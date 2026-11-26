import uuid

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

from .test_pipeline import _wait


def _ingest(client, name: str, text: str) -> tuple[str, str]:
    doc = client.post("/api/documents", files={"file": (name, text.encode("utf-8"), "text/plain")}).json()
    run = _wait(client, client.post(f"/api/documents/{doc['id']}/runs").json()["id"])
    assert run["status"] == "succeeded", run["error"]
    return doc["id"], run["id"]


def test_search_all_documents(monkeypatch):
    tag = uuid.uuid4().hex[:8]  # the test data dir is shared with other tests; unique words find only these documents
    with TestClient(app) as client:
        a, _ = _ingest(client, f"{uuid.uuid4()}_pump_{tag}.txt",
                       f"펌프 점검 절차 {tag}\n냉각수 펌프는 매주 월요일에 압력 zeta{tag} 값을 기록한다.\n")
        b, run_b = _ingest(client, f"valve_{tag}.log", f"밸브 교체 기록 {tag}\n밸브 V-12 omega{tag} 교체 완료.\n")

        for mode in ("dense", "lexical", "hybrid"):
            res = client.post("/api/search/all", json={"query": f"omega{tag} 밸브 교체", "mode": mode, "top_k": 3}).json()
            assert res["hits"], (mode, res)
            top = res["hits"][0]
            assert top["document_id"] == b and top["filename"] == f"valve_{tag}.log", (mode, top)
            assert res["documents"] >= 2
        hybrid = client.post("/api/search/all", json={"query": f"zeta{tag}"}).json()
        top = hybrid["hits"][0]
        assert top["document_id"] == a and top["filename"] == f"pump_{tag}.txt"  # Open WebUI's uuid prefix removed
        assert top["scores"]["lexical_rank"] == 1 and top["scores"]["fused"] > 0

        # Only the given documents
        only_a = client.post("/api/search/all", json={"query": f"omega{tag}", "document_ids": [a], "top_k": 5}).json()
        assert only_a["documents"] == 1 and all(h["document_id"] == a for h in only_a["hits"])

        # A new run replaces the old one: hits come from the latest succeeded run only
        run_b2 = _wait(client, client.post(f"/api/documents/{b}/runs").json()["id"])
        res = client.post("/api/search/all", json={"query": f"omega{tag}", "mode": "lexical"}).json()
        assert res["hits"][0]["run_id"] == run_b2["id"] != run_b

        # Tool server for Open WebUI: its own OpenAPI with two operations, key required when set
        spec = client.get("/api/tools/search/openapi.json").json()
        ops = {op["operationId"] for path in spec["paths"].values() for op in path.values()}
        assert ops == {"search_documents", "list_documents"}
        monkeypatch.setattr(settings, "api_key", "secret")
        assert client.post("/api/tools/search/search", json={"query": "x"}).status_code == 401
        key = {"Authorization": "Bearer secret"}
        res = client.post("/api/tools/search/search", json={"query": f"zeta{tag} 압력", "top_k": 2}, headers=key).json()
        first = res["results"][0]
        assert first["document"] == f"pump_{tag}.txt" and first["pages"] == "1"
        assert first["page_image"].endswith(f"/api/chunks/{hybrid['hits'][0]['chunk_id']}/preview.png")
        res = client.post("/api/tools/search/search", headers=key,
                          json={"query": f"zeta{tag}", "documents": [f"VALVE_{tag}"]}).json()
        assert {r["document"] for r in res["results"]} == {f"valve_{tag}.log"}
        assert client.post("/api/tools/search/search", headers=key,
                           json={"query": "x", "documents": ["no-such-document-zz"]}).status_code == 404
        docs = client.post("/api/tools/search/documents", headers=key).json()
        names = {d["document"] for d in docs}
        assert {f"pump_{tag}.txt", f"valve_{tag}.log"} <= names
        assert all(d["chunks"] >= 1 for d in docs if d["document"].endswith(tag + ".txt"))


def test_eval_corpus_judge_and_dataset():
    """scripts/eval_corpus.py: whitespace-free answer match in the right file; the committed set is well formed."""
    import importlib.util

    from app.config import ROOT

    spec = importlib.util.spec_from_file_location("eval_corpus", ROOT / "scripts" / "eval_corpus.py")
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    q = {"files": ["a.pdf", "scan.pdf"], "answer": ["20,867 명"]}
    hits = [{"file": "b.pdf", "text": "20,867명"}, {"file": "scan.pdf", "text": "출생아\n20,867\n명"}]
    assert ev.judge(q, hits) == {"rank": 2, "doc_top1": False}
    assert ev.judge(q, [{"file": "a.pdf", "text": "다른 값"}]) == {"rank": None, "doc_top1": True}

    ds = ev.load_set(ev.DEFAULT_SET)
    assert all(p.exists() for p in ds["paths"])
    names = {p.name for p in ds["paths"]}
    ids = [q["id"] for q in ds["queries"]]
    assert len(ids) == len(set(ids)) >= 40
    assert all(set(q["files"]) <= names and q["answer"] and q["kind"] for q in ds["queries"])


def test_rerank_pool(monkeypatch):
    from app.agents import retriever

    for cfg, want in (({}, 15), ({"candidates": 40}, 40), ({"candidates": 2}, 5)):
        monkeypatch.setattr(retriever, "models_cfg", lambda cfg=cfg: {"reranker": cfg})
        assert retriever.rerank_pool(5) == want
