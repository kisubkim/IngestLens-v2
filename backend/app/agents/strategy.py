"""Strategy agent: pick a parser per page and a chunking strategy for the document."""

import asyncio
from collections import Counter
from pathlib import Path

from sqlalchemy import select

from ..config import models_cfg, rules_cfg, rules_override, rules_version
from ..db import session
from ..events import record_decision
from ..models import PageProfile
from ..tools.chunking import CHARS_PER_TOKEN
from ..tools.embedding import count_tokens
from ..tools.pdf import body_font_size
from ..tools.toolpdf import engine
from ..tools.vlm import VLMClient
from .common import PipelineState, update_summary

STEP = "strategy"
SLIDE_FORMATS = {"ppt", "pptx", "odp"}
SHEET_FORMATS = {"xls", "xlsx", "ods"}


async def strategy(state: PipelineState) -> dict:
    run_id = state["run_id"]
    cfg = rules_cfg()["strategy"]
    vlm_enabled = VLMClient().enabled

    with session() as s:
        profiles = s.scalars(select(PageProfile).where(PageProfile.run_id == run_id).order_by(PageProfile.page)).all()

        # Parser per page label; VLM parsers degrade to the native fallback when no VLM is served.
        mapping, wanted = {}, {}
        for label, parser in cfg["parsers"].items():
            if parser.startswith("vlm_") and not vlm_enabled:
                mapping[label], wanted[label] = cfg["fallback"], parser
            else:
                mapping[label] = parser
        for p in profiles:
            p.parser = mapping.get(p.label, cfg["fallback"])
        used = Counter(p.parser for p in profiles)
        label_counts = Counter(p.label for p in profiles)

        size_hist: Counter = Counter()
        for p in profiles:
            size_hist.update(p.features.get("size_hist", {}))
        heading_pages = 0
        body = body_font_size(dict(size_hist))
        heading_min = round(body * cfg["heading_size_ratio"], 1) if body else None
        if heading_min:
            heading_pages = sum(any(float(k) >= heading_min for k in p.features.get("size_hist", {})) for p in profiles)

    degraded = {label: w for label, w in wanted.items() if label_counts.get(label)}
    record_decision(
        run_id, STEP, "parser selection", ", ".join(f"{k} x{v}" for k, v in used.most_common()),
        rule_id="label_to_parser",
        inputs={"label_counts": dict(label_counts), "mapping": mapping, "vlm_enabled": vlm_enabled},
        alternatives=[{"choice": f"{label} -> {w}", "reason_rejected": "VLM not configured; used " + cfg["fallback"]} for label, w in degraded.items()],
        confidence=1.0 if not degraded else 0.6,
        reasoning="Each page uses the parser mapped to its profile label in strategy_rules.yaml.",
    )

    n = max(1, len(profiles))
    heading_ratio = round(heading_pages / n, 3)
    fmt = state.get("format")
    hints = state.get("hints") or {}
    if fmt in SLIDE_FORMATS:
        strat, rule, why = "page", "slides", "Slides are self-contained units, so one chunk group per slide."
    elif fmt in SHEET_FORMATS:
        strat, rule, why = "page", "sheets", "Each page is one block of sheet rows with its header; keep blocks apart."
    elif hints.get("headings"):
        strat, rule, why = "section", "docx_headings", f"The document defines {len(hints['headings'])} headings with heading styles; split on them."
    elif heading_ratio >= cfg["section_min_page_ratio"]:
        strat, rule, why = "section", "heading_structure", f"{heading_ratio:.0%} of pages have heading-size text, so split on sections."
    else:
        strat, rule, why = "recursive", "no_structure", f"Only {heading_ratio:.0%} of pages have headings; use size-based recursive split."
    alternatives = [{"choice": s, "reason_rejected": r} for s, r in [
        ("section", f"heading page ratio {heading_ratio} < {cfg['section_min_page_ratio']}"),
        ("page", "not a slide or sheet format"),
        ("recursive", "document has usable structure"),
    ] if s != strat]

    emb_max = models_cfg()["embedding"]["max_tokens"]
    target = min(cfg["target_tokens"], emb_max - 16)
    overlap = min(cfg["overlap_tokens"], target // 4)
    min_tokens = min(cfg.get("min_tokens", 0), target // 2)
    cpt = await _calibrate_chars_per_token(run_id, state["pdf_path"])
    record_decision(
        run_id, STEP, "chunking", f"{strat} (target {target} tokens, overlap {overlap}, min {min_tokens})",
        rule_id=rule,
        inputs={"format": fmt, "body_font_size": body, "heading_min_size": heading_min, "heading_page_ratio": heading_ratio,
                "section_min_page_ratio": cfg["section_min_page_ratio"], "embedding_max_tokens": emb_max,
                "rules_version": rules_version(), "rules_changed_on_screen": bool(rules_override())},
        alternatives=alternatives, confidence=0.8, reasoning=why + " Tables and figures are always kept as separate chunks.",
    )

    plan = {
        "parsers": mapping,
        "parser_usage": dict(used),
        "heading_min_size": heading_min,
        "rules_version": rules_version(),
        "chunking": {"strategy": strat, "target_tokens": target, "overlap_tokens": overlap, "min_tokens": min_tokens,
                     "chars_per_token": cpt},
    }
    update_summary(run_id, "plan", plan)
    return {"plan": plan}


def _sample_text(pdf_path: str, limit: int = 6000) -> str:
    return engine().text(Path(pdf_path), limit)


async def _calibrate_chars_per_token(run_id: str, pdf_path: str) -> float:
    """Chunk budgets are in model tokens, but the chunker measures characters. Measure the ratio on this
    document with the embedding model's tokenizer; fall back to the default when it cannot be measured."""
    sample = await asyncio.to_thread(_sample_text, pdf_path)
    count = await count_tokens(sample) if len(sample) >= 200 else None
    if count:
        cpt = round(min(max(len(sample) / count, 0.8), 6.0), 3)
        record_decision(run_id, STEP, "token estimate", f"{cpt} chars/token (measured)", rule_id="tokenizer_calibrated",
                        inputs={"sample_chars": len(sample), "sample_tokens": count, "default": CHARS_PER_TOKEN}, confidence=0.9,
                        reasoning="Measured with the embedding model's own tokenizer, so chunk sizes match what the model sees.")
        return cpt
    why = "sample too short" if len(sample) < 200 else "no tokenizer endpoint (embedding base_url empty or server lacks /tokenize)"
    record_decision(run_id, STEP, "token estimate", f"{CHARS_PER_TOKEN} chars/token (default)", rule_id="tokenizer_default",
                    inputs={"sample_chars": len(sample)}, confidence=0.5, reasoning=f"Default ratio used: {why}.")
    return CHARS_PER_TOKEN
