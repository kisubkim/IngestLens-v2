"""Run the pipeline in-process for scripts (benchmarks, evaluations). Import setup() before anything from app."""

import asyncio
import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def setup(workdir: Path, models_file: Path | None = None) -> None:
    """Point the app at a scratch data dir (and optionally another models.yaml). Must run before importing app."""
    os.environ["RAG_DATA_DIR"] = str(workdir / "data")
    if models_file:
        os.environ["RAG_MODELS_FILE"] = str(models_file)
    sys.path.insert(0, str(ROOT / "backend"))


async def ingest(path: Path) -> tuple[str, str, dict]:
    """Run the full pipeline on one file. Returns (doc_id, run_id, run summary)."""
    from app.db import init_db, session
    from app.events import bus
    from app.graph.pipeline import run_pipeline
    from app.models import Document, Run

    init_db()
    bus.bind(asyncio.get_running_loop())
    with session() as s:
        doc = Document(filename=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size=path.stat().st_size, path=str(path))
        s.add(doc)
        s.flush()
        run = Run(document_id=doc.id)
        s.add(run)
        s.flush()
        doc_id, run_id = doc.id, run.id
    await run_pipeline(run_id, doc_id)
    with session() as s:
        r = s.get(Run, run_id)
        if r.status != "succeeded":
            raise RuntimeError(f"{path.name}: {r.status} {r.error}")
        return doc_id, run_id, r.summary


def shutdown() -> None:
    from app.tools import vectorstore

    vectorstore.close()
