import importlib.util
from urllib.parse import quote

from fastapi.testclient import TestClient

from app.config import ROOT, settings
from app.tools.engine import engine
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
        # A file that claims to be a PDF but is not one fails in the engine and reaches Open WebUI as 502.
        res = client.put("/api/openwebui/process", content=b"not really a pdf", headers={"X-Filename": "broken.pdf"})
        assert res.status_code == 502
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


def test_openwebui_formats(monkeypatch):
    real = engine().health
    monkeypatch.setattr(settings, "openwebui_extra_extensions", " DLG, .rec ")
    with TestClient(app) as client:
        monkeypatch.setattr(engine(), "health", lambda timeout_s=3: {**real(), "libreoffice": None})
        res = client.get("/api/openwebui/formats").json()
        exts = set(res["extensions"])
        assert {"pdf", "png", "docx", "pptx", "xlsx", "txt", "log", "csv", "dat", "dlg", "rec"} <= exts
        assert not exts & {"doc", "hwp", "md", "html", "json", "zip", "epub"}  # left to Open WebUI's own loaders
        assert res["no_extension"] is True and res["libreoffice"] is False
        monkeypatch.setattr(engine(), "health", lambda timeout_s=3: {**real(), "libreoffice": "/usr/bin/soffice"})
        res = client.get("/api/openwebui/formats").json()
        assert {"doc", "ppt", "xls", "hwp"} <= set(res["extensions"]) and res["libreoffice"] is True
        monkeypatch.setattr(settings, "api_key", "secret")
        assert client.get("/api/openwebui/formats").status_code == 401
        assert client.get("/api/openwebui/formats", headers={"Authorization": "Bearer secret"}).status_code == 200


def test_openwebui_chunks_marked(tmp_path):
    pdf = one_line_pdf(tmp_path / "mark.pdf", "chunk marked for the patched Open WebUI")
    with TestClient(app) as client:
        res = client.put("/api/openwebui/process", content=pdf.read_bytes(), headers={"X-Filename": "mark.pdf"})
        assert res.status_code == 200, res.text
        assert all(d["metadata"]["loader"] == "ingestlens" for d in res.json())


def _route_module(monkeypatch, env=None):
    spec = importlib.util.spec_from_file_location("owui_patch", ROOT / "deploy" / "openwebui_patch.py")
    patch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patch)
    if env is None:
        monkeypatch.delenv("INGESTLENS_EXTENSIONS", raising=False)
    else:
        monkeypatch.setenv("INGESTLENS_EXTENSIONS", env)
    ns = {"__name__": "ingestlens_route"}
    exec(compile(patch.ROUTE_MODULE, "ingestlens_route.py", "exec"), ns)
    return ns


def test_openwebui_patch_route(monkeypatch):
    """The routing module the Open WebUI patch installs: asks GET {url}/formats, falls back to its own list."""
    ns = _route_module(monkeypatch)
    calls = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"extensions": ["pdf", "log"], "no_extension": False}

    monkeypatch.setattr(ns["requests"], "get", lambda url, **kw: calls.append((url, kw["headers"])) or Resp())
    handles = ns["ingestlens_handles"]
    assert handles("a.PDF", "http://il:8000/api/openwebui/", "k") is True
    assert handles("notes.md", "http://il:8000/api/openwebui/", "k") is False
    assert handles("README", "http://il:8000/api/openwebui/", "k") is False
    assert calls == [("http://il:8000/api/openwebui/formats", {"Authorization": "Bearer k"})]  # cached

    def down(url, **kw):
        raise OSError("refused")

    monkeypatch.setattr(ns["requests"], "get", down)
    assert handles("a.docx", "http://other/api/openwebui", "") is True  # built-in list while IngestLens is down
    assert handles("a.html", "http://other/api/openwebui", "") is False

    fixed = _route_module(monkeypatch, "pdf, .HWP, noext")["ingestlens_handles"]
    assert fixed("x.hwp", "u", "") and fixed("syslog", "u", "") and not fixed("x.txt", "u", "")

    doc = type("Doc", (), {"metadata": {"loader": "ingestlens"}})()
    assert ns["is_ingestlens_chunk"](doc) and not ns["is_ingestlens_chunk"](type("D", (), {"metadata": {}})())
