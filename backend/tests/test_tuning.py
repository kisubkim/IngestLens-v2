import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

from .test_pipeline import _wait

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def test_token_calibration_changes_chunk_budget(sample_pdf, monkeypatch):
    import app.agents.strategy as strategy

    async def fake_count(text):
        return len(text) // 2  # 2.0 chars/token

    monkeypatch.setattr(strategy, "count_tokens", fake_count)
    with TestClient(app) as client:
        with sample_pdf.open("rb") as f:
            doc = client.post("/api/documents", files={"file": ("t.pdf", f, "application/pdf")}).json()
        run = _wait(client, client.post(f"/api/documents/{doc['id']}/runs").json()["id"])
        assert run["status"] == "succeeded", run["error"]
        assert abs(run["summary"]["plan"]["chunking"]["chars_per_token"] - 2.0) < 0.01
        d = next(d for d in client.get(f"/api/runs/{run['id']}/decisions").json() if d["subject"] == "token estimate")
        assert d["rule_id"] == "tokenizer_calibrated"


def test_token_calibration_default_without_endpoint(sample_pdf):
    with TestClient(app) as client:
        with sample_pdf.open("rb") as f:
            doc = client.post("/api/documents", files={"file": ("t.pdf", f, "application/pdf")}).json()
        run = _wait(client, client.post(f"/api/documents/{doc['id']}/runs").json()["id"])
        d = next(d for d in client.get(f"/api/runs/{run['id']}/decisions").json() if d["subject"] == "token estimate")
        assert d["rule_id"] == "tokenizer_default" and run["summary"]["plan"]["chunking"]["chars_per_token"] == 2.5


def test_eval_profile_sweep_finds_threshold(sample_pdf, tmp_path):
    sys.path.insert(0, str(SCRIPTS))
    import eval_profile

    rows = [{"doc": "s", "page": 1, "label": "table", "features": {"text_chars": 300, "image_area_ratio": 0, "tables": 1,
                                                                   "table_area_ratio": 0.2, "table_text_share": 0.3, "drawings": 10}}]
    rules = {"rules": [{"id": "t", "label": "table", "when": {"min_tables": 1, "min_table_area_ratio": 0.3}}],
             "default": {"id": "d", "label": "mixed"}}
    assert eval_profile.accuracy(rows, rules)[0] == 0
    best, changes = eval_profile.sweep(rows + [{**rows[0], "label": "mixed", "features": {**rows[0]["features"], "table_area_ratio": 0.1}}], rules)
    assert changes and changes[0]["condition"] == "min_table_area_ratio" and 0.1 < changes[0]["to"] <= 0.2


def test_eval_retrieval_relevance():
    sys.path.insert(0, str(SCRIPTS))
    import eval_retrieval

    hit = {"pages": [2], "text": "N2 순도 99.999%"}
    assert eval_retrieval.relevant(hit, {"pages": [3]})
    assert eval_retrieval.relevant(hit, {"text": "99.999%"})
    assert not eval_retrieval.relevant(hit, {"pages": [1], "text": "없음"})
