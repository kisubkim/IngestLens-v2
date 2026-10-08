import asyncio

import httpx
from fastapi.testclient import TestClient

from app.api import status as status_api
from app.main import app


def _state(res: dict, key: str) -> str:
    return next(i["state"] for i in res["items"] if i["key"] == key)


def test_status_without_models_is_ok_with_models_off():
    with TestClient(app) as client:
        res = client.get("/api/status?refresh=true").json()
    assert res["overall"] == "ok"
    assert {_state(res, k) for k in ("api", "db", "vectors")} == {"ok"}
    assert {_state(res, k) for k in ("embedding", "vlm", "reranker")} == {"off"}
    assert res["runs"] == {"running": 0, "queued": 0}


def _probe(monkeypatch, handler, model="qwen2.5vl:7b"):
    monkeypatch.setattr(status_api, "models_cfg", lambda: {"vlm": {"base_url": "http://vlm:8000/v1", "model": model}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await status_api._check_model(client, "vlm")

    return asyncio.run(run())


def test_model_probe_states(monkeypatch):
    listing = {"data": [{"id": "qwen2.5vl:7b"}, {"id": "bge-m3:latest"}]}
    assert _probe(monkeypatch, lambda r: httpx.Response(200, json=listing))["state"] == "ok"
    assert _probe(monkeypatch, lambda r: httpx.Response(200, json=listing), model="bge-m3")["state"] == "ok"  # :latest

    missing = _probe(monkeypatch, lambda r: httpx.Response(200, json=listing), model="qwen2.5-vl-32b")
    assert missing["state"] == "warn" and "qwen2.5-vl-32b" in missing["detail"]

    assert _probe(monkeypatch, lambda r: httpx.Response(404))["state"] == "ok"  # up, no model listing
    assert _probe(monkeypatch, lambda r: httpx.Response(503))["state"] == "error"

    def refuse(r):
        raise httpx.ConnectError("refused")

    down = _probe(monkeypatch, refuse)
    assert down["state"] == "error" and "연결할 수 없습니다" in down["detail"]


def test_placeholder_url_is_an_error_not_a_crash(monkeypatch):
    """The deploy template ships with http://<VLM 서버 주소>:<포트>/v1 until someone fills it in."""
    monkeypatch.setattr(status_api, "models_cfg", lambda: {"vlm": {"base_url": "http://<VLM 서버 주소>:<포트>/v1", "model": "m"}})

    async def run():
        async with httpx.AsyncClient() as client:
            return await status_api._check_model(client, "vlm")

    item = asyncio.run(run())
    assert item["state"] == "error" and "올바르지 않습니다" in item["detail"]
