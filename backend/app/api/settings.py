"""Storage settings screen: where uploads, page images, the DB and vectors live, and changing it.

Changes are written to SETTINGS_FILE and apply on the next server start: the DB engine and the Qdrant client
are created once at startup. Environment variables and .env win over the file, so those keys are locked here.
"""

import asyncio
import os
from pathlib import Path

import yaml
from dotenv import dotenv_values
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.engine import make_url

from ..config import ROOT, SETTINGS_FILE, Settings, settings
from ..graph.pipeline import _tasks
from .auth import is_local, require_admin

router = APIRouter(prefix="/api/settings", tags=["settings"])

EDITABLE = {
    "data_dir": "데이터 폴더",
    "db_url": "DB 주소",
    "qdrant_url": "Qdrant 주소",
}


def _show(key: str, value) -> str:
    if key == "db_url" and value:
        try:
            return make_url(value).render_as_string(hide_password=True)
        except Exception:
            return "(invalid URL)"
    return str(value)


def _source(key: str, file_values: dict) -> str:
    env_name = f"RAG_{key.upper()}"
    if any(k.upper() == env_name for k in os.environ):
        return "env"
    dotenv = settings.model_config.get("env_file")
    if dotenv and Path(dotenv).exists() and any(k.upper() == env_name for k in dotenv_values(dotenv)):
        return "dotenv"
    if key in file_values:
        return "file"
    return "default"


def _read_file() -> dict:
    if not SETTINGS_FILE.exists():
        return {}
    return yaml.safe_load(SETTINGS_FILE.read_text(encoding="utf-8")) or {}


def _dir_bytes(path: Path) -> int | None:
    if not path.exists():
        return None
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.stat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def _usage() -> list[dict]:
    d = settings.data_dir
    items = [
        ("uploads", "올린 원본 파일", d / "uploads"),
        ("converted", "Office·이미지를 변환한 PDF", d / "converted"),
        ("pages", "페이지 이미지 캐시", d / "pages"),
    ]
    if not settings.db_url:
        items.append(("db", "SQLite DB", d / "rag.db"))
    if not settings.qdrant_url:
        items.append(("qdrant", "내장 Qdrant (임베딩 벡터)", d / "qdrant"))
    out = []
    for key, label, path in items:
        size = _dir_bytes(path)
        if key == "db" and size is not None:  # WAL mode keeps recent writes next to the DB file
            size += sum(_dir_bytes(path.with_name(path.name + s)) or 0 for s in ("-wal", "-shm"))
        out.append({"key": key, "label": label, "path": str(path), "bytes": size})
    return out


def _state(request: Request) -> dict:
    file_values = _read_file()
    configured = Settings()  # what the next start will use
    items = []
    for key, label in EDITABLE.items():
        source = _source(key, file_values)
        effective, upcoming = getattr(settings, key), getattr(configured, key)
        items.append({
            "key": key,
            "label": label,
            "effective": _show(key, effective),
            "configured": _show(key, upcoming),
            "source": source,
            "locked": source in ("env", "dotenv"),
            "hint": settings.data_dir_hint if key == "data_dir" else "",
            "pending": effective != upcoming,
        })
    host = request.client.host if request.client else ""
    return {
        "settings_file": str(SETTINGS_FILE),
        "items": items,
        "database": _show("db_url", settings.database_url),
        "vector_store": settings.qdrant_url or str(settings.data_dir / "qdrant"),
        "usage": _usage(),
        "restart_required": any(i["pending"] for i in items),
        "key_required": bool(settings.api_key),
        "editable_here": bool(settings.api_key) or is_local(host),
        "active_runs": len(_tasks),
    }


@router.get("/storage")
async def get_storage(request: Request) -> dict:
    return await asyncio.to_thread(_state, request)


class StorageUpdate(BaseModel):
    """Only the fields that are sent change. An empty string goes back to the default."""
    data_dir: str | None = None
    db_url: str | None = None
    qdrant_url: str | None = None


def _check_data_dir(value: str) -> str:
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = ROOT / p
    p = p.resolve()
    if p.exists() and not p.is_dir():
        raise HTTPException(400, f"not a folder: {p}")
    probe = p
    while not probe.exists():
        probe = probe.parent
    if not os.access(probe, os.W_OK):
        raise HTTPException(400, f"no write permission: {probe}")
    return str(p)


def _check_db_url(value: str) -> str:
    if "***" in value:
        raise HTTPException(400, "type the DB password again; the masked value cannot be saved")
    try:
        url = make_url(value)
    except Exception:
        raise HTTPException(400, "invalid DB URL, e.g. postgresql+psycopg://user:pass@host:5432/rag")
    if not url.drivername.startswith(("sqlite", "postgresql")):
        raise HTTPException(400, "only sqlite and postgresql are supported")
    return value


def _check_qdrant_url(value: str) -> str:
    if not value.startswith(("http://", "https://")):
        raise HTTPException(400, "Qdrant URL must start with http:// or https://")
    return value.rstrip("/")


CHECKS = {"data_dir": _check_data_dir, "db_url": _check_db_url, "qdrant_url": _check_qdrant_url}


@router.put("/storage", dependencies=[Depends(require_admin)])
async def put_storage(req: StorageUpdate, request: Request) -> dict:
    changes = req.model_dump(exclude_unset=True)
    file_values = _read_file()
    for key, value in changes.items():
        if _source(key, file_values) in ("env", "dotenv"):
            raise HTTPException(409, f"{key} is set by an environment variable or .env (RAG_{key.upper()}); change it there")
        value = (value or "").strip()
        if value:
            file_values[key] = CHECKS[key](value)
        else:
            file_values.pop(key, None)
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        "# Written by the IngestLens settings screen. Applies on the next server start.\n"
        + yaml.safe_dump(file_values, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )
    return await asyncio.to_thread(_state, request)
