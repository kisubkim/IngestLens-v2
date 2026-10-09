"""Chunker agent: apply the planned chunking strategy to parsed elements."""

import asyncio

from sqlalchemy import select

from ..db import session
from ..events import emit_event, record_decision
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

    cpt, min_tokens = cfg.get("chars_per_token", CHARS_PER_TOKEN), cfg.get("min_tokens", 0)
    chunks = await asyncio.to_thread(chunk_elements, els, cfg["strategy"], cfg["target_tokens"], cfg["overlap_tokens"], cpt, min_tokens)
    if min_tokens:
        before = len(await asyncio.to_thread(chunk_elements, els, cfg["strategy"], cfg["target_tokens"], cfg["overlap_tokens"], cpt))
        record_decision(
            run_id, STEP, "short chunks", f"merged {before} -> {len(chunks)} chunks (min {min_tokens} tokens)", rule_id="chunk_merge",
            inputs={"min_tokens": min_tokens, "max_tokens": cfg["target_tokens"] + min_tokens, "before": before, "after": len(chunks)},
            alternatives=[{"choice": "keep every short chunk", "reason_rejected":
                           "a heading, one-row table or one-line note alone loses its context in search (e.g. a register name and its value)"}],
            confidence=0.8,
            reasoning="Chunks under the minimum are merged into the next (else the previous) chunk of the same section, "
                      "keeping all their pages and boxes; tables and figures are not split by this.")
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
