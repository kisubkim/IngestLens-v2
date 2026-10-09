"""Agent rules screen API: values are checked, stored as an override of only the changed keys, applied at once,
and reset; changing them needs admin rights like the storage settings."""

import copy
import json
import time

import yaml
from fastapi.testclient import TestClient

from app.config import rules_base, rules_cfg, rules_override_path
from app.main import app
from app.tools import rules_schema

LOCAL = ("127.0.0.1", 50000)


def _reset(client: TestClient) -> None:
    assert client.delete("/api/rules").status_code == 200


def test_shipped_rules_pass_their_own_checks():
    assert rules_schema.validate(rules_base()) == []


def test_every_field_belongs_to_an_agent_and_exists_in_the_shipped_rules():
    agents = {a["key"] for a in rules_schema.AGENTS}
    for f in rules_schema.FIELDS:
        assert f["agent"] in agents
        assert rules_schema.get(rules_base(), f["path"], rules_schema.MISSING) is not rules_schema.MISSING, f["path"]


def test_change_applies_at_once_and_stores_only_the_change():
    with TestClient(app, client=LOCAL) as client:
        _reset(client)
        state = client.get("/api/rules").json()
        assert state["overridden"] is False and state["changed"] == []
        new = copy.deepcopy(state["rules"])
        new["strategy"]["min_tokens"] = 64
        new["profiler"]["rules"][0]["when"]["max_text_chars"] = 80
        res = client.put("/api/rules", json={"rules": new})
        assert res.status_code == 200, res.text
        after = res.json()
        assert after["overridden"] and after["rules_version"] != state["rules_version"]
        assert ["strategy", "min_tokens"] in after["changed"] and ["profiler", "rules"] in after["changed"]
        # Applied without a restart: the agents read rules_cfg().
        assert rules_cfg()["strategy"]["min_tokens"] == 64
        stored = yaml.safe_load(rules_override_path().read_text(encoding="utf-8"))
        assert stored["strategy"] == {"min_tokens": 64} and set(stored) == {"strategy", "profiler"}
        assert stored["profiler"]["rules"][0]["when"]["max_text_chars"] == 80  # the rule list is stored whole
        _reset(client)
        assert not rules_override_path().exists() and rules_cfg()["strategy"]["min_tokens"] == 128


def test_bad_values_are_refused_and_nothing_changes():
    with TestClient(app, client=LOCAL) as client:
        _reset(client)
        rules = client.get("/api/rules").json()["rules"]
        cases = []
        r = copy.deepcopy(rules); r["strategy"]["overlap_tokens"] = 300; cases.append((r, "겹침"))  # > target/4
        r = copy.deepcopy(rules); r["parse"]["captions"]["pattern"] = "(["; cases.append((r, "정규식"))
        r = copy.deepcopy(rules); r["profiler"]["rules"][0]["when"] = {"min_colour": 1}; cases.append((r, "조건"))
        r = copy.deepcopy(rules); r["strategy"]["parsers"]["scanned"] = "magic"; cases.append((r, "파서"))
        r = copy.deepcopy(rules); r["office"]["unknown"] = 1; cases.append((r, "바꿀 수 없는"))
        r = copy.deepcopy(rules); r["parse"]["window_pages"] = 2.5; cases.append((r, "정수"))
        for bad, word in cases:
            res = client.put("/api/rules", json={"rules": bad})
            assert res.status_code == 400 and any(word in e for e in res.json()["detail"]["errors"]), (word, res.text)
        assert not rules_override_path().exists()


def test_broken_text_is_refused():
    """Korean decoded with the wrong code page arrives as lone surrogates; storing it broke reading the rules."""
    with TestClient(app, client=LOCAL) as client:
        _reset(client)
        rules = client.get("/api/rules").json()["rules"]
        rules["parse"]["captions"]["pattern"] = "^(\udce3\udc80|Figure)"
        res = client.put("/api/rules", content=json.dumps({"rules": rules}, ensure_ascii=True),
                         headers={"Content-Type": "application/json"})
        assert res.status_code == 400 and "깨진 글자" in res.json()["detail"]["errors"][0]
        assert not rules_override_path().exists()


def test_unusable_override_file_falls_back_to_the_shipped_rules():
    """A hand-edited or damaged override must not stop document processing."""
    with TestClient(app, client=LOCAL) as client:
        _reset(client)
        rules_override_path().write_text("strategy:\n  target_tokens: -5\n", encoding="utf-8")
        state = client.get("/api/rules").json()
        assert state["override_error"] and state["rules"]["strategy"]["target_tokens"] == 512
        assert rules_cfg()["strategy"]["target_tokens"] == 512
        rules_override_path().write_text("strategy: [unclosed\n", encoding="utf-8")
        state = client.get("/api/rules").json()
        assert state["override_error"] and state["overridden"]
        _reset(client)
        assert client.get("/api/rules").json()["override_error"] == ""


def test_changing_rules_needs_admin():
    with TestClient(app) as remote:  # not a loopback address and no RAG_API_KEY
        rules = remote.get("/api/rules").json()
        assert rules["editable_here"] is False
        assert remote.put("/api/rules", json={"rules": rules["rules"]}).status_code == 403
        assert remote.delete("/api/rules").status_code == 403


def test_next_run_uses_the_changed_rules(sample_pdf):
    with TestClient(app, client=LOCAL) as client:
        _reset(client)
        rules = client.get("/api/rules").json()["rules"]
        rules["strategy"]["min_tokens"] = 0
        version = client.put("/api/rules", json={"rules": rules}).json()["rules_version"]
        try:
            with sample_pdf.open("rb") as f:
                doc = client.post("/api/documents", files={"file": ("sample.pdf", f, "application/pdf")}).json()
            run = client.post(f"/api/documents/{doc['id']}/runs").json()
            deadline = time.time() + 60
            while (run := client.get(f"/api/runs/{run['id']}").json())["status"] not in ("succeeded", "failed") and time.time() < deadline:
                time.sleep(0.2)
            assert run["status"] == "succeeded", run["error"]
            plan = run["summary"]["plan"]
            assert plan["chunking"]["min_tokens"] == 0 and plan["rules_version"] == version
            decisions = client.get(f"/api/runs/{run['id']}/decisions").json()
            assert not any(d["rule_id"] == "chunk_merge" for d in decisions)
            chunking = next(d for d in decisions if d["subject"] == "chunking")
            assert chunking["inputs"]["rules_version"] == version and chunking["inputs"]["rules_changed_on_screen"] is True
        finally:
            _reset(client)
