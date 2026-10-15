"""Binary analysis tools for an LLM (Open WebUI "tool server"): its own small app mounted at /api/tools/binary, so
its OpenAPI document (/api/tools/binary/openapi.json) lists only these operations and their descriptions.

The model gets the file's overview (tools/binview.py), reads byte ranges, proposes a format spec, has the whole
file decoded and checked (tools/binspec.py), looks up values and exports JSON. Every POST needs RAG_API_KEY when it
is set; export downloads are plain links (the name is a hash, like the page images).
"""

import hashlib
import json
import re
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..config import settings
from ..db import session
from ..models import Document
from ..tools import binspec, binview
from .auth import require_key

READ_MAX = 4096
# Open WebUI stores uploads as "<uuid4>_<original name>"; the download keeps the original name.
OPENWEBUI_PREFIX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_(?=.)", re.I)
RECORDS_MAX = 200
SPEC_DOC = "Format spec as YAML text.\n" + binview.SPEC_HELP

tools_app = FastAPI(
    title="IngestLens binary tools",
    version="1.0",
    description="Work out the format of a binary file (for example a device log) and decode it. Start with "
                "binary_overview, write a spec, check it with binary_decode until there are no warnings and the values "
                "make sense, then use binary_records for specific values or binary_export for the whole file as JSON.",
    root_path_in_servers=False,
)
guard = [Depends(require_key)]


def _doc(ref: str) -> Document:
    """A document by id, or by file name (the newest one; Open WebUI's '<uuid>_' prefix is allowed either way)."""
    ref = (ref or "").strip()
    with session() as s:
        d = s.get(Document, ref)
        if d is None:
            rows = s.scalars(select(Document).order_by(Document.created_at.desc())).all()
            d = next((r for r in rows if r.filename == ref or r.filename.endswith("_" + ref) or ref.endswith("_" + r.filename)), None)
    if d is None:
        raise HTTPException(404, f"no document {ref!r}; use the document_id from the overview or binary_list")
    return d


def _spec(text: str) -> dict:
    try:
        return binspec.parse_spec(text)
    except binspec.SpecError as e:
        raise HTTPException(422, f"spec error: {e}") from None


class DocRef(BaseModel):
    document: str = Field(description="document_id from the overview, or the file name")


class ReadReq(DocRef):
    offset: int = Field(0, ge=0, description="byte offset to start at (decimal)")
    length: int = Field(256, ge=1, le=READ_MAX, description=f"number of bytes (at most {READ_MAX})")


class SpecReq(DocRef):
    spec: str = Field(description=SPEC_DOC)


class RecordsReq(SpecReq):
    start: int = Field(0, ge=0, description="first record index (0-based)")
    count: int = Field(10, ge=1, le=RECORDS_MAX, description=f"how many records (at most {RECORDS_MAX})")
    fields: list[str] | None = Field(None, description="only these field names (default: all)")


@tools_app.post("/list", operation_id="binary_list", dependencies=guard)
def list_binaries(limit: int = 20) -> list[dict]:
    """The most recent binary files ingested (id, name, size), newest first."""
    with session() as s:
        rows = s.scalars(select(Document).where(Document.format == "binary").order_by(Document.created_at.desc())
                         .limit(max(1, min(limit, 100)))).all()
        return [{"document_id": d.id, "filename": d.filename, "size": d.size, "created_at": d.created_at.isoformat()} for d in rows]


@tools_app.post("/overview", operation_id="binary_overview", dependencies=guard)
def overview(req: DocRef) -> dict:
    """The file's overview: size, entropy, likely record size and header size, field candidates (constant bytes,
    counters, timestamps, floats), sample records and the header as hex, strings with offsets, and the spec format."""
    d = _doc(req.document)
    src = settings.resolve(d.path)
    text_file = settings.data_dir / "converted" / d.id / "binary_overview.txt"
    text = text_file.read_text(encoding="ascii") if text_file.exists() else binview.overview_text(d.filename, d.id, binview.analyse(src))
    return {"document_id": d.id, "filename": d.filename, "size": d.size, "overview": text}


@tools_app.post("/read", operation_id="binary_read_bytes", dependencies=guard)
def read_bytes(req: ReadReq) -> dict:
    """Bytes of the file as a hex dump (offset, hex, ASCII), to look at a region the overview does not show."""
    d = _doc(req.document)
    with open(settings.resolve(d.path), "rb") as f:
        f.seek(req.offset)
        data = f.read(req.length)
    if not data:
        raise HTTPException(416, f"offset {req.offset} is past the end of the file ({d.size} bytes)")
    return {"document_id": d.id, "offset": req.offset, "length": len(data), "file_size": d.size,
            "hex": binview.hexdump(data, req.offset)}


@tools_app.post("/decode", operation_id="binary_decode", dependencies=guard)
def decode(req: SpecReq) -> dict:
    """Decode the whole file with the spec and check it: record count, bytes left over, header values, per-field
    statistics (range, NaN count, how often values increase, the range if the byte order were the other one),
    warnings that point at a wrong guess, and the first records. Fix the spec until warnings is empty."""
    d = _doc(req.document)
    try:
        return {"document_id": d.id, **binspec.decode(settings.resolve(d.path), _spec(req.spec))}
    except binspec.SpecError as e:
        raise HTTPException(422, f"spec error: {e}") from None


@tools_app.post("/records", operation_id="binary_records", dependencies=guard)
def records(req: RecordsReq) -> dict:
    """Values of specific records decoded with the spec (for questions like 'the temperature of record 1532')."""
    d = _doc(req.document)
    try:
        return {"document_id": d.id, **binspec.records(settings.resolve(d.path), _spec(req.spec), req.start, req.count, req.fields)}
    except binspec.SpecError as e:
        raise HTTPException(422, f"spec error: {e}") from None


@tools_app.post("/export", operation_id="binary_export", dependencies=guard)
def export(req: SpecReq, request: Request) -> dict:
    """The whole file decoded with the spec as one JSON file ({"header": {...}, "records": [...]}). Returns a download
    link to give the user; the JSON itself is too large for the chat."""
    d = _doc(req.document)
    spec = _spec(req.spec)
    name = hashlib.sha256((d.id + json.dumps(spec, sort_keys=True)).encode()).hexdigest()[:20] + ".json"
    out = _export_dir(d.id) / name
    res = binspec.export_json(settings.resolve(d.path), spec, out) if not out.exists() else {
        "records": binspec.layout(spec, d.size)["count"], "bytes": out.stat().st_size}
    base = (settings.public_url or str(request.base_url).replace("/api/tools/binary/", "/")).rstrip("/")
    stem = OPENWEBUI_PREFIX.sub("", Path(d.filename).stem)
    return {"document_id": d.id, **res, "download_url": f"{base}/api/tools/binary/exports/{d.id}/{name}?save_as={stem}.json"}


def _export_dir(doc_id: str) -> Path:
    return settings.data_dir / "converted" / doc_id / "exports"


@tools_app.get("/exports/{doc_id}/{name}", include_in_schema=False)
def download(doc_id: str, name: str, save_as: str | None = None):
    if "/" in name or "\\" in name or ".." in name or not name.endswith(".json"):
        raise HTTPException(400, "bad name")
    path = _export_dir(doc_id) / name
    if not path.exists():
        raise HTTPException(404, "export not found; run binary_export again")
    return FileResponse(path, media_type="application/json", filename=save_as or name)
