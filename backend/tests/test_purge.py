from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.tools import vectorstore

from .minipdf import one_line_pdf
from .test_pipeline import _wait

LOCAL = ("127.0.0.1", 50000)


def _ingest(client: TestClient, path, name: str) -> tuple[str, dict]:
    with path.open("rb") as f:
        doc = client.post("/api/documents", files={"file": (name, f, "application/pdf")}).json()
    run = _wait(client, client.post(f"/api/documents/{doc['id']}/runs").json()["id"])
    assert run["status"] == "succeeded", run["error"]
    return doc["id"], run


def _points(doc_id: str) -> int:
    c = vectorstore.client()
    return sum(c.count(col.name, count_filter=vectorstore._match(doc_id=doc_id)).count
               for col in c.get_collections().collections if col.name.startswith("chunks__"))


def _other_pdf(tmp_path):
    return one_line_pdf(tmp_path / "other.pdf", "Another document", size=20)


def test_overview_counts_documents_vectors_and_storage(sample_pdf, tmp_path):
    with TestClient(app, client=LOCAL) as client:
        client.delete("/api/documents?confirm=all")
        empty = client.get("/api/overview").json()
        assert empty["documents"]["count"] == 0 and empty["vectors"]["total"] == 0 and empty["recent"] == []

        doc_id, run = _ingest(client, sample_pdf, "sample.pdf")
        _ingest(client, _other_pdf(tmp_path), "other.pdf")
        _wait(client, client.post(f"/api/documents/{doc_id}/runs").json()["id"])  # re-run: only the latest run counts
        o = client.get("/api/overview").json()
    assert o["documents"]["count"] == 2 and o["documents"]["pages"] == 7 and o["documents"]["by_format"] == {"pdf": 2}
    assert o["runs"]["total"] == 3 and o["runs"]["by_status"] == {"succeeded": 3}
    assert o["chunks"] == o["vectors"]["total"] > 0
    assert o["vectors"]["embedding_model"] == "dev-hash" and not o["vectors"]["embedding_configured"]
    assert {c["dim"] for c in o["vectors"]["collections"]} == {1024}
    assert o["storage"]["bytes"] == sum(i["bytes"] or 0 for i in o["storage"]["items"]) > 0
    assert [d["filename"] for d in o["recent"]] == ["other.pdf", "sample.pdf"] and o["recent"][1]["chunks"] > 0


def test_element_stats_per_page(sample_pdf):
    with TestClient(app) as client:
        _, run = _ingest(client, sample_pdf, "sample.pdf")
        stats = client.get(f"/api/runs/{run['id']}/element-stats").json()
        elements = client.get(f"/api/runs/{run['id']}/elements").json()
    assert [p["page"] for p in stats["pages"]] == list(range(6))
    assert stats["total"] == len(elements) == sum(p["total"] for p in stats["pages"])
    assert stats["by_type"]["table"] >= 1
    table_page = next(p for p in stats["pages"] if p["label"] == "table")
    assert table_page["by_type"].get("table") and table_page["parser"]
    assert all(set(p["by_tool"]) for p in stats["pages"] if p["total"])


def test_delete_document_removes_rows_vectors_and_files(sample_pdf, tmp_path):
    with TestClient(app, client=LOCAL) as client:
        doc_id, run = _ingest(client, sample_pdf, "sample.pdf")
        other_id, _ = _ingest(client, _other_pdf(tmp_path), "other.pdf")
        client.get(f"/api/documents/{doc_id}/pages/0.png")  # fill the page image cache
        assert _points(doc_id) > 0
        for d in ("uploads", "converted", "pages"):
            assert (settings.data_dir / d / doc_id).exists() or d == "converted"  # PDFs are not converted

        res = client.delete(f"/api/documents/{doc_id}")
        assert res.status_code == 200, res.text
        assert res.json()["documents"] == 1 and res.json()["chunks"] > 0

        assert client.get(f"/api/documents/{doc_id}").status_code == 404
        assert client.get(f"/api/runs/{run['id']}").status_code == 404
        assert _points(doc_id) == 0
        assert not any((settings.data_dir / d / doc_id).exists() for d in ("uploads", "converted", "pages"))
        assert _points(other_id) > 0  # other documents are untouched
        assert client.delete(f"/api/documents/{doc_id}").status_code == 404


def test_delete_needs_local_request_and_idle_document(sample_pdf, monkeypatch):
    with TestClient(app, client=LOCAL) as client:
        doc_id, _ = _ingest(client, sample_pdf, "sample.pdf")
        monkeypatch.setattr("app.api.documents.active_runs", lambda ids=None: ["r1"])
        assert client.delete(f"/api/documents/{doc_id}").status_code == 409
        assert client.delete("/api/documents?confirm=all").status_code == 409
    with TestClient(app) as remote:  # not a loopback client
        assert remote.delete(f"/api/documents/{doc_id}").status_code == 403


def test_delete_all_needs_confirm_and_clears_everything(sample_pdf, tmp_path):
    with TestClient(app, client=LOCAL) as client:
        _ingest(client, sample_pdf, "sample.pdf")
        _ingest(client, _other_pdf(tmp_path), "other.pdf")
        assert client.delete("/api/documents").status_code == 400
        res = client.delete("/api/documents?confirm=all")
        assert res.status_code == 200 and res.json()["documents"] >= 2
        assert client.get("/api/documents").json() == []
        assert not [c for c in vectorstore.client().get_collections().collections if c.name.startswith("chunks__")]
        assert not any((settings.data_dir / "uploads").iterdir())
        # still usable afterwards
        doc_id, _ = _ingest(client, sample_pdf, "sample.pdf")
        assert _points(doc_id) > 0
