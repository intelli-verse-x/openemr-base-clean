"""Document storage — demo filesystem backing store (OpenEMR FHIR write path documented in W2_ARCHITECTURE)."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from ..config import get_settings
from ..observability import log

_STORE_ROOT = Path(__file__).resolve().parents[3] / "data" / "w2_documents"


def _root() -> Path:
    _STORE_ROOT.mkdir(parents=True, exist_ok=True)
    return _STORE_ROOT


def store_document(patient_id: int, filename: str, content: bytes) -> str:
    doc_id = f"doc-{uuid.uuid4().hex[:12]}"
    patient_dir = _root() / str(patient_id)
    patient_dir.mkdir(parents=True, exist_ok=True)
    path = patient_dir / f"{doc_id}_{filename}"
    path.write_bytes(content)
    meta = {
        "document_id": doc_id,
        "patient_id": patient_id,
        "filename": filename,
        "sha256": hashlib.sha256(content).hexdigest(),
        "path": str(path),
    }
    (patient_dir / f"{doc_id}.meta.json").write_text(json.dumps(meta))
    log.info("w2 doc stored", extra={"document_id": doc_id, "patient_id": patient_id, "bytes": len(content)})
    return doc_id


def load_document_path(patient_id: int, document_id: str) -> Path | None:
    patient_dir = _root() / str(patient_id)
    for p in patient_dir.glob(f"{document_id}_*"):
        if p.suffix != ".json":
            return p
    return None


def load_extraction(patient_id: int, document_id: str) -> dict | None:
    p = _root() / str(patient_id) / f"{document_id}.extraction.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def save_extraction(patient_id: int, document_id: str, payload: dict) -> None:
    p = _root() / str(patient_id) / f"{document_id}.extraction.json"
    p.write_text(json.dumps(payload, default=str))
