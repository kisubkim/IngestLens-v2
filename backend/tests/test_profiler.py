from app.config import rules_cfg
from app.tools.pdf import classify
from app.tools.engine import engine

from .minipdf import write_pdf


def test_page_labels(sample_pdf):
    rules = rules_cfg()["profiler"]
    labels = [classify(p["features"], rules) for p in engine().profile(sample_pdf)]
    assert [c["label"] for c in labels] == ["text", "text", "table", "diagram", "scanned", "text"]
    for c in labels:
        assert 0 < c["confidence"] <= 1
        assert c["rule_id"]


def test_classify_reports_evidence():
    f = {"text_chars": 10, "image_area_ratio": 0.9, "tables": 0, "table_area_ratio": 0, "drawings": 0}
    c = classify(f, rules_cfg()["profiler"])
    assert c["rule_id"] == "scanned"
    assert c["conditions"]["max_text_chars"] == {"threshold": 50, "actual": 10}


def test_small_table_page_is_table(tmp_path):
    """M6 regression: a page that is only a small table (13% of the page area) used to fall through to mixed."""
    lines = [(72, 100 + r * 30, 522, 100 + r * 30) for r in range(6)] + [(72 + c * 150, 100, 72 + c * 150, 250) for c in range(4)]
    text = [(72, 70, 18, "Utilization")] + [(78 + c * 150, 120 + r * 30, 10, f"r{r}c{c} value") for r in range(5) for c in range(3)]
    pdf = write_pdf(tmp_path / "small_table.pdf", [{"text": text, "lines": lines}])
    f = engine().profile(pdf)[0]["features"]
    assert f["table_area_ratio"] < 0.3 and f["table_text_share"] > 0.5
    assert classify(f, rules_cfg()["profiler"])["rule_id"] == "table_text_share"
