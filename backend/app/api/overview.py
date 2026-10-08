"""Home screen numbers: what is stored and indexed right now (documents, runs, vectors, disk use)."""

import asyncio

from fastapi import APIRouter
from sqlalchemy import func, select

from ..config import models_cfg, settings
from ..db import session
from ..models import Chunk, Document, Run, to_dict
from ..tools import vectorstore
from .settings import _usage

router = APIRouter(prefix="/api", tags=["overview"])


def _collections() -> list[dict]:
    """Collections are named chunks__<model>__<dim> (vectorstore.collection_name)."""
    out = []
    c = vectorstore.client()
    for col in c.get_collections().collections:
        if not col.name.startswith("chunks__"):
            continue
        _, model, dim = (col.name.split("__") + ["", ""])[:3]
        out.append({"name": col.name, "model": model, "dim": int(dim) if dim.isdigit() else None,
                    "points": c.count(col.name, exact=True).count})
    return out


def _overview() -> dict:
    with session() as s:
        docs = s.execute(select(func.count(Document.id), func.coalesce(func.sum(Document.size), 0),
                                func.coalesce(func.sum(Document.page_count), 0))).one()
        by_format = dict(s.execute(select(func.coalesce(Document.format, "미처리"), func.count()).group_by(Document.format)).all())
        by_status = dict(s.execute(select(Run.status, func.count()).group_by(Run.status)).all())
        # The latest run of each document is the one whose chunks are indexed (a re-run deletes older vectors).
        latest = select(Run.document_id, func.max(Run.created_at).label("at")).group_by(Run.document_id).subquery()
        latest_ids = select(Run.id).join(latest, (Run.document_id == latest.c.document_id) & (Run.created_at == latest.c.at))
        chunks = s.scalar(select(func.count(Chunk.id)).where(Chunk.run_id.in_(latest_ids))) or 0
        recent = []
        for d in s.scalars(select(Document).order_by(Document.created_at.desc()).limit(8)):
            run = s.scalars(select(Run).where(Run.document_id == d.id).order_by(Run.created_at.desc())).first()
            n = s.scalar(select(func.count(Chunk.id)).where(Chunk.run_id == run.id)) if run else 0
            recent.append({**to_dict(d), "latest_run": to_dict(run) if run else None, "chunks": n})
    collections = _collections()
    usage = _usage()
    emb = models_cfg().get("embedding") or {}
    return {
        "documents": {"count": docs[0], "bytes": docs[1], "pages": docs[2], "by_format": by_format},
        "runs": {"total": sum(by_status.values()), "by_status": by_status},
        "chunks": chunks,
        "vectors": {"total": sum(c["points"] for c in collections), "collections": collections,
                    "embedding_model": emb.get("model") if emb.get("base_url") else "dev-hash",
                    "embedding_configured": bool(emb.get("base_url"))},
        "storage": {"items": usage, "bytes": sum(u["bytes"] or 0 for u in usage), "data_dir": str(settings.data_dir)},
        "recent": recent,
    }


@router.get("/overview")
async def overview() -> dict:
    return await asyncio.to_thread(_overview)
