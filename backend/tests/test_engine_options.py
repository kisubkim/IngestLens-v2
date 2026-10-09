"""PDF engine options (ToolPDF >= 0.2.0): the rules' engine.* reach profiling and extraction, change what the
engine finds (a table without ruling lines), and an engine without option support still gets the old request."""

import copy
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import rules_cfg
from app.main import app
from app.tools.toolpdf import engine

from .minipdf import write_pdf

LOCAL = ("127.0.0.1", 50000)


def _borderless_table_pdf(path: Path) -> Path:
    """A 4 x 5 grid of aligned words and numbers with no ruling lines, under a heading."""
    text = [(72, 72, 14, "Quarterly results")]
    rows = [("Region", "Q1", "Q2", "Q3"), ("North", "120", "135", "150"), ("South", "98", "101", "117"),
            ("East", "143", "160", "171"), ("West", "88", "92", "95")]
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            text.append((72 + c * 110, 120 + r * 22, 11, cell))
    return write_pdf(path, [{"size": (595, 842), "text": text}])


def _tables(rules_tables: dict, pdf: Path) -> tuple[int, list[str]]:
    """Table count from profiling and element types from extraction with these table options in effect."""
    rules = copy.deepcopy(rules_cfg())
    rules["engine"]["tables"].update(rules_tables)
    with TestClient(app, client=LOCAL) as client:
        assert client.put("/api/rules", json={"rules": rules}).status_code == 200
        try:
            feats = engine().profile(pdf, [0])[0]["features"]
            prep = engine().extract(pdf, [(0, "pymupdf_tables", feats["drawings"])], None, rules_cfg()["parse"], False, {})[0]
        finally:
            client.delete("/api/rules")
    return feats["tables"], [e["type"] for e in prep["elements"]]


def test_engine_takes_options():
    support = engine().option_support()
    assert support and {"profile", "extract", "render"} <= set(support["endpoints"])


def test_text_strategy_finds_a_table_without_ruling_lines(tmp_path):
    pdf = _borderless_table_pdf(tmp_path / "borderless.pdf")
    n_lines, types_lines = _tables({"strategy": "lines"}, pdf)
    n_text, types_text = _tables({"strategy": "text"}, pdf)
    assert n_lines == 0 and "table" not in types_lines
    assert n_text >= 1 and "table" in types_text


def test_tables_can_be_switched_off(tmp_path):
    pdf = _borderless_table_pdf(tmp_path / "off.pdf")
    n, types = _tables({"strategy": "text", "enabled": False}, pdf)
    assert n == 0 and "table" not in types


def _run(client: TestClient, pdf: Path) -> dict:
    with pdf.open("rb") as f:
        doc = client.post("/api/documents", files={"file": (pdf.name, f, "application/pdf")}).json()
    run = client.post(f"/api/documents/{doc['id']}/runs").json()
    deadline = time.time() + 60
    while (run := client.get(f"/api/runs/{run['id']}").json())["status"] not in ("succeeded", "failed") and time.time() < deadline:
        time.sleep(0.2)
    return run


def test_run_records_the_engine_options(sample_pdf):
    with TestClient(app, client=LOCAL) as client:
        run = _run(client, sample_pdf)
        assert run["status"] == "succeeded", run["error"]
        d = next(x for x in client.get(f"/api/runs/{run['id']}/decisions").json() if x["subject"] == "PDF engine options")
        assert d["rule_id"] == "engine_options" and d["inputs"]["tables"]["strategy"] == "lines" and d["inputs"]["engine_version"]


def test_old_engine_gets_the_old_request(sample_pdf, monkeypatch):
    """An engine without /v1/options: no `options` field anywhere, the 0.1.x extract fields, and a fallback decision."""
    sent = []
    real_post = engine().http.post

    def spy(url, *a, **kw):
        sent.append((url, kw.get("json") or {}))
        return real_post(url, *a, **kw)

    monkeypatch.setattr(engine(), "option_support", lambda: None)
    monkeypatch.setattr(engine().http, "post", spy)
    with TestClient(app, client=LOCAL) as client:
        run = _run(client, sample_pdf)
    assert run["status"] == "succeeded", run["error"]
    assert not any("options" in body for _, body in sent)
    extract = next(body for url, body in sent if url == "/v1/extract")
    assert {"max_empty_cell_ratio", "crops", "image_format", "render_dpi", "crop_dpi"} <= set(extract)
    with TestClient(app, client=LOCAL) as client:
        d = next(x for x in client.get(f"/api/runs/{run['id']}/decisions").json() if x["subject"] == "PDF engine options")
    assert d["rule_id"] == "engine_options_unsupported"
