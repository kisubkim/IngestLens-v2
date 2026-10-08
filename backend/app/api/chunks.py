"""Page image with one chunk's regions highlighted, for showing "where the answer came from" outside the app
(the Open WebUI page-image filter deploy/openwebui_page_images.py links these images)."""

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import settings
from ..db import session
from ..models import Chunk, Document
from ..tools.toolpdf import engine

router = APIRouter(prefix="/api/chunks", tags=["chunks"])


def _render_highlight(pdf_path: str, page: int, boxes: list[list[float]], dpi: int, out: Path) -> None:
    """The engine draws the boxes on an in-memory copy of the page and renders it; the PDF is not changed."""
    png = engine().render(Path(pdf_path), page, dpi, highlight=boxes or None)  # IndexError when the page does not exist
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png)


@router.get("/{chunk_id}/preview.png")
async def chunk_preview(chunk_id: str, page: int | None = None, dpi: int = 110, highlight: bool = True) -> FileResponse:
    """The chunk's page (0-based; default: its first page) with the chunk's element boxes highlighted.
    `highlight=false` gives the plain page. Cached next to the plain page images, so deleting the document
    removes these too."""
    with session() as s:
        c = s.get(Chunk, chunk_id)
        d = s.get(Document, c.document_id) if c else None
    if not c or not d:
        raise HTTPException(404, "chunk not found")
    if not d.pdf_path:
        raise HTTPException(409, "document not converted")
    on_page = lambda pg: [b["bbox"] for b in (c.bboxes or []) if b.get("page") == pg]  # noqa: E731
    if page is None:
        page = min((b["page"] for b in c.bboxes or []), default=min(c.pages or [0]))
    if page not in (c.pages or []) and not on_page(page):
        raise HTTPException(404, "the chunk is not on that page")
    dpi = max(18, min(dpi, 300))
    out = settings.data_dir / "pages" / d.id / f"chunk_{chunk_id}_{page}_{dpi}{'' if highlight else '_plain'}.png"
    if not out.exists():
        try:
            await asyncio.to_thread(_render_highlight, str(settings.resolve(d.pdf_path)), page,
                                    on_page(page) if highlight else [], dpi, out)
        except IndexError:
            raise HTTPException(404, "page out of range")
    return FileResponse(out, media_type="image/png")
