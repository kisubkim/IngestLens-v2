"""Binary files (device logs): accepted, analysed into an overview that names the record layout, chunked."""

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.tools.binview import analyse, overview_text

from .binfixtures import HEADER, RECORD, device_log


def test_overview_finds_the_layout(tmp_path):
    info = analyse(device_log(tmp_path / "dev.bin", 3000))
    assert info["period"]["record_size"] == RECORD
    assert info["layout"]["header_size"] == HEADER
    kinds = {(f["offset"], f["type"], f["kind"]) for f in info["fields"]["findings"]}
    assert {(0, "u32", "timestamp"), (4, "f32", "float"), (8, "f32", "float"), (12, "u16", "counter")} <= kinds
    assert any(c["start"] == 16 and c["bytes"].startswith("aa 55 aa 55") for c in info["fields"]["constant"])
    assert any(s["text"] == "SENSOR-UNIT-07" and s["offset"] == 12 for s in info["strings"])
    text = overview_text("dev.bin", "abc123", info)
    assert "document_id: abc123" in text and "record size: 32" in text and "header size: 64" in text
    assert text.isascii() and len(text) < 40_000


def test_random_bytes_have_no_record_size(tmp_path):
    import os

    blob = tmp_path / "random.bin"
    blob.write_bytes(os.urandom(200_000))
    info = analyse(blob)
    assert info["period"]["record_size"] is None and info["entropy"] > 7.9


def _run(client: TestClient, path: Path) -> dict:
    with path.open("rb") as f:
        doc = client.post("/api/documents", files={"file": (path.name, f, "application/octet-stream")}).json()
    run = client.post(f"/api/documents/{doc['id']}/runs").json()
    deadline = time.time() + 60
    while (run := client.get(f"/api/runs/{run['id']}").json())["status"] not in ("succeeded", "failed") and time.time() < deadline:
        time.sleep(0.2)
    return {**run, "doc": doc}


def test_binary_upload_is_ingested_as_an_overview(tmp_path):
    with TestClient(app) as client:
        run = _run(client, device_log(tmp_path / "device.dat", 2000))
        assert run["status"] == "succeeded", run["error"]
        d = next(x for x in client.get(f"/api/runs/{run['id']}/decisions").json() if x["subject"] == "document format")
        assert d["rule_id"] == "binary_overview" and d["inputs"]["record_size"] == 32 and d["inputs"]["header_size"] == 64
        text = " ".join(c["text"] for c in client.get(f"/api/runs/{run['id']}/chunks").json()["items"])
        assert run["doc"]["id"] in text and "SENSOR-UNIT-07" in text


def test_openwebui_loader_returns_the_overview(tmp_path):
    body = device_log(tmp_path / "dev2.bin", 500).read_bytes()
    with TestClient(app) as client:
        res = client.put("/api/openwebui/process", content=body, headers={"X-Filename": "dev2.bin"})
    assert res.status_code == 200
    text = " ".join(d["page_content"] for d in res.json())
    assert "BINARY FILE OVERVIEW" in text and "document_id:" in text


def test_upload_size_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 0.01)  # about 10 KB
    big = tmp_path / "big.bin"
    big.write_bytes(bytes(20_000))
    with TestClient(app) as client, big.open("rb") as f:
        r = client.post("/api/documents", files={"file": ("big.bin", f, "application/octet-stream")})
    assert r.status_code == 413 and "RAG_MAX_UPLOAD_MB" in r.json()["detail"]
    assert not list((settings.data_dir / "uploads").glob("*/big.bin"))


# ---------- tools API (Open WebUI tool server) ----------

T = "/api/tools/binary"


def test_tools_api_end_to_end(tmp_path):
    from .binfixtures import SPEC, T0

    with TestClient(app) as client:
        run = _run(client, device_log(tmp_path / "plant_A.dat", 3000))
        doc_id = run["doc"]["id"]
        assert run["status"] == "succeeded", run["error"]

        listed = client.post(f"{T}/list").json()
        assert any(d["document_id"] == doc_id for d in listed)
        ov = client.post(f"{T}/overview", json={"document": "plant_A.dat"}).json()  # by file name
        assert ov["document_id"] == doc_id and "record size: 32" in ov["overview"]

        rb = client.post(f"{T}/read", json={"document": doc_id, "offset": 0, "length": 16}).json()
        assert rb["hex"].startswith("00000000  44 4c 4f 47")
        assert client.post(f"{T}/read", json={"document": doc_id, "offset": 10**9}).status_code == 416

        dec = client.post(f"{T}/decode", json={"document": doc_id, "spec": SPEC}).json()
        assert dec["ok"] and dec["records"] == 3000 and dec["header"]["device"] == "SENSOR-UNIT-07"
        wrong = client.post(f"{T}/decode", json={"document": doc_id, "spec": SPEC.replace("header: 64", "header: 60")}).json()
        assert not wrong["ok"] and wrong["warnings"]
        bad = client.post(f"{T}/decode", json={"document": doc_id, "spec": "record_size: 32\nfields: [{name: x, offset: 40, type: u8}]"})
        assert bad.status_code == 422 and "past record_size" in bad.json()["detail"]

        rec = client.post(f"{T}/records", json={"document": doc_id, "spec": SPEC, "start": 1532, "count": 1,
                                                "fields": ["time", "seq"]}).json()
        assert rec["records"][0]["seq"] == 1532 and rec["records"][0]["time"].startswith("2025-")

        ex = client.post(f"{T}/export", json={"document": doc_id, "spec": SPEC}).json()
        assert ex["records"] == 3000 and "/api/tools/binary/exports/" in ex["download_url"]
        assert ex["download_url"].endswith("save_as=plant_A.json")  # underscores in the name stay
        path = ex["download_url"].split("://", 1)[1].split("/", 1)[1]
        body = client.get("/" + path).json()
        assert len(body["records"]) == 3000 and body["records"][10]["seq"] == 10
        assert body["records"][0]["flags"] == {"value": 3, "alarm": True, "door": True}
        assert T0 == 1_760_000_000


def test_tools_api_needs_the_key(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret")
    with TestClient(app) as client:
        assert client.post(f"{T}/list").status_code == 401
        assert client.post(f"{T}/list", headers={"Authorization": "Bearer secret"}).status_code == 200
        assert client.get(f"{T}/openapi.json").status_code == 200  # the tool server reads it to list the tools
