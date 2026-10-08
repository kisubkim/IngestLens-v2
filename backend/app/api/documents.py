import asyncio
import hashlib
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select

from ..config import settings
from ..db import session
from ..graph.pipeline import start_run
from ..models import Document, Run, to_dict
from ..tools.toolpdf import engine
from ..tools.purge import active_runs, purge_all, purge_documents
from .auth import require_admin

router = APIRouter(prefix="/api/documents", tags=["documents"])
CHUNK = 1 << 20


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w.\- ]+", "_", Path(name).name) or "upload"


async def _read_upload(file: UploadFile) -> AsyncIterator[bytes]:
    while data := await file.read(CHUNK):
        yield data


async def _save(file: UploadFile) -> dict:
    return await save_stream(file.filename or "upload", _read_upload(file))


async def save_stream(filename: str, stream: AsyncIterator[bytes]) -> dict:
    """Stream to disk while hashing; an identical file returns the existing document."""
    doc_id = uuid.uuid4().hex
    dest_dir = settings.data_dir / "uploads" / doc_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / _safe_name(filename)
    h, size = hashlib.sha256(), 0
    with dest.open("wb") as f:
        async for data in stream:
            h.update(data)
            size += len(data)
            f.write(data)
    if not size:
        dest.unlink()
        dest_dir.rmdir()
        raise HTTPException(400, "empty file")
    digest = h.hexdigest()

    with session() as s:
        existing = s.scalars(select(Document).where(Document.sha256 == digest)).first()
        if existing:
            dest.unlink()
            dest_dir.rmdir()
            return {**to_dict(existing), "duplicate": True}
        doc = Document(id=doc_id, filename=filename or dest.name, sha256=digest, size=size, path=settings.stored_path(dest))
        s.add(doc)
        s.flush()
        return {**to_dict(doc), "duplicate": False}


@router.post("")
async def upload(file: UploadFile) -> dict:
    return await _save(file)


@router.post("/batch")
async def upload_many(files: list[UploadFile] = File()) -> list[dict]:
    """Save several files from one request. Each file is stored on its own; duplicates stay duplicates."""
    if not files:
        raise HTTPException(400, "no files")
    return [await _save(f) for f in files]


class BatchRunRequest(BaseModel):
    document_ids: list[str]


@router.post("/runs")
async def create_runs(req: BatchRunRequest) -> list[dict]:
    """Queue one run per document, in the given order. Runs execute one at a time in that order."""
    ids = list(dict.fromkeys(req.document_ids))
    if not ids:
        raise HTTPException(400, "no documents")
    with session() as s:
        missing = [i for i in ids if not s.get(Document, i)]
        if missing:
            raise HTTPException(404, f"document not found: {', '.join(missing)}")
        runs = [Run(document_id=i) for i in ids]
        s.add_all(runs)
        s.flush()
        out = [to_dict(r) for r in runs]
    for r in out:
        start_run(r["id"], r["document_id"])
    return out


@router.get("")
def list_documents() -> list[dict]:
    with session() as s:
        docs = s.scalars(select(Document).order_by(Document.created_at.desc())).all()
        latest = {}
        for r in s.scalars(select(Run).order_by(Run.created_at)):
            latest[r.document_id] = r
        return [{**to_dict(d), "latest_run": to_dict(latest[d.id]) if d.id in latest else None} for d in docs]


def _doc(doc_id: str) -> Document:
    with session() as s:
        d = s.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "document not found")
    return d


@router.get("/{doc_id}")
def get_document(doc_id: str) -> dict:
    return to_dict(_doc(doc_id))


@router.post("/{doc_id}/runs")
async def create_run(doc_id: str) -> dict:
    _doc(doc_id)
    with session() as s:
        run = Run(document_id=doc_id)
        s.add(run)
        s.flush()
        out = to_dict(run)
    start_run(out["id"], doc_id)
    return out


@router.delete("", dependencies=[Depends(require_admin)])
async def delete_all(confirm: str = "") -> dict:
    """Every document with its runs, chunks, vectors and files. Needs ?confirm=all so it cannot happen by accident."""
    if confirm != "all":
        raise HTTPException(400, "add ?confirm=all to delete every document")
    if busy := active_runs():
        raise HTTPException(409, f"{len(busy)} run(s) still queued or running; cancel them first")
    return await asyncio.to_thread(purge_all)


@router.delete("/{doc_id}", dependencies=[Depends(require_admin)])
async def delete_document(doc_id: str) -> dict:
    """The document with its runs, chunks, vectors, uploaded file, converted PDF and page images."""
    _doc(doc_id)
    if active_runs([doc_id]):
        raise HTTPException(409, "this document has a queued or running run; cancel it first")
    return await asyncio.to_thread(purge_documents, [doc_id])


def _render_cached(pdf_path: str, page: int, dpi: int, out: Path) -> None:
    png = engine().render(Path(pdf_path), page, dpi)  # IndexError when the page does not exist
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png)


@router.get("/{doc_id}/pages/{page}.png")
async def page_image(doc_id: str, page: int, dpi: int = 96) -> FileResponse:
    """0-based page render, cached on disk. Coordinates of bboxes are PDF points (72 dpi)."""
    d = _doc(doc_id)
    if not d.pdf_path:
        raise HTTPException(409, "document not converted yet; start a run first")
    dpi = max(18, min(dpi, 300))
    out = settings.data_dir / "pages" / doc_id / f"{page}_{dpi}.png"
    if not out.exists():
        try:
            await asyncio.to_thread(_render_cached, str(settings.resolve(d.pdf_path)), page, dpi, out)
        except IndexError:
            raise HTTPException(404, "page out of range")
    return FileResponse(out, media_type="image/png")
