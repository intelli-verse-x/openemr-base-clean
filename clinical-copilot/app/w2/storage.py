"""Document + extraction storage — MariaDB-backed (multi-pod safe) with FS cache."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from .. import db
from ..observability import log

_STORE_ROOT = Path(__file__).resolve().parents[3] / "data" / "w2_documents"
_TABLE_READY = False


def _root() -> Path:
    _STORE_ROOT.mkdir(parents=True, exist_ok=True)
    return _STORE_ROOT


async def ensure_tables() -> None:
    global _TABLE_READY
    if _TABLE_READY:
        return
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS copilot_w2_documents (
          document_id VARCHAR(64) NOT NULL PRIMARY KEY,
          patient_id INT NOT NULL,
          filename VARCHAR(255) NOT NULL,
          sha256 CHAR(64) NOT NULL,
          content LONGBLOB NOT NULL,
          extraction_json LONGTEXT NULL,
          created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          INDEX idx_w2_docs_patient (patient_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _TABLE_READY = True
    log.info("w2 document table ready")


async def store_document(patient_id: int, filename: str, content: bytes) -> str:
    await ensure_tables()
    doc_id = f"doc-{uuid.uuid4().hex[:12]}"
    sha = hashlib.sha256(content).hexdigest()
    await db.execute(
        """
        INSERT INTO copilot_w2_documents
          (document_id, patient_id, filename, sha256, content)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (doc_id, patient_id, filename[:255], sha, content),
    )
    # Local cache for VLM path / preview (optional)
    patient_dir = _root() / str(patient_id)
    patient_dir.mkdir(parents=True, exist_ok=True)
    (patient_dir / f"{doc_id}_{filename}").write_bytes(content)
    log.info("w2 doc stored", extra={"document_id": doc_id, "patient_id": patient_id, "bytes": len(content)})
    return doc_id


async def load_extraction(patient_id: int, document_id: str) -> dict | None:
    await ensure_tables()
    row = await db.fetch_one(
        """
        SELECT extraction_json FROM copilot_w2_documents
        WHERE document_id = %s AND patient_id = %s LIMIT 1
        """,
        (document_id, patient_id),
    )
    if not row or not row.get("extraction_json"):
        # FS fallback (dev / pre-migration)
        p = _root() / str(patient_id) / f"{document_id}.extraction.json"
        if p.exists():
            return json.loads(p.read_text())
        return None
    return json.loads(row["extraction_json"])


async def save_extraction(patient_id: int, document_id: str, payload: dict) -> None:
    await ensure_tables()
    blob = json.dumps(payload, default=str)
    await db.execute(
        """
        UPDATE copilot_w2_documents
        SET extraction_json = %s
        WHERE document_id = %s AND patient_id = %s
        """,
        (blob, document_id, patient_id),
    )
    p = _root() / str(patient_id) / f"{document_id}.extraction.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(blob)


async def document_store_ready() -> bool:
    try:
        await ensure_tables()
        await db.fetch_one("SELECT 1 AS ok FROM copilot_w2_documents LIMIT 1")
        return True
    except Exception:
        # Empty table still means store works
        try:
            await ensure_tables()
            return await db.ping()
        except Exception:
            return False
