"""Small synthetic guideline corpus — demo only, no real PHI."""
from __future__ import annotations

from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "guidelines"


def load_chunks() -> list[dict]:
    chunks: list[dict] = []
    if not CORPUS_DIR.exists():
        return chunks
    for md in sorted(CORPUS_DIR.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        for idx, block in enumerate(text.split("\n\n")):
            block = block.strip()
            if len(block) < 40:
                continue
            chunks.append({
                "chunk_id": f"{md.stem}:{idx}",
                "source_doc": md.name,
                "section": md.stem.replace("-", " ").title(),
                "text": block,
            })
    return chunks
