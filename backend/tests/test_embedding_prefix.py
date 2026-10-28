"""Query/document instructions for embedding models (EmbeddingGemma, e5): models.yaml embedding.query_prefix and
document_prefix ({title} = the chunk's section), the dimensions option, and searches using the prefix the run was
indexed with."""

import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.tools import embedding as embedding_mod

GEMMA = {"base_url": "http://fake-embed/v1", "api_key": "x", "model": "embeddinggemma-2", "dim": 8, "max_tokens": 8192,
         "batch_size": 32, "query_prefix": "task: search result | query: ", "document_prefix": "title: {title} | text: ",
         "dimensions": 8}


class FakeOpenAI:
    """Stands in for the embedding server: records what is sent, returns a fixed-size vector per input."""
    sent: list[dict] = []

    def __init__(self, **_):
        self.embeddings = SimpleNamespace(create=self._create)

    async def _create(self, model, input, **kw):
        FakeOpenAI.sent.append({"model": model, "input": list(input), **kw})
        data = [SimpleNamespace(index=i, embedding=[1.0] + [0.0] * 7) for i in range(len(input))]
        return SimpleNamespace(data=data)


def _patch(monkeypatch, cfg: dict):
    import app.config as config

    full = {**config.models_cfg(), "embedding": cfg}
    monkeypatch.setattr(embedding_mod, "models_cfg", lambda: full)
    monkeypatch.setattr(embedding_mod, "AsyncOpenAI", FakeOpenAI)
    for mod in ("app.agents.embedder", "app.agents.retriever"):
        monkeypatch.setattr(f"{mod}.models_cfg", lambda: full, raising=False)
    FakeOpenAI.sent = []


def test_prefixes_are_added(monkeypatch):
    import asyncio

    _patch(monkeypatch, GEMMA)
    e = embedding_mod.Embedder()
    asyncio.run(e.embed(["압력 기준", "본문"], "document", ["3. 점검 항목", None]))
    asyncio.run(e.embed(["압력이 높을 때"], "query"))
    asyncio.run(e.embed(["질문"], "query", query_prefix="query: "))
    docs, query, old = FakeOpenAI.sent
    assert docs["input"] == ["title: 3. 점검 항목 | text: 압력 기준", "title: none | text: 본문"]
    assert docs["dimensions"] == 8
    assert query["input"] == ["task: search result | query: 압력이 높을 때"]
    assert old["input"] == ["query: 질문"]  # the prefix a run was indexed with wins over models.yaml


def test_no_prefix_by_default(monkeypatch):
    import asyncio

    _patch(monkeypatch, {k: v for k, v in GEMMA.items() if k not in ("query_prefix", "document_prefix", "dimensions")})
    e = embedding_mod.Embedder()
    asyncio.run(e.embed(["본문"], "document", ["제목"]))
    asyncio.run(e.embed(["질문"], "query"))
    assert [s["input"] for s in FakeOpenAI.sent] == [["본문"], ["질문"]]
    assert "dimensions" not in FakeOpenAI.sent[0]


def test_run_records_prefixes_and_search_uses_them(sample_pdf, monkeypatch):
    _patch(monkeypatch, GEMMA)
    with TestClient(app) as client:
        with sample_pdf.open("rb") as f:
            doc = client.post("/api/documents", files={"file": ("sample.pdf", f, "application/pdf")}).json()
        run = client.post(f"/api/documents/{doc['id']}/runs").json()
        deadline = time.time() + 60
        while (run := client.get(f"/api/runs/{run['id']}").json())["status"] not in ("succeeded", "failed") and time.time() < deadline:
            time.sleep(0.2)
        assert run["status"] == "succeeded", run["error"]
        assert run["summary"]["embed"]["query_prefix"] == GEMMA["query_prefix"]
        d = next(x for x in client.get(f"/api/runs/{run['id']}/decisions").json() if x["subject"] == "embedding model")
        assert d["inputs"]["document_prefix"] == GEMMA["document_prefix"]
        sent_docs = [t for s in FakeOpenAI.sent for t in s["input"]]
        assert all(t.startswith("title: ") and " | text: " in t for t in sent_docs)

        # models.yaml changes later: searching this run still uses the prefix it was indexed with
        _patch(monkeypatch, {**GEMMA, "query_prefix": "changed: "})
        client.post("/api/search", json={"query": "검색 시험", "run_id": run["id"], "mode": "dense"})
        assert FakeOpenAI.sent[-1]["input"] == ["task: search result | query: 검색 시험"]
