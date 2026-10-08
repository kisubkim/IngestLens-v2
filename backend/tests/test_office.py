import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tools.chunking import split_table
from app.tools.toolpdf import engine

from .minipdf import write_pdf
from .office_fixtures import make_docx, make_pptx, make_xlsx
from .test_pipeline import _wait


def test_split_table_repeats_header():
    md = "차트: 생산량\n\n| a | b |\n|---|---|\n" + "\n".join(f"| {i} | {i * 2} |" for i in range(60))
    parts = split_table(md, 200)
    assert len(parts) > 1
    for p in parts:
        assert p.startswith("차트: 생산량\n\n| a | b |\n|---|---|\n") and len(p) <= 200
    assert sum(p.count("\n| ") for p in parts) - 1 * len(parts) == 60  # every data row kept once


def test_engine_native_rendering(tmp_path):
    """The engine renders Office files itself and returns their structure hints."""
    pdf = tmp_path / "o" / "p.native.pdf"
    res = engine().normalize(make_pptx(tmp_path / "p.pptx"), "p.pptx", "native", pdf)
    h = res["hints"]
    assert [s["page"] for s in h["slides"]] == [0, 1, 2]
    assert h["slides"][0]["notes"].startswith("발표자 노트")
    assert h["slides"][1]["charts"][0]["rows"][1] == ["1월", 120.0]
    assert res["page_count"] == 3 and pdf.exists()
    text = engine().text(pdf)
    assert "120" in text and "120.0" not in text

    pdf = tmp_path / "o" / "x.native.pdf"
    res = engine().normalize(make_xlsx(tmp_path / "x.xlsx", rows=130), "x.xlsx", "native", pdf)
    h = res["hints"]
    assert h["sheets"][0] == {"sheet": "측정값", "rows": 130, "cols": 4, "truncated": False}
    # every page is a whole block: one table whose first row is the header
    assert res["page_count"] == len(h["unit_pages"]) == 7  # ceil(130/24) + 1 summary sheet
    pcfg = {"tables": {"max_empty_cell_ratio": 0.5}, "figures": {"min_area_ratio": 0.04, "max_per_page": 4, "enrich_native_pages": False}}
    preps = engine().extract(pdf, [(p, "pymupdf_tables", 1) for p in range(7)], None, pcfg, False, {})
    heads = [next(e for e in preps[p]["elements"] if e["type"] == "table")["content"].splitlines()[0] for p in range(7)]
    assert all("일자" in h or "장비" in h for h in heads)


def _run(client, path, name):
    with path.open("rb") as f:
        doc = client.post("/api/documents", files={"file": (name, f, "application/octet-stream")}).json()
    run = _wait(client, client.post(f"/api/documents/{doc['id']}/runs").json()["id"])
    return run


def _decision(client, run_id, subject):
    return next(d for d in client.get(f"/api/runs/{run_id}/decisions").json() if d["subject"] == subject)


def _libreoffice(monkeypatch, path: str | None) -> None:
    """Whether the engine reports LibreOffice: intake decides native vs LibreOffice from /v1/health."""
    real = engine().health
    monkeypatch.setattr(engine(), "health", lambda timeout_s=3: {**real(), "libreoffice": path})


@pytest.fixture
def no_libreoffice(monkeypatch):
    _libreoffice(monkeypatch, None)


def test_docx_native(tmp_path, no_libreoffice):
    with TestClient(app) as client:
        run = _run(client, make_docx(tmp_path / "m.docx"), "manual.docx")
        assert run["status"] == "succeeded", run["error"]
        d = _decision(client, run["id"], "document format")
        assert d["rule_id"] == "office_native" and "LibreOffice is not installed" in d["choice"]
        assert _decision(client, run["id"], "chunking")["rule_id"] == "docx_headings"
        els = client.get(f"/api/runs/{run['id']}/elements").json()
        titles = [e["content"] for e in els if e["type"] == "title"]
        assert {"장비 운영 매뉴얼", "1. 개요", "2.1 준비물", "3. 점검 항목"} <= set(titles)
        assert any(e["type"] == "table" and "25±2" in e["content"] for e in els)
        sections = {c["section"] for c in client.get(f"/api/runs/{run['id']}/chunks").json()["items"]}
        assert {"1. 개요", "2. 설치 절차", "3. 점검 항목"} <= sections
        assert run["summary"]["office"] == {"kind": "docx", "renderer": "native", "headings": 5, "images": 1}


def test_pptx_native(tmp_path, no_libreoffice):
    with TestClient(app) as client:
        run = _run(client, make_pptx(tmp_path / "d.pptx"), "deck.pptx")
        assert run["status"] == "succeeded", run["error"]
        assert run["summary"]["plan"]["chunking"]["strategy"] == "page"
        assert run["summary"]["office"]["with_notes"] == 1
        els = client.get(f"/api/runs/{run['id']}/elements").json()
        notes = [e for e in els if e["source_tool"] == "pptx_notes"]
        assert len(notes) == 1 and notes[0]["page"] == 0
        assert any(e["page"] == 1 and e["type"] == "table" and "135" in e["content"] for e in els)  # chart data
        assert {e["content"] for e in els if e["type"] == "title"} >= {"프로젝트 개요", "월별 생산량", "점검 결과"}
        chunks = client.get(f"/api/runs/{run['id']}/chunks").json()["items"]
        assert all(len(c["pages"]) == 1 for c in chunks)  # page strategy: nothing spans slides


def test_xlsx_native_even_with_libreoffice(tmp_path, monkeypatch):
    _libreoffice(monkeypatch, "soffice")  # present, but xlsx stays native by config
    with TestClient(app) as client:
        run = _run(client, make_xlsx(tmp_path / "s.xlsx", rows=130), "sheet.xlsx")
        assert run["status"] == "succeeded", run["error"]
        assert "spreadsheets keep every table readable" in _decision(client, run["id"], "document format")["choice"]
        tables = client.get(f"/api/runs/{run['id']}/chunks", params={"type": "table"}).json()["items"]
        assert len(tables) >= 6
        assert all("일자" in c["text"] or "장비" in c["text"] for c in tables)  # header in every table chunk


def test_pptx_libreoffice_path_adds_chart_data(tmp_path, monkeypatch):
    """LibreOffice draws charts as vector art; the chart's own data comes from the pptx instead."""
    eng = engine()
    real = eng.normalize

    def fake_normalize(src, filename, method, out, hints=True, *args):
        assert method == "libreoffice"
        # Stand-in for LibreOffice on the engine: one page per slide and no chart table; hints come from the pptx.
        slide_hints = real(src, filename, "native", tmp_path / "hints.pdf")["hints"]
        out.parent.mkdir(parents=True, exist_ok=True)
        write_pdf(out, [{"size": (960, 540), "text": [(40, 60, 24, f"Slide {i + 1}")]} for i in range(3)])
        return {"hints": slide_hints if hints else {}, "encrypted": False, "page_count": 3, "pages": [[960, 540]] * 3}

    _libreoffice(monkeypatch, "soffice")
    monkeypatch.setattr(eng, "normalize", fake_normalize)
    with TestClient(app) as client:
        run = _run(client, make_pptx(tmp_path / "lo.pptx"), "lo.pptx")
        assert run["status"] == "succeeded", run["error"]
        assert _decision(client, run["id"], "document format")["rule_id"] == "office_convert"
        els = client.get(f"/api/runs/{run['id']}/elements", params={"page": 1}).json()
        chart = [e for e in els if e["source_tool"] == "pptx_chart_data"]
        assert len(chart) == 1 and "| 1월 | 120 |" in chart[0]["content"]
        assert run["summary"]["parse"]["office_hints"]["notes"] == 1


def test_legacy_doc_without_libreoffice_fails_clearly(tmp_path, no_libreoffice):
    p = tmp_path / "old.doc"
    p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600)  # OLE2 header
    with TestClient(app) as client:
        run = _run(client, p, "old.doc")
        assert run["status"] == "failed" and "needs LibreOffice" in run["error"]
