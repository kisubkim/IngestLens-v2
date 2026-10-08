"""Retrieval agent: dense, lexical (BM25) or hybrid (RRF) search over one run's chunks, optional rerank.

Every hit carries its score at each stage so the UI can show why it ranked where it did.
"""

import asyncio
import time

from sqlalchemy import select

from ..db import session
from ..models import Chunk, Run
from ..tools import vectorstore
from ..tools.embedding import Embedder
from ..tools.lexical import index_for
from ..tools.reranker import Reranker

RRF_K = 60  # standard reciprocal-rank-fusion constant; damps the gap between rank 1 and rank 2


def latest_run(doc_id: str) -> str | None:
    with session() as s:
        return s.scalars(select(Run.id).where(Run.document_id == doc_id, Run.status == "succeeded")
                         .order_by(Run.created_at.desc())).first()


def _ms(t0: float) -> int:
    return round((time.perf_counter() - t0) * 1000)


async def search(query: str, top_k: int = 5, doc_id: str | None = None, run_id: str | None = None,
                 mode: str = "hybrid", rerank: bool = False, dense_weight: float = 1.0, lexical_weight: float = 1.0) -> dict:
    run_id = run_id or (latest_run(doc_id) if doc_id else None)
    out = {"run_id": run_id, "mode": mode, "hits": [], "notes": [], "timings_ms": {}}
    if not run_id:
        out["notes"].append("no succeeded run for this document")
        return out
    with session() as s:
        chunks = {c.id: c for c in s.scalars(select(Chunk).where(Chunk.run_id == run_id))}
    cand_n = max(top_k * 4, 20)

    dense: dict[str, tuple[int, float]] = {}
    if mode in ("dense", "hybrid"):
        t0 = time.perf_counter()
        emb = Embedder()
        vec = (await emb.embed([query]))[0]
        name = vectorstore.collection_name(emb.model, len(vec))
        out |= {"model": emb.model, "collection": name}
        if await asyncio.to_thread(vectorstore.client().collection_exists, name):
            hits = await asyncio.to_thread(vectorstore.search, name, vec, cand_n, None, run_id)
            dense = {h["chunk_id"]: (i + 1, h["score"]) for i, h in enumerate(hits) if h["chunk_id"] in chunks}
        if not dense and chunks:
            out["notes"].append("dense index has no vectors for this run (a later run of the same document replaced them)")
        out["timings_ms"]["dense"] = _ms(t0)

    lexical: dict[str, tuple[int, float]] = {}
    if mode in ("lexical", "hybrid"):
        t0 = time.perf_counter()
        idx, ids = await asyncio.to_thread(index_for, run_id, [(cid, c.text) for cid, c in sorted(chunks.items())])
        scores = await asyncio.to_thread(idx.scores, query)
        ranked = sorted(((sc, cid) for cid, sc in zip(ids, scores) if sc > 0), reverse=True)[:cand_n]
        lexical = {cid: (i + 1, sc) for i, (sc, cid) in enumerate(ranked)}
        out["timings_ms"]["lexical"] = _ms(t0)

    def final(cid: str) -> float:
        if mode == "dense":
            return dense[cid][1]
        if mode == "lexical":
            return lexical[cid][1]
        return (dense_weight / (RRF_K + dense[cid][0]) if cid in dense else 0.0) + \
               (lexical_weight / (RRF_K + lexical[cid][0]) if cid in lexical else 0.0)

    candidates = sorted(set(dense) | set(lexical), key=final, reverse=True)
    out["candidates"] = len(candidates)

    reranker = Reranker()
    rerank_scores: dict[str, float] = {}
    if rerank and not reranker.enabled:
        out["notes"].append("rerank requested but models.yaml reranker.base_url is empty")
    elif rerank and candidates:
        t0 = time.perf_counter()
        pool = candidates[: max(top_k * 3, top_k)]
        scores = await reranker.rerank(query, [chunks[c].text for c in pool])
        rerank_scores = dict(zip(pool, scores))
        candidates = sorted(pool, key=lambda c: rerank_scores[c], reverse=True)
        out["reranker"] = reranker.model
        out["timings_ms"]["rerank"] = _ms(t0)

    for i, cid in enumerate(candidates[:top_k]):
        c = chunks[cid]
        out["hits"].append({
            "rank": i + 1, "chunk_id": cid, "seq": c.seq, "text": c.text, "tokens": c.tokens, "pages": c.pages,
            "bboxes": c.bboxes, "section": c.section, "element_types": c.element_types,
            "scores": {
                "dense": dense.get(cid, (None, None))[1], "dense_rank": dense.get(cid, (None, None))[0],
                "lexical": lexical.get(cid, (None, None))[1], "lexical_rank": lexical.get(cid, (None, None))[0],
                "fused": final(cid) if mode == "hybrid" else None,
                "rerank": rerank_scores.get(cid),
            },
            # Kept for callers of the M1 API.
            "score": rerank_scores.get(cid, final(cid)),
        })
    return out
