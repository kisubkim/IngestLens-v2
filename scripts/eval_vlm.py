"""Evaluate VLM parsing quality (OCR, tables, figures) on pages with known content, and save a result file.

    python scripts/eval_vlm.py --models my_models.yaml --name "Qwen2.5-VL-32B vLLM" [--notes "..."]

Runs every document in the case set through the full pipeline in a scratch data dir, scores each page with
app.tools.vlm_checks, and writes evals/results/vlm/<timestamp>_<name>.json. The app's "VLM 평가 비교" screen
lists those files side by side. Keep the files in git so results from different machines can be compared.
"""

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _inproc import ROOT, ingest, setup, shutdown  # noqa: E402

RESULTS = ROOT / "evals" / "results" / "vlm"


def _git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        return out.stdout.strip() + ("+dirty" if dirty else "") if out.returncode == 0 else None
    except OSError:
        return None


def _models_meta() -> dict:
    from app.config import models_cfg

    keep = ("model", "base_url", "max_tokens", "max_concurrency", "render_dpi", "crop_dpi", "image_format")
    return {k: {f: v for f, v in (models_cfg().get(k) or {}).items() if f in keep} for k in ("vlm", "embedding", "reranker")}


def _prompts_sha() -> str:
    from app.tools.vlm import PROMPTS

    return hashlib.sha256(json.dumps(PROMPTS, sort_keys=True).encode()).hexdigest()[:12]


async def evaluate(cases_file: Path) -> dict:
    from sqlalchemy import select

    from app.db import session
    from app.models import Element, Event, PageProfile
    from app.tools.vlm_checks import score_page

    spec = json.loads(cases_file.read_text(encoding="utf-8"))
    pages, runs = [], []
    for d in spec["documents"]:
        t0 = time.perf_counter()
        _, run_id, summary = await ingest((cases_file.parent / d["file"]).resolve())
        with session() as s:
            labels = {p.page: p.label for p in s.scalars(select(PageProfile).where(PageProfile.run_id == run_id))}
            els = [{"page": e.page, "type": e.type, "content": e.content, "meta": e.meta or {}, "source_tool": e.source_tool}
                   for e in s.scalars(select(Element).where(Element.run_id == run_id).order_by(Element.page, Element.seq))]
            steps = {e.step: e.data.get("seconds") for e in s.scalars(
                select(Event).where(Event.run_id == run_id, Event.type == "step_finished"))}
        runs.append({"file": d["file"], "seconds": round(time.perf_counter() - t0, 1), "steps": steps, "parse": summary.get("parse", {})})
        for case in d["cases"]:
            page = case["page"] - 1
            mine = [e for e in els if e["page"] == page]
            checks = score_page(case["expect"], labels.get(page), mine)
            pages.append({
                "doc": d["file"], "page": case["page"], "id": case["id"], "title": case.get("title", case["id"]),
                "score": round(mean(c["score"] for c in checks), 3) if checks else None,
                "checks": checks, "label": labels.get(page),
                "vlm_seconds": round(sum(e["meta"].get("vlm_seconds") or 0 for e in mine), 1) or None,
                "elements": [{"type": e["type"], "source_tool": e["source_tool"], "content": e["content"],
                              "meta": {k: v for k, v in e["meta"].items() if k in ("figure_type", "caption", "vlm_seconds")}}
                             for e in mine],
                "expected_text": case["expect"].get("ocr_text"),
            })
    return {"dataset": spec.get("name") or cases_file.parent.name, "dataset_version": dataset_version(cases_file, spec),
            "pages": pages, "runs": runs}


def dataset_version(cases_file: Path, spec: dict) -> str:
    """Results are comparable only on the same version: it covers the expectations and the rendered pages."""
    import io

    from PIL import Image

    from app.tools.toolpdf import engine

    h = hashlib.sha256(json.dumps(spec["documents"], ensure_ascii=False, sort_keys=True).encode())
    for d in spec["documents"]:
        pdf = cases_file.parent / d["file"]
        for page in range(engine().info(pdf)["page_count"]):
            # Raw RGB of the engine's render, not the PNG bytes, so the version doesn't depend on PNG encoding.
            h.update(Image.open(io.BytesIO(engine().render(pdf, page, 40))).convert("RGB").tobytes())
    return h.hexdigest()[:12]


def summarize(res: dict) -> dict:
    checks = [c for p in res["pages"] for c in p["checks"]]
    by_check: dict[str, list] = {}
    for c in checks:
        by_check.setdefault(c["id"], []).append(c)
    parse = [r["parse"] for r in res["runs"]]
    cer = [c["value"] for c in by_check.get("ocr_cer", [])]
    return {
        "score": round(mean(p["score"] for p in res["pages"] if p["score"] is not None), 3),
        "checks_passed": sum(c["pass"] for c in checks),
        "checks_total": len(checks),
        "by_check": {k: {"label": v[0]["label"], "score": round(mean(c["score"] for c in v), 3),
                         "passed": sum(c["pass"] for c in v), "total": len(v)} for k, v in by_check.items()},
        "ocr_cer": round(mean(cer), 3) if cer else None,
        "ingest_seconds": round(sum(r["seconds"] for r in res["runs"]), 1),
        "parse_seconds": round(sum(r["steps"].get("parse") or 0 for r in res["runs"]), 1),
        "vlm_calls": sum(p.get("vlm_calls", 0) for p in parse),
        "vlm_errors": sum(p.get("vlm_errors", 0) for p in parse),
        "vlm_truncated": sum(p.get("vlm_truncated", 0) for p in parse),
        "vlm_avg_seconds": round(mean(x for x in (p.get("vlm_avg_seconds") for p in parse) if x), 2)
        if any(p.get("vlm_avg_seconds") for p in parse) else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", type=Path, required=True, help="models.yaml to evaluate")
    ap.add_argument("--name", help="label shown on the comparison screen (default: the VLM model name)")
    ap.add_argument("--notes", default="", help="free text: GPU, quantization, server options ...")
    ap.add_argument("--cases", type=Path, default=ROOT / "evals" / "vlm" / "cases.json")
    ap.add_argument("--out-dir", type=Path, default=RESULTS)
    ap.add_argument("--workdir", type=Path)
    a = ap.parse_args()
    setup(a.workdir or Path(tempfile.mkdtemp(prefix="rag-vlm-eval-")), a.models.resolve())
    try:
        res = asyncio.run(evaluate(a.cases.resolve()))
        models = _models_meta()
        prompts = _prompts_sha()
    finally:
        shutdown()
    created = datetime.now(timezone.utc)
    name = a.name or models["vlm"].get("model") or "no-vlm"
    out = {"name": name, "notes": a.notes, "created_at": created.isoformat(timespec="seconds"), "git_commit": _git_commit(),
           "models": models, "prompts_sha": prompts, "summary": summarize(res), **res}
    slug = re.sub(r"[^a-zA-Z0-9.]+", "-", name).strip("-").lower()[:60]
    path = a.out_dir / f"{created:%Y%m%d-%H%M%S}_{slug}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    s = out["summary"]
    print(f"{name}: score {s['score']:.0%}, checks {s['checks_passed']}/{s['checks_total']}, OCR CER {s['ocr_cer']}, "
          f"VLM avg {s['vlm_avg_seconds']}s, ingest {s['ingest_seconds']}s")
    for p in out["pages"]:
        fails = ", ".join(f"{c['label']}={c['value']}" for c in p["checks"] if not c["pass"])
        print(f"  p{p['page']} {p['id']:<13} {p['score']:.0%}  {fails}")
    print(f"result: {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")


if __name__ == "__main__":
    main()
