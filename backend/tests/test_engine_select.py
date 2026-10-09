"""Engine selection (RAG_PDF_ENGINE), a whole run on the local engine, encrypted PDFs through the API, and the
rules that keep the engine package separable and the dependencies permissive."""

import ast
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tools import engine as engine_mod
from app.config import Settings
from app.tools.engine import AppEngine, local, toolpdf

from .test_engine_conformance import _encrypted_pdf
from .test_pipeline import _mock_vlm

BACKEND = Path(__file__).resolve().parents[1]
LOCAL = ("127.0.0.1", 50000)


def _wait(client: TestClient, run_id: str, timeout: float = 90) -> dict:
    deadline = time.time() + timeout
    while (run := client.get(f"/api/runs/{run_id}").json())["status"] not in ("succeeded", "failed") and time.time() < deadline:
        time.sleep(0.2)
    return run


def _upload(client: TestClient, pdf: Path, **form) -> dict:
    with pdf.open("rb") as f:
        r = client.post("/api/documents", files={"file": (pdf.name, f, "application/pdf")}, data=form)
    assert r.status_code == 200, r.text
    return r.json()


def _decision(client: TestClient, run_id: str, subject: str) -> dict:
    return next(d for d in client.get(f"/api/runs/{run_id}/decisions").json() if d["subject"] == subject)


# ---------- selection ----------

def test_auto_prefers_toolpdf_and_falls_back_to_local(monkeypatch):
    e = AppEngine("auto")
    assert e.select().name == "toolpdf" and "응답" in e.reason

    def down(timeout_s=3):
        raise ConnectionError("down")

    monkeypatch.setattr(toolpdf(), "health", down)
    e = AppEngine("auto")
    assert e.select().name == "local" and "응답 없음" in e.reason
    monkeypatch.undo()
    # Back on ToolPDF at the next run start once the probe interval has passed.
    assert e.select(recheck=True).name == "local"
    e._probed -= engine_mod.PROBE_S + 1
    assert e.select(recheck=True).name == "toolpdf"


def test_explicit_modes():
    assert AppEngine("local").select().name == "local"
    assert AppEngine("toolpdf").select().name == "toolpdf"
    with pytest.raises(ValueError):
        AppEngine("pymupdf")


def test_default_mode_is_auto():
    assert Settings.model_fields["pdf_engine"].default == "auto"


# ---------- a whole run on the local engine ----------

def test_end_to_end_on_the_local_engine(sample_pdf, monkeypatch, pinned):
    pinned(local())
    _mock_vlm(monkeypatch)
    with TestClient(app, client=LOCAL) as client:
        doc = _upload(client, sample_pdf)
        run = _wait(client, client.post(f"/api/documents/{doc['id']}/runs").json()["id"])
        assert run["status"] == "succeeded", run["error"]
        s = run["summary"]
        assert s["engine"]["engine"] == "local"
        assert s["profile"]["label_counts"] == {"text": 3, "table": 1, "diagram": 1, "scanned": 1}
        assert s["chunk"]["count"] > 0 and s["embed"]["count"] == s["chunk"]["count"]
        d = _decision(client, run["id"], "PDF engine")
        assert d["rule_id"] == "pdf_engine_configured" and d["inputs"]["engine"] == "local"
        assert _decision(client, run["id"], "PDF engine options")["rule_id"] == "engine_options"
        tables = [e for e in client.get(f"/api/runs/{run['id']}/elements", params={"page": 2}).json() if e["type"] == "table"]
        assert tables and "r0c0" in tables[0]["content"]
        assert client.get(f"/api/documents/{doc['id']}/pages/0.png").headers["content-type"] == "image/png"
        status = client.get("/api/status", params={"refresh": True}).json()
        item = next(i for i in status["items"] if i["key"] == "engine")
        assert item["label"] == "PDF 엔진 (내장)" and item["state"] == "ok"


def test_auto_run_records_the_choice(sample_pdf, pinned):
    pinned("auto")
    with TestClient(app, client=LOCAL) as client:
        doc = _upload(client, sample_pdf)
        run = _wait(client, client.post(f"/api/documents/{doc['id']}/runs").json()["id"])
        assert run["status"] == "succeeded", run["error"]
        d = _decision(client, run["id"], "PDF engine")
        assert d["rule_id"] == "pdf_engine_auto" and d["inputs"]["engine"] == "toolpdf" and d["alternatives"][0]["choice"] == "local"


# ---------- encrypted PDFs ----------

@pytest.mark.parametrize("which", ["toolpdf", "local"])
def test_encrypted_pdf_through_the_api(tmp_path, which, pinned):
    pinned(toolpdf() if which == "toolpdf" else local())
    pdf = _encrypted_pdf(tmp_path / f"locked-{which}.pdf", user=f"pw-{which}")
    with TestClient(app, client=LOCAL) as client:
        doc = _upload(client, pdf)
        assert doc["has_password"] is False and "password" not in doc
        run = _wait(client, client.post(f"/api/documents/{doc['id']}/runs").json()["id"])
        assert run["status"] == "failed" and "password protected" in run["error"]

        r = client.put(f"/api/documents/{doc['id']}/password", json={"password": "wrong"})
        assert r.status_code == 200 and r.json()["has_password"] and "password" not in r.json()
        run = _wait(client, client.post(f"/api/documents/{doc['id']}/runs").json()["id"])
        assert run["status"] == "failed" and "wrong PDF password" in run["error"]

        client.put(f"/api/documents/{doc['id']}/password", json={"password": f"pw-{which}"})
        run = _wait(client, client.post(f"/api/documents/{doc['id']}/runs").json()["id"])
        assert run["status"] == "succeeded", run["error"]
        assert _decision(client, run["id"], "encrypted PDF")["rule_id"] == "pdf_password"
        assert client.get(f"/api/documents/{doc['id']}/pages/1.png").status_code == 200
        chunks = client.get(f"/api/runs/{run['id']}/chunks").json()["items"]
        assert any("Confidential" in c["text"] for c in chunks)
        # The password appears nowhere in what the API returns about the run.
        for path in ("events", "decisions"):
            assert f"pw-{which}" not in client.get(f"/api/runs/{run['id']}/{path}").text
        assert f"pw-{which}" not in client.get("/api/documents").text


def test_password_at_upload(tmp_path):
    pdf = _encrypted_pdf(tmp_path / "locked-upload.pdf", user="at-upload")
    with TestClient(app, client=LOCAL) as client:
        doc = _upload(client, pdf, password="at-upload")
        assert doc["has_password"]
        run = _wait(client, client.post(f"/api/documents/{doc['id']}/runs").json()["id"])
        assert run["status"] == "succeeded", run["error"]


# ---------- package rules ----------

def test_engine_package_imports_nothing_else_from_the_app():
    """app/engines must stay separable: no imports of app.* outside the package."""
    for py in (BACKEND / "app" / "engines").rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert not (node.level == 0 and mod.startswith("app") and not mod.startswith("app.engines")), (py, mod)
                depth = len(py.relative_to(BACKEND / "app" / "engines").parts) - 1  # levels inside the package
                assert node.level <= depth + 1, (py, mod, "relative import leaves app.engines")
            elif isinstance(node, ast.Import):
                assert not any(a.name == "app" or a.name.startswith("app.") and not a.name.startswith("app.engines")
                               for a in node.names), py


# Libraries that must not be used: copyleft (or needing copyleft system libraries).
FORBIDDEN = {"pymupdf", "fitz", "pymupdfb", "ghostscript", "fpdf2", "img2pdf", "pdf2image", "camelot-py",
             "weasyprint", "pikepdf", "poppler", "python-poppler", "pyqt5", "pyqt6"}


def test_dependencies_stay_permissive():
    for req in BACKEND.glob("requirements*.txt"):
        for line in req.read_text(encoding="utf-8").splitlines():
            name = line.split("#")[0].strip().split("==")[0].split("[")[0].strip().lower()
            assert name not in FORBIDDEN, (req.name, name)
    for py in (BACKEND / "app").rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            assert not any(n.split(".")[0].lower() in {"pymupdf", "fitz", "pikepdf", "ghostscript"} for n in names), py
