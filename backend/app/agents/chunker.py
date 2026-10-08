"""Chunker agent: apply the planned chunking strategy to parsed elements."""

import asyncio

from sqlalchemy import select

from ..db import session
from ..events import emit_event
from ..models import Chunk, Element
from ..tools.chunking import CHARS_PER_TOKEN, chunk_elements, chunk_stats
from .common import PipelineState, update_summary

STEP = "chunk"


async def chunk(state: PipelineState) -> dict:
    run_id = state["run_id"]
    cfg = state["plan"]["chunking"]

    with session() as s:
        els = [
            {"page": e.page, "type": e.type, "bbox": e.bbox, "content": e.content}
            for e in s.scalars(select(Element).where(Element.run_id == run_id).order_by(Element.page, Element.seq))
        ]

    chunks = await asyncio.to_thread(chunk_elements, els, cfg["strategy"], cfg["target_tokens"], cfg["overlap_tokens"],
                                     cfg.get("chars_per_token", CHARS_PER_TOKEN))
    with session() as s:
        s.add_all(
            Chunk(id=f"{run_id[:8]}-{i:05d}", run_id=run_id, document_id=state["doc_id"], seq=i, strategy_id=cfg["strategy"], **c)
            for i, c in enumerate(chunks)
        )

    stats = chunk_stats(chunks, cfg["target_tokens"])
    stats["strategy"] = cfg["strategy"]
    update_summary(run_id, "chunk", stats)
    if stats["count"] and (stats["too_short"] + stats["too_long"]) / stats["count"] > 0.2:
        emit_event(run_id, "warning", STEP, f"{stats['too_short']} short and {stats['too_long']} long chunks out of {stats['count']}", stats)
    return {}
