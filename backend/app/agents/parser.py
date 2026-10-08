"""Parser agent: run the planned parser on every page and store unified elements.

Pages are processed in windows. The PDF engine prepares a window (native text and tables, figure
regions, rendered crops), then the window's VLM calls run concurrently while the next windows prepare.
The engine runs its own process pool; parse.windows_in_flight bounds how many windows are asked at once.
The global VLM semaphore (tools/vlm.py) bounds load on the vLLM server.
"""

import asyncio
import time
from collections import Counter
from pathlib import Path

from sqlalchemy import select

from ..config import models_cfg, rules_cfg
from ..db import session
from ..events import emit_event, record_decision
from ..models import Element, PageProfile
from ..tools.figures import attach_captions
from ..tools.toolpdf import engine
from ..tools.vlm import PROMPTS, VLMClient
from ..tools.vlm_output import md_to_elements, parse_figure, strip_fences
from .common import PipelineState, update_summary

STEP = "parse"


async def _prepare(pdf_path: str, *args) -> dict[int, dict]:
    """Native elements, figure regions and VLM jobs (with crops) of one window, from the PDF engine."""
    return await asyncio.to_thread(engine().extract, Path(pdf_path), *args)


async def _run_jobs(vlm: VLMClient, preps: dict[int, dict], stats: Counter) -> None:
    first_limit = vlm.cfg.get("max_tokens", 2048)
    retry_limit = vlm.cfg.get("max_tokens_retry", first_limit * 2)

    async def one(job: dict) -> None:
        stats["vlm_image_bytes"] += len(job["image"])
        try:
            job["result"] = await vlm.ask(job["image"], PROMPTS[job["kind"]])
            # A long page or table hit the answer limit: ask once more with a bigger limit instead of losing the tail.
            if job["result"].finish_reason == "length" and retry_limit > first_limit:
                first = job["result"]
                job["result"] = await vlm.ask(job["image"], PROMPTS[job["kind"]], max_tokens=retry_limit)
                job["retry"] = {"max_tokens": first_limit, "retry_max_tokens": retry_limit, "first_seconds": first.seconds}
        except Exception as e:  # recorded per page during merge; the run continues
            job["error"] = f"{type(e).__name__}: {e}"
        finally:
            job["image"] = None  # release the crop as soon as it is sent

    await asyncio.gather(*(one(j) for prep in preps.values() for j in prep["jobs"]))


def _merge(run_id: str, page: int, label: str, prep: dict, pcfg: dict, stats: Counter) -> list[dict]:
    els = list(prep["elements"])
    for job in prep["jobs"]:
        res, err = job.get("result"), job.get("error")
        stats["vlm_calls"] += 1
        if err:
            stats["vlm_errors"] += 1
        else:
            stats["vlm_seconds_x100"] += int(res.seconds * 100)
            if job.get("retry"):
                stats["vlm_retried"] += 1
                stats["vlm_seconds_x100"] += int(job["retry"]["first_seconds"] * 100)
                still = res.finish_reason == "length"
                record_decision(run_id, STEP, f"page {page + 1}", f"VLM {job['kind']} retried with max_tokens {job['retry']['retry_max_tokens']}",
                                rule_id="vlm_truncated_retry", inputs={**job["retry"], "kind": job["kind"], "truncated_again": still},
                                alternatives=[{"choice": "keep truncated answer", "reason_rejected": "the end of the page or table would be lost"}],
                                confidence=0.5 if still else 0.8,
                                reasoning="The first answer stopped at max_tokens (finish_reason=length), so the same request was sent "
                                          "once more with a larger limit." + (" It was truncated again." if still else ""))
            if res.finish_reason == "length":
                stats["vlm_truncated"] += 1
                emit_event(run_id, "warning", STEP, f"page {page + 1}: VLM {job['kind']} answer truncated at max_tokens")

        if job["kind"] == "ocr":
            new = md_to_elements(res.text, job["bbox"], "vlm_ocr") if not err else []
            if new:
                els = new
            else:
                els = prep["fallback"]
                record_decision(run_id, STEP, f"page {page + 1}", "fallback pymupdf_text", rule_id="vlm_error",
                                inputs={"planned_parser": "vlm_ocr"}, confidence=0.3,
                                reasoning=err or "VLM returned an empty transcription.")
        elif job["kind"] == "table":
            t = job["target"]
            if err or not res.text.strip():
                emit_event(run_id, "warning", STEP, f"page {page + 1}: table re-extraction failed, kept native table", {"error": err})
                continue
            before = t["meta"]["empty_cell_ratio"]
            t["content"], t["source_tool"] = strip_fences(res.text), "vlm_table"
            t["meta"]["reextracted"] = True
            stats["tables_reextracted"] += 1
            record_decision(run_id, STEP, f"page {page + 1}", "table re-extracted with VLM", rule_id="table_empty_cells",
                            inputs={"empty_cell_ratio": before, "max_empty_cell_ratio": pcfg["tables"]["max_empty_cell_ratio"], "bbox": t["bbox"]},
                            alternatives=[{"choice": "keep pymupdf table", "reason_rejected": "too many empty cells (merged or borderless cells)"}],
                            confidence=0.7)
        elif job["kind"] == "figure":
            if err:
                emit_event(run_id, "warning", STEP, f"page {page + 1}: figure description failed", {"error": err, "bbox": job["bbox"]})
                continue
            ftype, body = parse_figure(res.text)
            if not body:
                continue
            stats["figures_described"] += 1
            els.append({"type": "figure", "bbox": job["bbox"], "content": body, "source_tool": "vlm_figures",
                        "meta": {"figure_type": ftype, "region_source": job["region"]["source"],
                                 "area_ratio": job["region"]["area_ratio"], "vlm_seconds": res.seconds}})

    # Stable sort: OCR elements share the page bbox and keep their order. A whole-page figure goes last,
    # so the page's own title comes first and the figure chunk gets this page's section, not the previous one.
    els.sort(key=lambda e: (1 if (e.get("meta") or {}).get("region_source") == "page" else 0, e["bbox"][1], e["bbox"][0]))
    return attach_captions(els, pcfg["captions"]["pattern"], pcfg["captions"]["max_gap"])


def _norm(t: str) -> str:
    return " ".join(t.split()).lower()


def _md_table(rows: list[list]) -> str:
    cells = [[str(int(c)) if isinstance(c, float) and c.is_integer() else str(c) for c in r] for r in rows]
    head = "| " + " | ".join(cells[0]) + " |\n|" + "---|" * len(cells[0])
    return head + "".join("\n| " + " | ".join(r) + " |" for r in cells[1:])


def _apply_hints(page: int, els: list[dict], hints: dict, rect: list[float], stats: Counter) -> list[dict]:
    """Office structure the PDF cannot carry: real headings, speaker notes, native chart data."""
    if not hints:
        return els
    titles = {_norm(h["text"]) for h in hints.get("headings", [])} | {_norm(s["title"]) for s in hints.get("slides", []) if s["title"]}
    for e in els:
        if e["type"] == "text" and _norm(e["content"]) in titles:
            e["type"] = "title"
            e.setdefault("meta", {})["source"] = "office_heading"
            stats["hint_titles"] += 1
    for sl in hints.get("slides", []):
        if sl.get("page") != page:
            continue
        # Native rendering already draws chart data as a table; LibreOffice draws the chart as vector art.
        if hints.get("renderer") == "libreoffice":
            for ch in sl["charts"]:
                cap = f"차트: {ch['title']}\n\n" if ch["title"] else "차트\n\n"
                els.append({"type": "table", "bbox": rect, "content": cap + _md_table(ch["rows"]), "source_tool": "pptx_chart_data",
                            "meta": {"source": "pptx_chart_data"}})
                stats["chart_tables"] += 1
        if sl["notes"]:
            strip = [rect[0], rect[3] - 24, rect[2], rect[3]]
            els.append({"type": "text", "bbox": strip, "content": f"[발표자 노트] {sl['notes']}", "source_tool": "pptx_notes",
                        "meta": {"source": "speaker_notes"}})
            stats["notes"] += 1
    return els


def _maybe_relabel(run_id: str, page: int, label: str, els: list[dict], min_area: float) -> str | None:
    if label not in ("diagram", "image_heavy"):
        return None
    charts = [e for e in els if (e.get("meta") or {}).get("figure_type") == "chart" and e["meta"]["area_ratio"] >= min_area]
    if not charts:
        return None
    area = max(e["meta"]["area_ratio"] for e in charts)
    record_decision(run_id, STEP, f"page {page + 1}", f"relabel {label} -> chart", rule_id="vlm_figure_type",
                    inputs={"rule_label": label, "vlm_figure_type": "chart", "chart_area_ratio": area, "min_area": min_area},
                    confidence=0.8, reasoning="The VLM identified the main figure on this page as a chart.")
    return "chart"


async def parse(state: PipelineState) -> dict:
    run_id, pdf_path, n = state["run_id"], state["pdf_path"], state["page_count"]
    heading_min = state["plan"]["heading_min_size"]
    pcfg = rules_cfg()["parse"]
    vcfg = models_cfg()["vlm"]
    vlm = VLMClient()
    hints = state.get("hints") or {}

    fallback = rules_cfg()["strategy"]["fallback"]
    parser_of, label_of, drawings_of = {}, {}, {}
    with session() as s:
        for p in s.scalars(select(PageProfile).where(PageProfile.run_id == run_id)):
            parser_of[p.page], label_of[p.page], drawings_of[p.page] = p.parser, p.label, p.features.get("drawings", 0)
    size = pcfg["window_pages"]
    windows = [[(p, parser_of.get(p, fallback), drawings_of.get(p, 0)) for p in range(start, min(n, start + size))]
               for start in range(0, n, size)]

    stats: Counter = Counter()
    types: Counter = Counter()
    tools: Counter = Counter()
    relabeled: dict[int, str] = {}
    done = 0
    timing: Counter = Counter()  # summed across windows, so they can exceed wall time when windows overlap
    in_flight = asyncio.Semaphore(pcfg["windows_in_flight"])

    async def window(pages: list[tuple[int, str, int]]) -> None:
        nonlocal done
        async with in_flight:
            t0 = time.perf_counter()
            preps = await _prepare(pdf_path, pages, heading_min, pcfg, vlm.enabled, vcfg)
            t1 = time.perf_counter()
            await _run_jobs(vlm, preps, stats)
            timing["prepare_s"] += t1 - t0
            timing["vlm_wait_s"] += time.perf_counter() - t1
        rows = []
        for page in sorted(preps):
            prep = preps[page]
            stats["figure_regions"] += len(prep["regions"])
            stats["figure_regions_skipped"] += prep["skipped_regions"]
            label = label_of.get(page, "mixed")
            els = _merge(run_id, page, label, prep, pcfg, stats)
            els = _apply_hints(page, els, hints, prep["rect"], stats)
            new_label = _maybe_relabel(run_id, page, label, els, pcfg["relabel_chart_min_area"])
            if new_label:
                relabeled[page] = new_label
            for seq, e in enumerate(els):
                rows.append(Element(run_id=run_id, page=page, seq=seq, type=e["type"], bbox=e["bbox"], content=e["content"],
                                    source_tool=e["source_tool"], meta=e.get("meta") or {}))
                types[e["type"]] += 1
                tools[e["source_tool"]] += 1
        with session() as s:
            s.add_all(rows)
        done += len(pages)
        emit_event(run_id, "progress", STEP, f"Parsed pages {done}/{n}",
                   {"done": done, "total": n, "elements": sum(types.values()), "vlm_calls": stats["vlm_calls"], "vlm_errors": stats["vlm_errors"]})

    await asyncio.gather(*(window(w) for w in windows))

    if relabeled:
        with session() as s:
            for p in s.scalars(select(PageProfile).where(PageProfile.run_id == run_id, PageProfile.page.in_(list(relabeled)))):
                p.label, p.rule_id, p.confidence = relabeled[p.page], "vlm_figure_type", 0.8

    if stats["figure_regions"]:
        if vlm.enabled:
            record_decision(run_id, STEP, "figure enrichment", f"{stats['figures_described']} of {stats['figure_regions']} figures described",
                            rule_id="figure_regions",
                            inputs={"min_area_ratio": pcfg["figures"]["min_area_ratio"], "max_per_page": pcfg["figures"]["max_per_page"],
                                    "enrich_native_pages": pcfg["figures"]["enrich_native_pages"], "vlm_errors": stats["vlm_errors"]},
                            confidence=round(stats["figures_described"] / stats["figure_regions"], 2),
                            reasoning="Embedded images and vector-drawing clusters were cropped and described by the VLM, then placed at their page position.")
        else:
            record_decision(run_id, STEP, "figure enrichment", f"skipped: {stats['figure_regions_skipped']} figure regions not described",
                            rule_id="vlm_not_configured", inputs={"min_area_ratio": pcfg["figures"]["min_area_ratio"]}, confidence=0.3,
                            reasoning="Figure content is missing from the index until models.yaml vlm.base_url is set.")

    calls_ok = stats["vlm_calls"] - stats["vlm_errors"]
    summary = {
        "elements": sum(types.values()),
        "by_type": dict(types),
        "by_tool": dict(tools),
        "vlm_enabled": vlm.enabled,
        "vlm_calls": stats["vlm_calls"],
        "vlm_errors": stats["vlm_errors"],
        "vlm_truncated": stats["vlm_truncated"],
        "vlm_retried": stats["vlm_retried"],
        "vlm_avg_seconds": round(stats["vlm_seconds_x100"] / 100 / calls_ok, 2) if calls_ok else None,
        "figure_regions": stats["figure_regions"],
        "figures_described": stats["figures_described"],
        "tables_reextracted": stats["tables_reextracted"],
        "pages_relabeled": len(relabeled),
        "office_hints": {k: stats[k] for k in ("hint_titles", "notes", "chart_tables") if stats[k]},
        "window_prepare_s": round(timing["prepare_s"], 1),
        "window_vlm_wait_s": round(timing["vlm_wait_s"], 1),
        "vlm_image_mb": round(stats["vlm_image_bytes"] / 2**20, 1),
    }
    update_summary(run_id, "parse", summary)
    return {}
