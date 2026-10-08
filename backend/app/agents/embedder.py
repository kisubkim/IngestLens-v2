"""Embedding agent: embed chunks and index them in Qdrant."""

import asyncio
import math
import time

from sqlalchemy import select, update

from ..config import models_cfg
from ..db import session
from ..events import emit_event, record_decision
from ..models import Chunk
from ..tools import vectorstore
from ..tools.embedding import Embedder
from .common import PipelineState, update_summary

STEP = "embed"


async def embed(state: PipelineState) -> dict:
    run_id, doc_id = state["run_id"], state["doc_id"]
    emb = Embedder()
    cfg = models_cfg()["embedding"]
    if emb.remote:
        record_decision(run_id, STEP, "embedding model", cfg["model"], rule_id="configured_endpoint",
                        inputs={"base_url": cfg["base_url"], "max_tokens": cfg["max_tokens"]}, confidence=1.0)
    else:
        record_decision(run_id, STEP, "embedding model", "dev-hash", rule_id="embedding_not_configured",
                        alternatives=[{"choice": cfg["model"], "reason_rejected": "models.yaml embedding.base_url is empty"}],
                        confidence=0.2,
                        reasoning="Development fallback: trigram hashing captures lexical overlap only. Configure a vLLM embedding endpoint for real retrieval.")

    with session() as s:
        chunks = [(c.id, c.seq, c.text, c.pages, c.section, c.element_types)
                  for c in s.scalars(select(Chunk).where(Chunk.run_id == run_id).order_by(Chunk.seq))]

    t0 = time.perf_counter()
    batch = cfg.get("batch_size", 32)
    name, norms = None, []
    for start in range(0, len(chunks), batch):
        part = chunks[start:start + batch]
        vecs = await emb.embed([c[2] for c in part])
        if name is None:
            name = vectorstore.collection_name(emb.model, len(vecs[0]))
            await asyncio.to_thread(vectorstore.ensure_collection, name, len(vecs[0]))
            await asyncio.to_thread(vectorstore.delete_document, name, doc_id)  # re-run replaces the old index
        items = [(cid, v, {"doc_id": doc_id, "run_id": run_id, "chunk_id": cid, "seq": seq, "text": text,
                           "pages": pages, "section": section, "element_types": types})
                 for (cid, seq, text, pages, section, types), v in zip(part, vecs)]
        await asyncio.to_thread(vectorstore.upsert, name, items)
        norms += [math.sqrt(sum(x * x for x in v)) for v in vecs]
        with session() as s:
            s.execute(update(Chunk).where(Chunk.id.in_([c[0] for c in part])).values(embedded=True))
        done = start + len(part)
        emit_event(run_id, "progress", STEP, f"Embedded chunks {done}/{len(chunks)}", {"done": done, "total": len(chunks)})

    secs = time.perf_counter() - t0
    stats = {"model": emb.model, "dim": emb.dim, "collection": name, "count": len(chunks), "seconds": round(secs, 2),
             "chunks_per_s": round(len(chunks) / secs, 1) if secs else None}
    if norms:
        stats |= {"norm_min": round(min(norms), 4), "norm_avg": round(sum(norms) / len(norms), 4), "norm_max": round(max(norms), 4)}
    update_summary(run_id, "embed", stats)
    return {}
