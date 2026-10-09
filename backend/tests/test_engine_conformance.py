"""Conformance: ToolPDF and the local engine answer the same requests with the same shapes, and agree on the
content that the pipeline's decisions depend on (page labels, tables, titles, figures, OCR pages, passwords).
ToolPDF's answer is the reference; layout details (exact bboxes, pixel sizes) may differ within tolerances."""

import io
from pathlib import Path

import pytest
from PIL import Image

from app.config import rules_cfg
from app.engines import EngineError, PasswordError
from app.tools.engine import local, toolpdf
from app.tools.pdf import classify

from .minipdf import write_pdf

FIGURES = {"min_area_ratio": 0.04, "max_per_page": 4, "on_all_pages": True}
MODES = ["text", "text", "text", "figures", "ocr", "text"]  # what the pipeline picks for sample.pdf's pages


@pytest.fixture(scope="module")
def engines():
    return {"toolpdf": toolpdf(), "local": local()}


@pytest.fixture(params=["toolpdf", "local"])
def eng(request, engines):
    return engines[request.param]


def _encrypted_pdf(path: Path, user: str = "secret") -> Path:
    from reportlab.lib.pdfencrypt import StandardEncryption
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), encrypt=StandardEncryption(user, ownerPassword="owner-" + user, strength=128))
    c.setFont("Helvetica", 14)
    c.drawString(72, 770, "Confidential quarterly report")
    c.showPage()
    c.drawString(72, 770, "Second page")
    c.showPage()
    c.save()
    return path


# ---------- shapes ----------

def test_health_and_options(eng):
    h = eng.health()
    assert {"version", "engine", "libreoffice"} <= set(h)
    schema = eng.options_schema()
    assert schema and {"info", "text", "profile", "extract", "render"} <= set(schema["endpoints"])
    caps = eng.capabilities()
    assert caps["password"] and {"lines", "text"} <= set(caps["table_strategies"])


def test_info(eng, sample_pdf):
    i = eng.info(sample_pdf)
    assert i["encrypted"] is False and i["page_count"] == 6
    assert all(abs(w - 595) < 1 and abs(h - 842) < 1 for w, h in i["pages"])


def test_profile_shape_and_labels(engines, sample_pdf):
    """Same feature keys, and the rules give every page the same label with either engine."""
    rules = rules_cfg()["profiler"]
    out = {name: e.profile(sample_pdf) for name, e in engines.items()}
    ref, got = out["toolpdf"], out["local"]
    assert [p["page"] for p in got] == [p["page"] for p in ref]
    for r, g in zip(ref, got):
        assert set(g["features"]) == set(r["features"])
        assert g["features"]["tables"] == r["features"]["tables"], g["page"]
        assert (g["features"]["drawings"] > 0) == (r["features"]["drawings"] > 0), g["page"]
        assert abs(g["features"]["text_chars"] - r["features"]["text_chars"]) <= max(20, 0.1 * r["features"]["text_chars"])
    assert [classify(p["features"], rules)["label"] for p in got] == [classify(p["features"], rules)["label"] for p in ref]


def _extract(e, pdf, crops=True):
    pages = [{"page": i, "mode": m, "drawings": 1} for i, m in enumerate(MODES)]
    return e.extract(pdf, pages, 14.0, FIGURES, {"image": {"crops": crops}})


def test_extract_agrees(engines, sample_pdf):
    out = {name: _extract(e, sample_pdf) for name, e in engines.items()}
    ref, got = out["toolpdf"], out["local"]
    assert set(got) == set(ref) == set(range(6))
    for p in range(6):
        r, g = ref[p], got[p]
        assert set(g) == set(r)
        titles = lambda x: [e["content"] for e in x["elements"] if e["type"] == "title"]  # noqa: E731
        assert titles(g) == titles(r), p
        assert [e["type"] for e in g["elements"] if e["type"] == "table"] == [e["type"] for e in r["elements"] if e["type"] == "table"], p
        assert sorted(c["kind"] for c in g["crops"]) == sorted(c["kind"] for c in r["crops"]), p
        assert len(g["regions"]) == len(r["regions"]), p
        for c in g["crops"]:
            assert isinstance(c["image"], bytes) and Image.open(io.BytesIO(c["image"])).format == "JPEG"
            if c["kind"] == "table":
                assert g["elements"][c["target"]]["type"] == "table"
    # the table's cells
    cells = lambda x: {c.strip() for e in x[2]["elements"] if e["type"] == "table" for c in e["content"].split("|")} - {"", "---"}  # noqa: E731
    assert cells(got) == cells(ref)


def test_extract_without_crops_reports_regions(eng, sample_pdf):
    out = _extract(eng, sample_pdf, crops=False)
    assert out[3]["regions"] and out[3]["skipped_regions"] == len(out[3]["regions"])
    assert all(c["kind"] == "ocr" for p in out.values() for c in p["crops"]) or not any(p["crops"] for p in out.values())


def test_render(eng, sample_pdf):
    png = Image.open(io.BytesIO(eng.render(sample_pdf, 0, 72)))
    assert png.format == "PNG" and abs(png.width - 595) <= 2 and abs(png.height - 842) <= 2
    clip = Image.open(io.BytesIO(eng.render(sample_pdf, 2, 144, "jpeg", clip=[100, 100, 200, 150], pad=0,
                                            highlight=[[110, 110, 150, 140]], options={"image": {"colorspace": "gray"}})))
    assert clip.format == "JPEG" and clip.mode == "L" and abs(clip.width - 200) <= 3 and abs(clip.height - 100) <= 3
    with pytest.raises(IndexError):
        eng.render(sample_pdf, 99, 72)


def test_text(eng, sample_pdf):
    t = eng.text(sample_pdf, 300)
    assert "Introduction" in t and len(t) <= 300


def test_unknown_option_is_refused(eng, sample_pdf):
    with pytest.raises(EngineError):
        eng.profile(sample_pdf, [0], {"tables": {"no_such_option": 1}})
    with pytest.raises(EngineError):
        eng.profile(sample_pdf, [0], {"tables": {"snap_tolerance": 500}})


def test_borderless_table_by_text_strategy(eng, tmp_path):
    rows = [("Region", "Q1", "Q2", "Q3"), ("North", "120", "135", "150"), ("South", "98", "101", "117"),
            ("East", "143", "160", "171"), ("West", "88", "92", "95")]
    text = [(72 + c * 110, 120 + r * 22, 11, cell) for r, row in enumerate(rows) for c, cell in enumerate(row)]
    pdf = write_pdf(tmp_path / "borderless.pdf", [{"size": (595, 842), "text": text}])
    assert eng.profile(pdf, [0], {"tables": {"strategy": "lines"}})[0]["features"]["tables"] == 0
    assert eng.profile(pdf, [0], {"tables": {"strategy": "text"}})[0]["features"]["tables"] >= 1
    els = eng.extract(pdf, [{"page": 0, "mode": "text", "drawings": 0}], None, FIGURES, {"tables": {"strategy": "text"}})[0]["elements"]
    table = next(e for e in els if e["type"] == "table")
    assert "North" in table["content"] and "171" in table["content"]


# ---------- encrypted PDFs ----------

def test_encrypted_pdf(eng, tmp_path):
    pdf = _encrypted_pdf(tmp_path / "locked.pdf")
    assert eng.info(pdf) == {"encrypted": True, "page_count": None, "pages": []}
    ok = {"document": {"password": "secret"}}
    i = eng.info(pdf, ok)
    assert i["encrypted"] is True and i["page_count"] == 2
    assert "Confidential" in eng.text(pdf, 500, ok)
    assert len(eng.profile(pdf, None, ok)) == 2
    assert eng.extract(pdf, [{"page": 0, "mode": "text", "drawings": 0}], None, FIGURES, ok)[0]["elements"]
    assert Image.open(io.BytesIO(eng.render(pdf, 1, 72, options=ok))).format == "PNG"
    for bad in (None, {"document": {"password": "wrong"}}):
        with pytest.raises(PasswordError):
            eng.text(pdf, 100, bad)
        with pytest.raises(PasswordError):
            eng.render(pdf, 0, 72, options=bad)
    with pytest.raises(PasswordError):
        eng.info(pdf, {"document": {"password": "wrong"}})


# ---------- normalize ----------

def test_image_to_pdf(eng, tmp_path):
    img = tmp_path / "scan.png"
    Image.new("RGB", (800, 600), "white").save(img, dpi=(96, 96))
    out = eng.normalize(img, "scan.png", "image", tmp_path / f"scan-{eng.name}.pdf")
    assert out["page_count"] == 1 and not out["encrypted"]
    w, h = out["pages"][0]
    assert abs(w - 600) < 2 and abs(h - 450) < 2


def test_native_office_hints_agree(engines, tmp_path):
    from .office_fixtures import make_pptx, make_xlsx

    pptx, xlsx = make_pptx(tmp_path / "p.pptx"), make_xlsx(tmp_path / "x.xlsx", rows=60)
    res = {n: e.normalize(pptx, "p.pptx", "native", tmp_path / f"p-{n}.pdf") for n, e in engines.items()}
    strip = lambda h: [{k: s[k] for k in ("slide", "title", "notes", "charts", "page")} for s in h["slides"]]  # noqa: E731
    assert strip(res["local"]["hints"]) == strip(res["toolpdf"]["hints"])
    assert res["local"]["page_count"] == res["toolpdf"]["page_count"]
    res = {n: e.normalize(xlsx, "x.xlsx", "native", tmp_path / f"x-{n}.pdf", xlsx_rows_per_page=24) for n, e in engines.items()}
    assert res["local"]["hints"]["sheets"] == res["toolpdf"]["hints"]["sheets"]
    assert res["local"]["hints"]["unit_pages"] == res["toolpdf"]["hints"]["unit_pages"]
