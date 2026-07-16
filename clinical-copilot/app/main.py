"""FastAPI entrypoint for the Clinical Co-Pilot service."""
from __future__ import annotations

import contextlib

import httpx
from fastapi import FastAPI, File, Form, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import __version__, db
from .agent import handle_chat
from .config import get_settings
from .observability import configure_logging, get_correlation_id, get_tracer, log, new_correlation_id
from .schemas import ChatRequest, ChatResponse, HealthResponse, ReadyCheck, ReadyResponse
from .ui import PANEL_HTML


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await db.init_pool()
    log.info("clinical-copilot starting", extra={"version": __version__})
    yield
    get_tracer().flush()  # drain any queued Langfuse events before exit
    await db.close_pool()


app = FastAPI(title="Clinical Co-Pilot", version=__version__, lifespan=lifespan)


@app.middleware("http")
async def correlation_mw(request: Request, call_next):
    cid = request.headers.get("X-Correlation-ID") or new_correlation_id()
    from .observability import _correlation_id
    _correlation_id.set(cid)
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = get_correlation_id()
    return response


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness — is the process alive? No dependency checks."""
    return HealthResponse(status="alive", version=__version__)


@app.get("/ready", response_model=ReadyResponse)
async def ready() -> ReadyResponse:
    """Readiness — validates real dependencies (OpenEMR DB, LLM, observability)."""
    checks: list[ReadyCheck] = []
    s = get_settings()

    # OpenEMR database
    try:
        ok = await db.ping()
        checks.append(ReadyCheck(name="openemr_db", ok=ok, detail="SELECT 1"))
    except Exception as exc:
        checks.append(ReadyCheck(name="openemr_db", ok=False, detail=str(exc)))

    # LLM provider reachability (skip network call for mock)
    if s.llm_enabled:
        try:
            base = s.llm_base_url or "https://api.openai.com/v1"
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"{base.rstrip('/')}/models",
                                headers={"Authorization": f"Bearer {s.llm_api_key}"})
            checks.append(ReadyCheck(name="llm", ok=r.status_code < 500, detail=f"HTTP {r.status_code}"))
        except Exception as exc:
            checks.append(ReadyCheck(name="llm", ok=False, detail=str(exc)))
    else:
        checks.append(ReadyCheck(name="llm", ok=True, detail="mock mode"))

    # Observability backend
    tracer = get_tracer()
    checks.append(ReadyCheck(name="langfuse", ok=True,
                             detail="enabled" if tracer.enabled else "disabled (no-op)"))

    # Week 2 dependencies
    if s.w2_enabled:
        from .w2.rag.retriever import HybridRetriever

        retriever = HybridRetriever()
        checks.append(ReadyCheck(
            name="w2_guideline_index",
            ok=retriever.ready,
            detail=f"{len(retriever._chunks)} chunks" if retriever.ready else "empty corpus",
        ))
        checks.append(ReadyCheck(name="w2_document_store", ok=True, detail="filesystem demo store"))
        checks.append(ReadyCheck(
            name="w2_rerank",
            ok=True,
            detail="cohere" if s.w2_rerank_enabled else "hybrid-score fallback",
        ))

    all_ok = all(c.ok for c in checks)
    body = ReadyResponse(status="ready" if all_ok else "not_ready", checks=checks)
    return JSONResponse(status_code=200 if all_ok else 503, content=body.model_dump())


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    return await handle_chat(req)


@app.post("/w2/upload")
async def w2_upload(
    patient_id: int = Form(...),
    doc_type: str = Form(...),
    user_id: str = Form("admin"),
    role: str = Form("physician"),
    file: UploadFile = File(...),
):
    """Upload lab PDF or intake form, extract structured JSON with citations."""
    from pathlib import Path
    import tempfile

    from .schemas import Role as AppRole
    from .w2.ingest import attach_and_extract
    from .w2.schemas import DocType

    s = get_settings()
    if not s.w2_enabled:
        return JSONResponse(status_code=503, content={"error": "Week 2 flow disabled"})

    suffix = Path(file.filename or "upload.pdf").suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        result = await attach_and_extract(
            patient_id=patient_id,
            file_path=tmp_path,
            doc_type=DocType(doc_type),
            user_id=user_id,
            role=AppRole(role),
        )
        return result.model_dump()
    finally:
        tmp_path.unlink(missing_ok=True)


@app.post("/w2/chat")
async def w2_chat(req: Request):
    """Week 2 multimodal chat — supervisor routes intake-extractor + evidence-retriever."""
    from .w2.agent import handle_w2_chat
    from .w2.schemas import W2ChatRequest

    s = get_settings()
    if not s.w2_enabled:
        return JSONResponse(status_code=503, content={"error": "Week 2 flow disabled"})

    body = await req.json()
    return (await handle_w2_chat(W2ChatRequest.model_validate(body))).model_dump()


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/", response_class=HTMLResponse)
async def panel() -> str:
    return PANEL_HTML
