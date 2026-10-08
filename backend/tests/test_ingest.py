from urllib.parse import quote

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

from .minipdf import one_line_pdf
from .test_pipeline import _wait


def test_ingest_queues_and_reuses(sample_pdf):
    with TestClient(app) as client:
        with sample_pdf.open("rb") as f:
            res = client.post("/api/ingest", files=[("files", ("sample.pdf", f, "application/pdf"))])
        assert res.status_code == 200, res.text
        [item] = res.json()
        assert item["run_created"] is True and item["run"]["status"] == "queued"
        assert _wait(client, item["run"]["id"])["status"] == "succeeded"

        # The same bytes again: same document, and its succeeded run is reused instead of re-running.
        with sample_pdf.open("rb") as f:
            [again] = client.post("/api/ingest", files=[("files", ("copy.pdf", f, "application/pdf"))]).json()
        assert again["document"]["duplicate"] is True
        assert again["run_created"] is False and again["run"]["id"] == item["run"]["id"]


def test_openwebui_loader_returns_chunks(sample_pdf):
    with TestClient(app) as client:
        res = client.put(
            "/api/openwebui/process",
            content=sample_pdf.read_bytes(),
            headers={"Content-Type": "application/pdf", "X-Filename": quote("보고서 샘플.pdf")},
        )
        assert res.status_code == 200, res.text
        docs = res.json()
        assert docs and all(d["page_content"] for d in docs)
        meta = docs[0]["metadata"]
        assert meta["source"] == "보고서 샘플.pdf"
        # 0-based like LangChain PDF loaders, because Open WebUI displays page + 1
        assert meta["page"] == int(meta["page_label"]) - 1 == int(meta["pages"].split(",")[0]) - 1
        assert docs[0]["metadata"]["page"] == 0
        assert all(isinstance(v, (str, int)) for d in docs for v in d["metadata"].values())
        run = client.get(f"/api/runs/{meta['run_id']}").json()
        assert run["status"] == "succeeded"


def test_openwebui_loader_extension_from_content_type(tmp_path):
    pdf = one_line_pdf(tmp_path / "noext.pdf", "file sent without an extension")
    with TestClient(app) as client:
        res = client.put(
            "/api/openwebui/process",
            content=pdf.read_bytes(),
            headers={"Content-Type": "application/pdf", "X-Filename": "report"},
        )
        assert res.status_code == 200, res.text
        assert res.json()[0]["metadata"]["source"] == "report.pdf"


def test_openwebui_loader_errors():
    with TestClient(app) as client:
        res = client.put("/api/openwebui/process", content=b"plain text", headers={"X-Filename": "note.xyz"})
        assert res.status_code == 502 and "Unsupported format" in res.json()["detail"]
        assert client.put("/api/openwebui/process", content=b"", headers={"X-Filename": "a.pdf"}).status_code == 400


def test_api_key(sample_pdf, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret")
    with TestClient(app) as client:
        body = sample_pdf.read_bytes()
        headers = {"Content-Type": "application/pdf", "X-Filename": "sample.pdf"}
        assert client.put("/api/openwebui/process", content=body, headers=headers).status_code == 401
        bad = {**headers, "Authorization": "Bearer nope"}
        assert client.put("/api/openwebui/process", content=body, headers=bad).status_code == 401
        assert client.post("/api/ingest", files=[("files", ("s.pdf", body, "application/pdf"))]).status_code == 401
        ok = {**headers, "Authorization": "Bearer secret"}
        assert client.put("/api/openwebui/process", content=body, headers=ok).status_code == 200
        # The UI endpoints stay open; the key guards only the ingest API.
        assert client.get("/api/documents").status_code == 200
