from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.config import SETTINGS_FILE, settings
from app.db import init_db, session
from app.main import app
from app.models import Document

LOCAL = ("127.0.0.1", 50000)


@pytest.fixture(autouse=True)
def _clean_settings_file():
    yield
    SETTINGS_FILE.unlink(missing_ok=True)


def _item(state: dict, key: str) -> dict:
    return next(i for i in state["items"] if i["key"] == key)


def test_storage_overview():
    with TestClient(app, client=LOCAL) as client:
        state = client.get("/api/settings/storage").json()
    assert [i["key"] for i in state["items"]] == ["data_dir", "db_url", "qdrant_url"]
    data_dir = _item(state, "data_dir")
    # conftest sets RAG_DATA_DIR, and the environment wins over the settings file.
    assert data_dir["source"] == "env" and data_dir["locked"] and not data_dir["pending"]
    assert data_dir["effective"] == str(settings.data_dir)
    assert {u["key"] for u in state["usage"]} == {"uploads", "converted", "pages", "db", "qdrant"}
    assert state["editable_here"] and not state["key_required"]


def test_update_writes_file_and_needs_restart(tmp_path, monkeypatch):
    with TestClient(app, client=LOCAL) as client:
        assert client.put("/api/settings/storage", json={"data_dir": str(tmp_path)}).status_code == 409

        monkeypatch.delenv("RAG_DATA_DIR")
        new_dir = tmp_path / "ingestlens-data"
        res = client.put("/api/settings/storage", json={"data_dir": str(new_dir)})
        assert res.status_code == 200, res.text
        item = _item(res.json(), "data_dir")
        assert item["source"] == "file" and item["configured"] == str(new_dir.resolve()) and item["pending"]
        assert res.json()["restart_required"]
        assert yaml.safe_load(SETTINGS_FILE.read_text(encoding="utf-8")) == {"data_dir": str(new_dir.resolve())}
        assert settings.data_dir != new_dir  # the running server keeps its storage until restart

        res = client.put("/api/settings/storage", json={"db_url": "postgresql+psycopg://rag:secret@db:5432/rag"})
        db = _item(res.json(), "db_url")
        assert "secret" not in db["configured"] and "***" in db["configured"]
        saved = yaml.safe_load(SETTINGS_FILE.read_text(encoding="utf-8"))
        assert saved["db_url"].endswith("secret@db:5432/rag") and "data_dir" in saved

        assert client.put("/api/settings/storage", json={"db_url": db["configured"]}).status_code == 400
        assert client.put("/api/settings/storage", json={"db_url": "mysql://x@y/z"}).status_code == 400
        assert client.put("/api/settings/storage", json={"qdrant_url": "qdrant:6333"}).status_code == 400
        assert client.put("/api/settings/storage", json={"data_dir": str(SETTINGS_FILE)}).status_code == 400

        res = client.put("/api/settings/storage", json={"data_dir": "", "db_url": ""})
        assert _item(res.json(), "data_dir")["source"] == "default"
        assert yaml.safe_load(SETTINGS_FILE.read_text(encoding="utf-8")) == {}


def test_update_needs_local_request_or_key(monkeypatch):
    with TestClient(app) as remote:  # TestClient's default client host is not a loopback address
        assert remote.put("/api/settings/storage", json={"qdrant_url": "http://q:6333"}).status_code == 403
        assert remote.get("/api/settings/storage").json()["editable_here"] is False

        monkeypatch.setattr(settings, "api_key", "k")
        assert remote.put("/api/settings/storage", json={"qdrant_url": "http://q:6333"}).status_code == 401
        res = remote.put("/api/settings/storage", json={"qdrant_url": "http://q:6333/"},
                         headers={"Authorization": "Bearer k"})
        assert res.status_code == 200 and _item(res.json(), "qdrant_url")["configured"] == "http://q:6333"


def test_admin_hosts_treat_docker_gateway_as_local(monkeypatch):
    """Behind Docker port publishing the host's browser arrives from the bridge gateway, not 127.0.0.1."""
    with TestClient(app, client=("172.18.0.1", 50000)) as gateway:
        assert gateway.get("/api/settings/storage").json()["editable_here"] is False
        monkeypatch.setattr(settings, "admin_hosts", "10.0.0.5, 172.16.0.0/12, not-an-ip")
        assert gateway.get("/api/settings/storage").json()["editable_here"] is True
        assert gateway.put("/api/settings/storage", json={"qdrant_url": ""}).status_code == 200
    with TestClient(app, client=("192.168.1.20", 50000)) as lan:
        assert lan.put("/api/settings/storage", json={"qdrant_url": ""}).status_code == 403


def test_locked_data_dir_shows_hint(monkeypatch):
    monkeypatch.setattr(settings, "data_dir_hint", "Docker 볼륨으로 정한다")
    with TestClient(app, client=LOCAL) as client:
        items = client.get("/api/settings/storage").json()["items"]
    assert _item({"items": items}, "data_dir")["hint"] == "Docker 볼륨으로 정한다"
    assert _item({"items": items}, "db_url")["hint"] == ""


def test_document_paths_are_relative(sample_pdf):
    with TestClient(app) as client:
        with sample_pdf.open("rb") as f:
            doc = client.post("/api/documents", files={"file": ("sample.pdf", f, "application/pdf")}).json()
        assert not Path(doc["path"]).is_absolute()
        assert settings.resolve(doc["path"]).exists()

        # Rows from older versions hold absolute paths; startup rewrites them relative to data_dir.
        with session() as s:
            s.get(Document, doc["id"]).path = str(settings.resolve(doc["path"]))
        init_db()
        with session() as s:
            assert s.get(Document, doc["id"]).path == doc["path"]
