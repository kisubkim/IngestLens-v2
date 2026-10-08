"""Evaluation results for the comparison screen: the JSON files written by scripts/eval_vlm.py (read-only)."""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..config import settings

router = APIRouter(prefix="/api/evals", tags=["evals"])


def _dir() -> Path:
    return settings.evals_dir / "vlm"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/vlm")
def list_vlm() -> dict:
    """Every result file, newest first, without the per-page outputs."""
    items, errors = [], []
    for path in sorted(_dir().glob("*.json"), reverse=True):
        try:
            r = _load(path)
            items.append({"file": path.name, **{k: r.get(k) for k in
                          ("name", "notes", "created_at", "git_commit", "models", "prompts_sha", "dataset", "dataset_version", "summary")}})
        except (OSError, ValueError) as e:
            errors.append({"file": path.name, "error": str(e)})
    return {"dir": str(_dir()), "items": items, "errors": errors}


@router.get("/vlm/{file}")
def get_vlm(file: str) -> dict:
    path = _dir() / file
    if Path(file).name != file or path.suffix != ".json" or not path.is_file():
        raise HTTPException(404, "result not found")
    return {"file": file, **_load(path)}
