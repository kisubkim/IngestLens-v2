"""Agent rules screen: show the values of config/strategy_rules.yaml per agent, change them, and apply at once.

Changes are checked against tools/rules_schema.FIELDS and stored as an override in the data folder (only the keys
that differ from the shipped file). The cached rules are dropped on save, so the next agent step uses them; a run
that is already going picks the new values up from its next step on.
"""

import asyncio

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..config import RULES_OVERRIDE_ERROR, rules_base, rules_cfg, rules_override, rules_override_path, rules_version, settings
from ..graph.pipeline import _tasks
from ..tools import rules_schema
from .auth import is_local, require_admin

router = APIRouter(prefix="/api/rules", tags=["rules"])


def _overridden() -> bool:
    try:
        return bool(rules_override())
    except Exception:  # unreadable file: rules_cfg() already fell back to the shipped rules and says why
        return True


def _state(request: Request) -> dict:
    rules_cfg.cache_clear()  # the file may have been edited by hand
    base, effective = rules_base(), rules_cfg()
    host = request.client.host if request.client else ""
    return {
        "agents": rules_schema.AGENTS,
        "fields": rules_schema.FIELDS,
        "features": rules_schema.FEATURES,
        "labels": rules_schema.LABELS,
        "parsers": rules_schema.PARSERS,
        "rules": effective,
        "defaults": base,
        "changed": rules_schema.changed_paths(base, effective),
        "override_file": str(rules_override_path()),
        "overridden": _overridden(),
        "override_error": RULES_OVERRIDE_ERROR["message"],
        "rules_version": rules_version(),
        "key_required": bool(settings.api_key),
        "editable_here": bool(settings.api_key) or is_local(host),
        "active_runs": len(_tasks),
    }


@router.get("")
async def get_rules(request: Request) -> dict:
    return await asyncio.to_thread(_state, request)


class RulesUpdate(BaseModel):
    rules: dict


def _write(override: dict | None) -> None:
    path = rules_override_path()
    if override:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# Written by the IngestLens rules screen: only the values that differ from config/strategy_rules.yaml.\n"
            "# Delete this file (or press \"모두 기본값으로\") to go back to the shipped rules.\n"
            + yaml.safe_dump(override, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    elif path.exists():
        path.unlink()
    rules_cfg.cache_clear()


@router.put("", dependencies=[Depends(require_admin)])
async def put_rules(req: RulesUpdate, request: Request) -> dict:
    errors = rules_schema.validate(req.rules)
    if errors:
        raise HTTPException(400, {"errors": errors})
    await asyncio.to_thread(_write, rules_schema.diff(rules_base(), req.rules))
    return await asyncio.to_thread(_state, request)


@router.delete("", dependencies=[Depends(require_admin)])
async def reset_rules(request: Request) -> dict:
    await asyncio.to_thread(_write, None)
    return await asyncio.to_thread(_state, request)
