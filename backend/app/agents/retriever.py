"""Retrieval agent: dense, lexical (BM25) or hybrid (RRF) search over one run's chunks (`search`) or over the latest
run of every document (`search_all`), optional rerank.

Every hit carries its score at each stage so the UI can show why it ranked where it did.
"""

import asyncio
import hashlib
import re
import time

from sqlalchemy import select

from ..config import models_cfg
from ..db import session
from ..models import Chunk, Document, Run
from ..tools import vectorstore
from ..tools.embedding import Embedder
from ..tools.lexical import cached as lexical_cached
from ..tools.lexical import index_for
from ..tools.reranker import Reranker

RRF_K = 60  # standard reciprocal-rank-fusion constant; damps the gap between rank 1 and rank 2


def latest_run(doc_id: str) -> str | None:
    with session() as s:
        return s.scalars(select(Run.id).where(Run.document_id == doc_id, Run.status == "succeeded")
                         .order_by(Run.created_at.desc())).first()


def rerank_pool(top_k: int) -> int:
    """How many fused candidates the reranker scores: models.yaml reranker.candidates, else 3 x top_k."""
    n = (models_cfg().get("reranker") or {}).get("candidates")
    return max(int(n) if n else top_k * 3, top_k)


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
        run = s.get(Run, run_id)
        # The query instruction the run's chunks were embedded for (models.yaml may have changed since).
        indexed_prefix = ((run.summary or {}).get("embed") or {}).get("query_prefix") if run else None
    cand_n = max(top_k * 4, 20, rerank_pool(top_k) if rerank else 0)

    dense: dict[str, tuple[int, float]] = {}
    if mode in ("dense", "hybrid"):
        t0 = time.perf_counter()
        emb = Embedder()
        vec = (await emb.embed([query], "query", query_prefix=indexed_prefix))[0]
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
        pool = candidates[: rerank_pool(top_k)]
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


# ---------- all documents ----------

# Open WebUI stores uploads as "<uuid4>_<original name>"; results show the original name (like the UI's displayName).
_OWUI_PREFIX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_(?=.)", re.I)


def display_name(filename: str) -> str:
    return _OWUI_PREFIX.sub("", filename)


def scope(document_ids: list[str] | None = None) -> list[dict]:
    """The latest succeeded run of every document (or of the given ones): the runs the all-documents search covers."""
    with session() as s:
        q = select(Run.id, Run.document_id, Run.summary).where(Run.status == "succeeded")
        if document_ids:
            q = q.where(Run.document_id.in_(document_ids))
        latest: dict[str, tuple[str, dict]] = {}
        for rid, did, summary in s.execute(q.order_by(Run.created_at.desc())):
            latest.setdefault(did, (rid, summary or {}))
        names = dict(s.execute(select(Document.id, Document.filename).where(Document.id.in_(list(latest)))).all())
    out = []
    for did, (rid, summary) in latest.items():
        embed = summary.get("embed") or {}
        out.append({"run_id": rid, "document_id": did, "filename": names.get(did, ""),
                    "collection": embed.get("collection"), "query_prefix": embed.get("query_prefix")})
    return out


async def search_all(query: str, top_k: int = 5, document_ids: list[str] | None = None, mode: str = "hybrid",
                     rerank: bool = False, dense_weight: float = 1.0, lexical_weight: float = 1.0) -> dict:
    """Search every document's latest succeeded run at once. Dense search covers the runs embedded with the model in
    models.yaml now (one query embedding per query prefix those runs were indexed with); runs embedded with another
    model are searched by BM25 only and listed in notes. BM25 statistics (IDF) are over all covered chunks."""
    runs = scope(document_ids)
    by_run = {r["run_id"]: r for r in runs}
    out: dict = {"mode": mode, "documents": len(runs), "hits": [], "notes": [], "timings_ms": {}}
    if not runs:
        out["notes"].append("no document has a succeeded run")
        return out
    cand_n = max(top_k * 4, 20, rerank_pool(top_k) if rerank else 0)

    dense: dict[str, tuple[int, float]] = {}
    dense_runs: set[str] = set()
    if mode in ("dense", "hybrid"):
        t0 = time.perf_counter()
        emb = Embedder()
        hits: list[dict] = []
        name = None
        groups: dict[str | None, list[dict]] = {}
        for r in runs:
            groups.setdefault(r["query_prefix"], []).append(r)
        for prefix, members in groups.items():
            vec = (await emb.embed([query], "query", query_prefix=prefix))[0]
            name = vectorstore.collection_name(emb.model, len(vec))
            # Runs indexed into another collection (another model or dimension) have no vectors here.
            ids = [r["run_id"] for r in members if r["collection"] in (None, name)]
            dense_runs |= set(ids)
            if ids and await asyncio.to_thread(vectorstore.client().collection_exists, name):
                hits += await asyncio.to_thread(vectorstore.search, name, vec, cand_n, None, None, ids)
        hits.sort(key=lambda h: h["score"], reverse=True)
        dense = {h["chunk_id"]: (i + 1, h["score"]) for i, h in enumerate(hits[:cand_n])}
        out |= {"model": emb.model, "collection": name, "dense_documents": len(dense_runs)}
        other = [display_name(r["filename"]) for r in runs if r["run_id"] not in dense_runs]
        if other:
            out["notes"].append(f"{len(other)} document(s) were embedded with another model and are searched by "
                                f"keywords only (run them again to re-embed): {', '.join(sorted(other)[:10])}")
        out["timings_ms"]["dense"] = _ms(t0)

    lexical: dict[str, tuple[int, float]] = {}
    if mode in ("lexical", "hybrid"):
        t0 = time.perf_counter()
        key = "all:" + hashlib.sha1(",".join(sorted(by_run)).encode()).hexdigest()
        cached = lexical_cached(key)
        if cached is None:
            with session() as s:
                rows = s.execute(select(Chunk.id, Chunk.text).where(Chunk.run_id.in_(list(by_run))).order_by(Chunk.id)).all()
            cached = await asyncio.to_thread(index_for, key, [(cid, text) for cid, text in rows])
        idx, ids = cached
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
    pool = candidates[: rerank_pool(top_k)] if rerank else candidates[:top_k]
    with session() as s:
        chunks = {c.id: c for c in s.scalars(select(Chunk).where(Chunk.id.in_(pool)))}
    pool = [c for c in pool if c in chunks]

    reranker = Reranker()
    rerank_scores: dict[str, float] = {}
    if rerank and not reranker.enabled:
        out["notes"].append("rerank requested but models.yaml reranker.base_url is empty")
    elif rerank and pool:
        t0 = time.perf_counter()
        scores = await reranker.rerank(query, [chunks[c].text for c in pool])
        rerank_scores = dict(zip(pool, scores))
        pool = sorted(pool, key=lambda c: rerank_scores[c], reverse=True)
        out["reranker"] = reranker.model
        out["timings_ms"]["rerank"] = _ms(t0)

    for i, cid in enumerate(pool[:top_k]):
        c = chunks[cid]
        r = by_run[c.run_id]
        out["hits"].append({
            "rank": i + 1, "document_id": r["document_id"], "filename": display_name(r["filename"]),
            "run_id": c.run_id, "chunk_id": cid, "seq": c.seq, "text": c.text, "tokens": c.tokens,
            "pages": c.pages, "bboxes": c.bboxes, "section": c.section, "element_types": c.element_types,
            "scores": {
                "dense": dense.get(cid, (None, None))[1], "dense_rank": dense.get(cid, (None, None))[0],
                "lexical": lexical.get(cid, (None, None))[1], "lexical_rank": lexical.get(cid, (None, None))[0],
                "fused": final(cid) if mode == "hybrid" else None,
                "rerank": rerank_scores.get(cid),
            },
            "score": rerank_scores.get(cid, final(cid)),
        })
    return out
