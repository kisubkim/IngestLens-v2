import json

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.tools.vlm_checks import cer, hangul_ratio, score_page, table_columns


def by_id(checks):
    return {c["id"]: c for c in checks}


def test_cer_ignores_markdown_and_whitespace():
    assert cer("## 2. 비상 대응\n\n| 가스 | 누출 |", "2. 비상 대응 가스 누출") == 0
    assert cer("abc", "abd") == 1 / 3


def test_single_column_table_and_spaced_facts_fail():
    els = [{"type": "title", "content": "2. 비상 대응 절차", "meta": {}},
           {"type": "table", "content": "| 누출 가스가 N F 3 인 경우 |\n| --- |\n| 내선 4119 |", "meta": {}}]
    c = by_id(score_page({"facts": ["NF3", "4119"], "no_single_column_table": True, "title": "비상 대응"}, "scanned", els))
    assert c["facts"]["score"] == 0.5 and c["facts"]["value"] == {"missing": ["NF3"]}
    assert not c["no_1col_table"]["pass"]
    assert c["title"]["pass"]


def test_figure_checks_language_skips_table_values():
    content = "**그림 1. 불량 수**\n\n- 제목: 월별 불량 수\n| Month | Count |\n|---|---|\n| 1월 | 120 |"
    els = [{"type": "figure", "content": content, "meta": {"figure_type": "chart", "caption": "그림 1. 불량 수"}}]
    c = by_id(score_page({"figure_type": "chart", "figure_facts": ["120", "4월"], "language": "ko", "caption": "그림 1"}, "chart", els))
    assert c["figure_type"]["pass"] and c["caption"]["pass"]
    assert c["figure_facts"]["score"] == 0.5
    assert c["language"]["pass"]
    assert hangul_ratio("The chart shows values") == 0
    assert table_columns("| a | b | c |\n|---|---|---|\n| 1 | 2 | 3 |") == 3


def test_evals_api_lists_and_reads_results(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "evals_dir", tmp_path)
    (tmp_path / "vlm").mkdir()
    result = {"name": "m1", "notes": "", "created_at": "2026-10-04T00:00:00+00:00", "git_commit": "abc", "models": {"vlm": {"model": "m1"}},
              "prompts_sha": "p", "dataset_version": "d", "summary": {"score": 0.9}, "pages": [{"id": "x"}], "runs": []}
    (tmp_path / "vlm" / "20261004-000000_m1.json").write_text(json.dumps(result), encoding="utf-8")
    (tmp_path / "vlm" / "broken.json").write_text("{", encoding="utf-8")
    client = TestClient(app)

    listing = client.get("/api/evals/vlm").json()
    assert [i["file"] for i in listing["items"]] == ["20261004-000000_m1.json"]
    assert "pages" not in listing["items"][0]
    assert listing["errors"][0]["file"] == "broken.json"

    assert client.get("/api/evals/vlm/20261004-000000_m1.json").json()["pages"] == [{"id": "x"}]
    assert client.get("/api/evals/vlm/..%2Fsecret.json").status_code == 404
    assert client.get("/api/evals/vlm/missing.json").status_code == 404
