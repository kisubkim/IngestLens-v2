"""Profiler agent: per-page features, rule classification, VLM second opinion on uncertain pages."""

import asyncio
from collections import Counter

from pathlib import Path

from sqlalchemy import select

from ..config import rules_base, rules_cfg
from ..db import session
from ..events import emit_event, record_decision
from ..models import PageProfile
from ..tools.engine import engine, engine_rules
from ..tools.pdf import classify
from ..tools.vlm import VLMClient
from .common import PipelineState, update_summary

STEP = "profile"
LABELS = {"text", "scanned", "table", "diagram", "chart", "image_heavy", "mixed"}


def _profile_batch(run_id: str, pdf_path: str, start: int, end: int, rules: dict) -> list[tuple[int, str, float]]:
    """Features measured by the PDF engine, classified here by the rules."""
    rows = []
    for p in engine().profile(Path(pdf_path), list(range(start, end))):
        f = p["features"]
        c = classify(f, rules)
        f["evidence"] = {"conditions": c["conditions"], "evaluated": c["evaluated"]}
        rows.append(PageProfile(run_id=run_id, page=p["page"], label=c["label"], rule_id=c["rule_id"], confidence=c["confidence"], features=f))
    with session() as s:
        s.add_all(rows)
    return [(r.page, r.label, r.confidence) for r in rows]


def _render(pdf_path: str, page: int, dpi: int) -> bytes:
    return engine().render(Path(pdf_path), page, dpi)


async def _vlm_review(run_id: str, pdf_path: str, pages: list[tuple[int, str, float]], vlm: VLMClient) -> None:
    async def review(page: int, label: str, conf: float) -> None:
        png = await asyncio.to_thread(_render, pdf_path, page, 100)
        try:
            ans = await vlm.classify(png)
        except Exception as e:  # keep the rule label; the run continues
            emit_event(run_id, "warning", STEP, f"VLM review failed on page {page + 1}: {e}")
            return
        new = ans.get("label")
        if new not in LABELS or new == label:
            record_decision(run_id, STEP, f"page {page + 1}", f"keep {label}", rule_id="vlm_review",
                            inputs={"rule_label": label, "rule_confidence": conf, "vlm_label": new},
                            confidence=max(conf, 0.7), reasoning=str(ans.get("reason", "")))
            return
        with session() as s:
            p = s.scalars(select(PageProfile).where(PageProfile.run_id == run_id, PageProfile.page == page)).one()
            p.label, p.rule_id, p.confidence = new, "vlm_review", 0.7
        record_decision(run_id, STEP, f"page {page + 1}", f"relabel {label} -> {new}", rule_id="vlm_review",
                        inputs={"rule_label": label, "rule_confidence": conf, "vlm_label": new},
                        alternatives=[{"choice": label, "reason_rejected": "rule confidence low and VLM disagreed"}],
                        confidence=0.7, reasoning=str(ans.get("reason", "")))

    await asyncio.gather(*(review(*p) for p in pages))


def _record_engine_options(run_id: str) -> None:
    """Which table and image options the PDF engine got (they shape table counts here and extraction later)."""
    support = engine().options_schema()
    chosen = engine_rules()
    tables = chosen.get("tables") or {}
    if support:
        record_decision(run_id, STEP, "PDF engine options", f"tables: {tables.get('strategy')}"
                        + ("" if tables.get("enabled", True) else " (off)"), rule_id="engine_options",
                        inputs={"engine": engine().name, "engine_version": support.get("version"), **chosen}, confidence=1.0,
                        reasoning="Table and image options from the rules (engine.*) go to profiling and extraction, "
                                  "so both steps see the same tables.")
        return
    custom = chosen != (rules_base().get("engine") or {})
    record_decision(run_id, STEP, "PDF engine options", "engine defaults (options not supported)",
                    rule_id="engine_options_unsupported", inputs={"wanted": chosen},
                    alternatives=[{"choice": "rules engine.*", "reason_rejected": "the PDF engine is older than ToolPDF 0.2.0"}] if custom else [],
                    confidence=0.5 if custom else 1.0,
                    reasoning="The engine has no GET /v1/options, so requests are sent without options and it uses its own defaults."
                              + (" The changed engine options in the rules are not applied; upgrade ToolPDF." if custom else ""))


async def profile(state: PipelineState) -> dict:
    run_id, pdf_path, n = state["run_id"], state["pdf_path"], state["page_count"]
    rules = rules_cfg()["profiler"]
    batch = rules["batch_pages"]
    await asyncio.to_thread(_record_engine_options, run_id)

    results: list[tuple[int, str, float]] = []
    for start in range(0, n, batch):
        end = min(n, start + batch)
        results += await asyncio.to_thread(_profile_batch, run_id, pdf_path, start, end, rules)
        emit_event(run_id, "progress", STEP, f"Profiled pages {end}/{n}", {"done": end, "total": n})

    low = sorted((r for r in results if r[2] < rules["vlm_review_below"]), key=lambda r: r[2])[: rules["vlm_review_max_pages"]]
    vlm = VLMClient()
    if low and not vlm.enabled:
        record_decision(run_id, STEP, "VLM second opinion", "skipped", rule_id="vlm_not_configured",
                        inputs={"low_confidence_pages": [p + 1 for p, _, _ in low], "threshold": rules["vlm_review_below"]},
                        reasoning="Rule labels are kept for these pages because models.yaml vlm.base_url is empty.")
    elif low:
        await _vlm_review(run_id, pdf_path, low, vlm)

    with session() as s:
        labels = s.scalars(select(PageProfile.label).where(PageProfile.run_id == run_id)).all()
    counts = Counter(labels)
    ratios = {k: round(v / n, 3) for k, v in counts.most_common()}
    top, top_ratio = next(iter(ratios.items()))
    threshold = rules_cfg()["strategy"]["dominant_ratio"]
    kind = f"{top}-dominant" if top_ratio >= threshold else "mixed"

    summary = {"page_count": n, "label_counts": dict(counts), "label_ratios": ratios, "document_type": kind}
    record_decision(run_id, STEP, "document profile", kind, rule_id="dominant_ratio",
                    inputs={"label_ratios": ratios, "dominant_ratio_threshold": threshold},
                    confidence=round(top_ratio, 2),
                    reasoning=f"Most common page type is {top} at {top_ratio:.0%} of pages.")
    update_summary(run_id, "profile", summary)
    return {"profile": summary}
