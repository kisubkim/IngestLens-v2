import json

import numpy as np
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sse_starlette.sse import EventSourceResponse

from ..db import session
from ..events import bus
from ..graph.pipeline import STEP_NAMES, cancel_run
from ..models import Chunk, Decision, Element, Event, PageProfile, Run, to_dict
from ..tools import vectorstore

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _run(run_id: str) -> Run:
    with session() as s:
        r = s.get(Run, run_id)
    if not r:
        raise HTTPException(404, "run not found")
    return r


@router.get("")
def list_runs(document_id: str | None = None) -> list[dict]:
    with session() as s:
        q = select(Run).order_by(Run.created_at.desc())
        if document_id:
            q = q.where(Run.document_id == document_id)
        return [to_dict(r) for r in s.scalars(q)]


@router.get("/{run_id}")
def get_run(run_id: str) -> dict:
    return {**to_dict(_run(run_id)), "steps": STEP_NAMES}


@router.post("/{run_id}/cancel")
def cancel(run_id: str) -> dict:
    run = _run(run_id)
    if run.status not in ("queued", "running"):
        raise HTTPException(409, f"run is {run.status}")
    return {"cancelled": cancel_run(run_id)}


@router.get("/{run_id}/events")
def list_events(run_id: str, after: int = 0) -> list[dict]:
    with session() as s:
        return [to_dict(e) for e in s.scalars(select(Event).where(Event.run_id == run_id, Event.id > after).order_by(Event.id))]


@router.get("/{run_id}/stream")
async def stream(run_id: str, request: Request, after: int = 0):
    """SSE: replay stored events after `after`, then push live ones. Ends on run_finished."""
    _run(run_id)
    q = bus.subscribe(run_id)  # subscribe before replay so nothing falls in the gap

    async def gen():
        last = after
        try:
            for ev in list_events(run_id, after):
                last = ev["id"]
                yield {"id": str(ev["id"]), "event": "run_event", "data": json.dumps(ev, ensure_ascii=False)}
                if ev["type"] == "run_finished":
                    return
            while not await request.is_disconnected():
                ev = await q.get()
                if ev["id"] <= last:
                    continue
                last = ev["id"]
                yield {"id": str(ev["id"]), "event": "run_event", "data": json.dumps(ev, ensure_ascii=False)}
                if ev["type"] == "run_finished":
                    return
        finally:
            bus.unsubscribe(run_id, q)

    return EventSourceResponse(gen(), ping=15)


@router.get("/{run_id}/decisions")
def decisions(run_id: str, step: str | None = None, subject: str | None = None) -> list[dict]:
    with session() as s:
        q = select(Decision).where(Decision.run_id == run_id).order_by(Decision.id)
        if step:
            q = q.where(Decision.step == step)
        if subject:
            q = q.where(Decision.subject == subject)
        return [to_dict(d) for d in s.scalars(q)]


@router.get("/{run_id}/parsed.md", response_class=PlainTextResponse)
def parsed_markdown(run_id: str) -> str:
    """Whole parse result as one Markdown document, page by page."""
    _run(run_id)
    out, page = [], None
    with session() as s:
        for e in s.scalars(select(Element).where(Element.run_id == run_id).order_by(Element.page, Element.seq)):
            if e.page != page:
                page = e.page
                out.append(f"<!-- page {page + 1} -->")
            out.append(f"## {e.content}" if e.type == "title" else e.content)
    return "\n\n".join(out) + "\n"


@router.get("/{run_id}/pages")
def page_profiles(run_id: str) -> list[dict]:
    with session() as s:
        return [to_dict(p) for p in s.scalars(select(PageProfile).where(PageProfile.run_id == run_id).order_by(PageProfile.page))]


@router.get("/{run_id}/elements")
def elements(run_id: str, page: int | None = None) -> list[dict]:
    with session() as s:
        q = select(Element).where(Element.run_id == run_id).order_by(Element.page, Element.seq)
        if page is not None:
            q = q.where(Element.page == page)
        return [to_dict(e) for e in s.scalars(q)]


@router.get("/{run_id}/element-stats")
def element_stats(run_id: str) -> dict:
    """Per-page element counts by type and tool, for the parse report's chart. Pages without elements are included."""
    _run(run_id)
    with session() as s:
        profiles = {p.page: p for p in s.scalars(select(PageProfile).where(PageProfile.run_id == run_id))}
        rows = s.execute(select(Element.page, Element.type, Element.source_tool, func.count(), func.sum(func.length(Element.content)))
                         .where(Element.run_id == run_id).group_by(Element.page, Element.type, Element.source_tool)).all()
    pages: dict[int, dict] = {p: {"page": p, "label": pr.label, "parser": pr.parser, "total": 0, "chars": 0, "by_type": {}, "by_tool": {}}
                              for p, pr in profiles.items()}
    by_type: dict[str, int] = {}
    for page, typ, tool, n, chars in rows:
        row = pages.setdefault(page, {"page": page, "label": None, "parser": None, "total": 0, "chars": 0, "by_type": {}, "by_tool": {}})
        row["total"] += n
        row["chars"] += chars or 0
        row["by_type"][typ] = row["by_type"].get(typ, 0) + n
        row["by_tool"][tool] = row["by_tool"].get(tool, 0) + n
        by_type[typ] = by_type.get(typ, 0) + n
    ordered = [pages[p] for p in sorted(pages)]
    return {"total": sum(by_type.values()), "by_type": by_type, "pages": ordered,
            "empty_pages": [p["page"] for p in ordered if not p["total"]]}


@router.get("/{run_id}/chunks")
def chunks(run_id: str, offset: int = 0, limit: int = 200, page: int | None = None,
           type: str | None = None, q: str | None = None) -> dict:
    """Filters: page (0-based, chunks touching it), element type, substring in text or section."""
    with session() as s:
        rows = s.scalars(select(Chunk).where(Chunk.run_id == run_id).order_by(Chunk.seq)).all()
    if page is not None:
        rows = [c for c in rows if page in c.pages]
    if type:
        rows = [c for c in rows if type in c.element_types]
    if q:
        ql = q.lower()
        rows = [c for c in rows if ql in c.text.lower() or ql in (c.section or "").lower()]
    return {"total": len(rows), "items": [to_dict(c) for c in rows[offset:offset + min(limit, 1000)]]}


def _collection(run_id: str) -> str:
    embed = (_run(run_id).summary or {}).get("embed") or {}
    if not embed.get("collection"):
        raise HTTPException(409, "run has no embeddings")
    return embed["collection"]


@router.get("/{run_id}/embeddings")
def embeddings(run_id: str, limit: int = 5000) -> dict:
    """2D PCA projection of the run's chunk vectors, plus norm stats."""
    name = _collection(run_id)
    pairs = vectorstore.run_vectors(name, run_id, min(limit, 20000))
    if not pairs:
        return {"collection": name, "count": 0, "points": [], "note": "no vectors for this run (a later run replaced them)"}
    ids = [cid for cid, _ in pairs]
    x = np.asarray([v for _, v in pairs], dtype=np.float32)
    norms = np.linalg.norm(x, axis=1)
    centered = x - x.mean(axis=0)
    if len(ids) >= 3:
        _, sv, vt = np.linalg.svd(centered, full_matrices=False)
        xy = centered @ vt[:2].T
        var = (sv ** 2) / max(float((sv ** 2).sum()), 1e-12)
        explained = [round(float(v), 4) for v in var[:2]]
    else:
        xy, explained = np.zeros((len(ids), 2)), [0.0, 0.0]
    with session() as s:
        meta = {c.id: c for c in s.scalars(select(Chunk).where(Chunk.run_id == run_id))}
    points = [{"chunk_id": cid, "x": round(float(xy[i, 0]), 5), "y": round(float(xy[i, 1]), 5),
               "seq": meta[cid].seq, "pages": meta[cid].pages, "section": meta[cid].section,
               "element_types": meta[cid].element_types, "tokens": meta[cid].tokens,
               "preview": meta[cid].text[:160], "norm": round(float(norms[i]), 4)}
              for i, cid in enumerate(ids) if cid in meta]
    return {"collection": name, "dim": int(x.shape[1]), "count": len(points), "explained_variance": explained,
            "norm": {"min": round(float(norms.min()), 4), "mean": round(float(norms.mean()), 4), "max": round(float(norms.max()), 4)},
            "points": sorted(points, key=lambda p: p["seq"])}


@router.get("/{run_id}/chunks/{chunk_id}/neighbors")
def neighbors(run_id: str, chunk_id: str, k: int = 5) -> list[dict]:
    """Nearest chunks of the same run by cosine similarity."""
    name = _collection(run_id)
    vec = vectorstore.chunk_vector(name, chunk_id)
    if vec is None:
        raise HTTPException(404, "chunk has no vector")
    hits = vectorstore.search(name, vec, min(k, 50) + 1, run_id=run_id)
    return [{"chunk_id": h["chunk_id"], "score": round(h["score"], 4), "pages": h["pages"], "section": h["section"],
             "element_types": h["element_types"], "preview": h["text"][:160]}
            for h in hits if h["chunk_id"] != chunk_id][:k]
