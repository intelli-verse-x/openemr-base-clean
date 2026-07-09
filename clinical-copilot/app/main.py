"""FastAPI entrypoint for the Clinical Co-Pilot service."""
from __future__ import annotations

import contextlib

import httpx
from fastapi import FastAPI, Request, Response
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

    all_ok = all(c.ok for c in checks)
    body = ReadyResponse(status="ready" if all_ok else "not_ready", checks=checks)
    return JSONResponse(status_code=200 if all_ok else 503, content=body.model_dump())


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    return await handle_chat(req)


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/", response_class=HTMLResponse)
async def panel() -> str:
    return PANEL_HTML
