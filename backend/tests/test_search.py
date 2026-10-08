import math

from fastapi.testclient import TestClient

from app.main import app
from app.tools.lexical import BM25, tokenize

from .test_pipeline import _wait


def test_tokenize_korean_bigrams_and_words():
    assert tokenize("벡터 DB에 저장") == ["벡터", "db", "에", "저장"]
    assert tokenize("임베딩한") == ["임베", "베딩", "딩한"]


def test_bm25_ranks_matching_doc_first():
    idx = BM25(["표 데이터 r3c2 분기 실적", "텍스트 본문 설명", "다이어그램 구성"])
    scores = idx.scores("분기 실적 r3c2")
    assert scores[0] > 0 and scores[1] == scores[2] == 0


def _run(client, pdf) -> tuple[str, str]:
    with pdf.open("rb") as f:
        doc = client.post("/api/documents", files={"file": ("s.pdf", f, "application/pdf")}).json()
    run = _wait(client, client.post(f"/api/documents/{doc['id']}/runs").json()["id"])
    assert run["status"] == "succeeded", run["error"]
    return doc["id"], run["id"]


def test_search_modes_projection_neighbors(sample_pdf, monkeypatch):
    with TestClient(app) as client:
        doc_id, run_id = _run(client, sample_pdf)
        q = "Quarterly results r3c2"

        by_mode = {m: client.post("/api/search", json={"query": q, "run_id": run_id, "mode": m, "top_k": 3}).json() for m in ("dense", "lexical", "hybrid")}
        for m, res in by_mode.items():
            assert res["hits"], m
            assert 2 in res["hits"][0]["pages"], (m, res["hits"][0])
        top = by_mode["hybrid"]["hits"][0]["scores"]
        assert top["dense_rank"] and top["lexical_rank"] and top["fused"] > 0
        assert by_mode["lexical"]["hits"][0]["scores"]["dense"] is None
        assert by_mode["hybrid"]["hits"][0]["bboxes"]

        # rerank without a configured reranker is reported, not an error
        res = client.post("/api/search", json={"query": q, "run_id": run_id, "rerank": True}).json()
        assert any("reranker" in n for n in res["notes"]) and res["hits"]

        # document_id resolves to the latest succeeded run
        assert client.post("/api/search", json={"query": q, "document_id": doc_id}).json()["run_id"] == run_id

        emb = client.get(f"/api/runs/{run_id}/embeddings").json()
        n_chunks = client.get(f"/api/runs/{run_id}/chunks").json()["total"]
        assert emb["count"] == n_chunks and emb["dim"] == 1024
        assert all(math.isfinite(p["x"]) and math.isfinite(p["y"]) for p in emb["points"])
        assert 0 < emb["explained_variance"][0] <= 1

        cid = emb["points"][0]["chunk_id"]
        nb = client.get(f"/api/runs/{run_id}/chunks/{cid}/neighbors", params={"k": 3}).json()
        assert len(nb) == 3 and cid not in {n["chunk_id"] for n in nb}
        assert nb[0]["score"] >= nb[-1]["score"]

        page2 = client.get(f"/api/runs/{run_id}/chunks", params={"page": 2}).json()
        assert page2["total"] >= 1 and all(2 in c["pages"] for c in page2["items"])
        tables = client.get(f"/api/runs/{run_id}/chunks", params={"type": "table"}).json()
        assert tables["total"] == 1 and "r0c0" in tables["items"][0]["text"]
        assert client.get(f"/api/runs/{run_id}/chunks", params={"q": "quarterly"}).json()["total"] >= 1


def test_rerank_reorders(sample_pdf, monkeypatch):
    from app.tools import reranker

    def init(self):
        self.cfg, self.enabled, self.model = {}, True, "mock-rerank"

    async def rerank(self, query, documents):
        # Prefer the longest document, which is never what the fused order puts first here.
        return [float(len(d)) for d in documents]

    monkeypatch.setattr(reranker.Reranker, "__init__", init)
    monkeypatch.setattr(reranker.Reranker, "rerank", rerank)
    with TestClient(app) as client:
        _, run_id = _run(client, sample_pdf)
        res = client.post("/api/search", json={"query": "Quarterly results r3c2", "run_id": run_id, "rerank": True, "top_k": 3}).json()
        assert res["reranker"] == "mock-rerank"
        scores = [h["scores"]["rerank"] for h in res["hits"]]
        assert scores == sorted(scores, reverse=True) and all(s is not None for s in scores)
