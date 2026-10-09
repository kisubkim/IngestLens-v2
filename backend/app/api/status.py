"""Backend status for the UI's status indicator: is each part (DB, vector store, model servers) usable right now."""

import asyncio
import os
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter
from sqlalchemy import func, select, text

from ..config import models_cfg, settings
from ..db import session
from ..models import Run
from ..tools import vectorstore
from ..tools.engine import engine, local, toolpdf

router = APIRouter(prefix="/api", tags=["status"])

TIMEOUT_S = 3.0
CACHE_S = 5.0  # several open tabs poll this; model servers are asked at most this often
_cache: dict = {"at": 0.0, "value": None}

MODEL_LABELS = {"embedding": "임베딩 모델", "vlm": "VLM (OCR·그림 설명)", "reranker": "Reranker"}
# What the pipeline does without the model, shown when base_url is empty.
MODEL_OFF = {
    "embedding": "설정 없음: 테스트용 dev-hash 임베딩으로 대신합니다(검색 품질 낮음)",
    "vlm": "설정 없음: 스캔·그림 페이지를 PDF 텍스트로만 처리합니다",
    "reranker": "설정 없음: 검색에서 rerank를 쓸 수 없습니다",
}


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _item(key: str, label: str, state: str, detail: str, ms: int | None = None) -> dict:
    """state: ok, warn (works but degraded), off (not configured), error (configured but failing)."""
    return {"key": key, "label": label, "state": state, "detail": detail, "latency_ms": ms}


def _check_db() -> dict:
    t0 = time.perf_counter()
    kind = "SQLite" if settings.database_url.startswith("sqlite") else settings.database_url.split(":", 1)[0]
    try:
        with session() as s:
            s.execute(text("select 1"))
        return _item("db", "DB", "ok", f"{kind} 연결됨", _ms(t0))
    except Exception as e:
        return _item("db", "DB", "error", f"{kind} 연결 실패: {type(e).__name__}: {e}"[:300], _ms(t0))


def _check_vectors() -> dict:
    t0 = time.perf_counter()
    where = settings.qdrant_url or "내장 Qdrant"
    try:
        n = len(vectorstore.client().get_collections().collections)
        return _item("vectors", "벡터 DB (Qdrant)", "ok", f"{where}, 컬렉션 {n}개", _ms(t0))
    except Exception as e:
        return _item("vectors", "벡터 DB (Qdrant)", "error", f"{where} 연결 실패: {type(e).__name__}: {e}"[:300], _ms(t0))


def _model_ids(body) -> set[str]:
    ids = {m.get("id", "") for m in (body.get("data") or []) if isinstance(m, dict)} if isinstance(body, dict) else set()
    return ids | {i.removesuffix(":latest") for i in ids}


async def _check_model(client: httpx.AsyncClient, key: str) -> dict:
    cfg = models_cfg().get(key) or {}
    label, base, model = MODEL_LABELS[key], (cfg.get("base_url") or "").rstrip("/"), cfg.get("model") or ""
    if not base:
        return _item(key, label, "off", MODEL_OFF[key])
    t0 = time.perf_counter()
    try:
        r = await client.get(f"{base}/models", headers={"Authorization": f"Bearer {cfg.get('api_key') or 'EMPTY'}"})
    except httpx.HTTPError as e:
        return _item(key, label, "error", f"{model} · {base} 에 연결할 수 없습니다 ({type(e).__name__})", _ms(t0))
    except Exception as e:  # e.g. httpx.InvalidURL for a placeholder like http://<VLM 서버 주소>:<포트>/v1
        return _item(key, label, "error", f"models.yaml 의 주소가 올바르지 않습니다: {base} ({type(e).__name__})", _ms(t0))
    ms = _ms(t0)
    if r.status_code >= 500 or r.status_code in (401, 403):
        return _item(key, label, "error", f"{model} · {base} 응답 {r.status_code}", ms)
    try:
        ids = _model_ids(r.json()) if r.status_code == 200 else set()
    except ValueError:
        ids = set()
    if ids and model not in ids:
        return _item(key, label, "warn", f"서버는 응답하지만 {model} 모델이 없습니다. 있는 모델: {', '.join(sorted(ids)[:5])}", ms)
    return _item(key, label, "ok", f"{model} · 응답 {ms}ms", ms)


def _version(v) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in str(v).split(".")[:2])
    except ValueError:
        return (0,)


async def _check_toolpdf(client: httpx.AsyncClient) -> tuple[dict | None, dict]:
    """ToolPDF's health (None when it does not answer) and its status item."""
    base, mode, label = settings.toolpdf_url.rstrip("/"), settings.toolpdf_transfer, "PDF 엔진 (ToolPDF)"
    t0 = time.perf_counter()
    try:
        r = await client.get(f"{base}/v1/health")
        h = r.json() if r.status_code == 200 else {}
    except Exception as e:
        return None, _item("engine", label, "error", f"{base} 에 연결할 수 없습니다 ({type(e).__name__}). 문서를 처리할 수 없습니다", _ms(t0))
    ms = _ms(t0)
    if not h:
        return None, _item("engine", label, "error", f"{base} 응답 {r.status_code}", ms)
    if mode == "shared" and "shared" not in h.get("transfer", []):
        return h, _item("engine", label, "error", "RAG_TOOLPDF_TRANSFER=shared 인데 엔진에 공유 폴더(TOOLPDF_SHARED_ROOT)가 없습니다", ms)
    # The engine may have been upgraded while the app runs: ask again whether it takes options.
    known = toolpdf()._options
    if known is not False and (known or {}).get("version") != h.get("version"):
        toolpdf().reset()
    new = _version(h.get("version")) >= (0, 2)
    opts = "옵션 지원" if new else "옵션 미지원(0.2.0 이상 필요, 규칙의 PDF 엔진 옵션과 암호 PDF를 쓸 수 없음)"
    return h, _item("engine", label, "ok" if new else "warn",
                    f"{h.get('engine')} · ToolPDF {h.get('version')} · {opts} · 파일 전달 {mode} · 응답 {ms}ms", ms)


def _office_item(where: str, soffice: str | None) -> dict:
    if soffice:
        return _item("office", "LibreOffice", "ok", f"{where}에 있음: .doc, .ppt, .hwp도 변환합니다")
    return _item("office", "LibreOffice", "off", f"{where}에 없음: docx, pptx, xlsx는 자체 변환, .doc, .ppt, .hwp는 처리할 수 없습니다")


async def _check_engine(client: httpx.AsyncClient) -> list[dict]:
    """The PDF engine in use (RAG_PDF_ENGINE) and, through it, LibreOffice. In auto mode ToolPDF is asked too:
    the item says which engine the next run uses."""
    eng = engine()
    if eng.mode == "local":
        h = await asyncio.to_thread(local().health)
        return [_item("engine", "PDF 엔진 (내장)", "ok", f"RAG_PDF_ENGINE=local · {h['engine']}"),
                _office_item("이 서버", h.get("libreoffice"))]
    h, item = await _check_toolpdf(client)
    if eng.mode == "toolpdf" or h is not None:
        if eng.mode == "auto":
            item["detail"] = "auto: " + item["detail"]
            if eng.impl.name == "local":
                item["detail"] += " · 지금은 내장 엔진 사용 중, 다음 실행부터 ToolPDF"
        office = _office_item("PDF 엔진", h.get("libreoffice")) if h else _item("office", "LibreOffice", "off", "PDF 엔진에 연결되지 않아 알 수 없습니다")
        return [item, office]
    # auto and ToolPDF does not answer: the local engine processes documents
    lh = await asyncio.to_thread(local().health)
    return [_item("engine", "PDF 엔진 (내장)", "warn",
                  f"auto: ToolPDF({settings.toolpdf_url})에 연결되지 않아 내장 엔진으로 처리합니다 · {lh['engine']}"),
            _office_item("이 서버", lh.get("libreoffice"))]


def _runs() -> dict:
    with session() as s:
        rows = dict(s.execute(select(Run.status, func.count()).where(Run.status.in_(["running", "queued"])).group_by(Run.status)).all())
    return {"running": rows.get("running", 0), "queued": rows.get("queued", 0)}


async def _collect() -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        db, vectors, runs, (engine_item, office), *model_items = await asyncio.gather(
            asyncio.to_thread(_check_db), asyncio.to_thread(_check_vectors), asyncio.to_thread(_runs), _check_engine(client),
            *(_check_model(client, k) for k in ("embedding", "vlm", "reranker")))
    items = [_item("api", "API 서버", "ok", "응답 중"), db, vectors, engine_item, *model_items, office]
    states = {i["state"] for i in items}
    overall = "error" if "error" in states else "warn" if "warn" in states else "ok"
    return {"overall": overall, "version": os.environ.get("INGESTLENS_VERSION", "dev"),
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "items": items, "runs": runs}


@router.get("/status")
async def status(refresh: bool = False) -> dict:
    """Per-component state. Model servers are probed with GET {base_url}/models (OpenAI-compatible)."""
    if refresh or not _cache["value"] or time.monotonic() - _cache["at"] > CACHE_S:
        _cache["value"], _cache["at"] = await _collect(), time.monotonic()
    return _cache["value"]
