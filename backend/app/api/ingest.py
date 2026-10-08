"""HTTP entry points for other systems: upload files and run the pipeline without the UI.

- `POST /api/ingest`: multipart files; queues one run per file and returns at once.
- `PUT /api/openwebui/process`: Open WebUI "External" document loader. Open WebUI sends the raw file
  (filename in `X-Filename`, URL-encoded) and waits for `[{page_content, metadata}]`; we answer with our chunks.
"""

import asyncio
import mimetypes
import time
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from sqlalchemy import select

from ..config import settings
from ..db import session
from ..graph.pipeline import start_run
from ..models import Chunk, Document, Run, to_dict
from .auth import require_key
from .documents import _save, save_stream

# Python's mimetypes table misses some Office types on Windows; the extension decides the Office parser.
_MIME_EXT = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/msword": ".doc",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.ms-excel": ".xls",
    "application/x-hwp": ".hwp",
    "image/jpeg": ".jpg",
}


router = APIRouter(prefix="/api", tags=["ingest"], dependencies=[Depends(require_key)])


def queue_run(doc_id: str) -> tuple[dict, bool]:
    """Reuse the document's latest run unless it failed or was cancelled; otherwise queue a new one.
    Returns (run, created)."""
    with session() as s:
        latest = s.scalars(select(Run).where(Run.document_id == doc_id).order_by(Run.created_at.desc())).first()
        if latest and latest.status in ("queued", "running", "succeeded"):
            return to_dict(latest), False
        run = Run(document_id=doc_id)
        s.add(run)
        s.flush()
        out = to_dict(run)
    start_run(out["id"], doc_id)
    return out, True


@router.post("/ingest")
async def ingest(files: list[UploadFile] = File()) -> list[dict]:
    """Save the files and queue their runs in the given order. Poll `GET /api/runs/{run.id}` for progress."""
    out = []
    for f in files:
        doc = await _save(f)
        run, created = queue_run(doc["id"])
        out.append({"document": doc, "run": run, "run_created": created})
    return out


def _filename(x_filename: str | None, content_type: str | None) -> str:
    name = Path(unquote(x_filename or "")).name
    if Path(name).suffix:
        return name
    mime = (content_type or "").split(";")[0].strip().lower()
    ext = _MIME_EXT.get(mime) or mimetypes.guess_extension(mime) or ""
    return (name or "upload") + ext


async def _wait(run_id: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        with session() as s:
            run = to_dict(s.get(Run, run_id))
        if run["status"] not in ("queued", "running"):
            return run
        if time.monotonic() > deadline:
            raise HTTPException(504, f"run {run_id} still {run['status']} after {timeout:.0f}s")
        await asyncio.sleep(1)


@router.put("/openwebui/process")
async def openwebui_process(
    request: Request,
    x_filename: str | None = Header(None),
    content_type: str | None = Header(None),
) -> list[dict]:
    filename = _filename(x_filename, content_type)
    doc = await save_stream(filename, request.stream())
    run, _ = queue_run(doc["id"])
    run = await _wait(run["id"], settings.ingest_wait_seconds)
    if run["status"] != "succeeded":
        raise HTTPException(502, f"run {run['id']} {run['status']}: {run['error']}")

    with session() as s:
        name = s.get(Document, doc["id"]).filename
        chunks = s.scalars(select(Chunk).where(Chunk.run_id == run["id"]).order_by(Chunk.seq)).all()
        # Metadata values stay scalar: some vector stores behind Open WebUI reject lists.
        # `page` is 0-based like LangChain's PDF loaders: Open WebUI shows it as page + 1 and opens `#page={page + 1}`.
        # `page_label` and `pages` are the 1-based numbers people read.
        return [
            {
                "page_content": c.text,
                "metadata": {
                    "source": name,
                    "document_id": doc["id"],
                    "run_id": run["id"],
                    "chunk_id": c.id,
                    **({"page": min(c.pages), "page_label": str(min(c.pages) + 1)} if c.pages else {}),
                    "pages": ",".join(str(p + 1) for p in c.pages),
                    "section": c.section or "",
                    "element_types": ",".join(c.element_types),
                },
            }
            for c in chunks
        ]
