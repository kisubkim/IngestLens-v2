"""Large-document benchmark: run the full pipeline in-process on a big PDF and measure it.

    python scripts/bench_large.py --pdf big.pdf [--vlm-url http://127.0.0.1:8001/v1]

Use any large PDF (e.g. a few hundred pages, 150 MB, mixing text, figure and scanned pages).
ToolPDF must be running (RAG_TOOLPDF_URL, default http://127.0.0.1:8095).
Reports per-step seconds, VLM call stats and peak RSS of this process (the engine's memory is its own).
"""

import argparse
import asyncio
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import psutil
import yaml

ROOT = Path(__file__).resolve().parents[1]


class PeakRSS(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.peak = 0
        self.stop = False

    def run(self) -> None:
        p = psutil.Process()
        while not self.stop:
            rss = p.memory_info().rss
            for c in p.children(recursive=True):  # child processes, if any (the PDF engine is a separate service)
                try:
                    rss += c.memory_info().rss
                except psutil.NoSuchProcess:
                    pass
            self.peak = max(self.peak, rss)
            time.sleep(0.05)


async def run(pdf: Path) -> dict:
    from app.db import init_db, session
    from app.events import bus
    from app.graph.pipeline import run_pipeline
    from app.models import Document, Event, Run
    from sqlalchemy import select

    init_db()
    bus.bind(asyncio.get_running_loop())
    with session() as s:
        doc = Document(filename=pdf.name, sha256="bench", size=pdf.stat().st_size, path=str(pdf))
        s.add(doc)
        s.flush()
        run = Run(document_id=doc.id)
        s.add(run)
        s.flush()
        doc_id, run_id = doc.id, run.id
    try:
        await run_pipeline(run_id, doc_id)
    finally:
        from app.tools import vectorstore

        vectorstore.close()
    with session() as s:
        r = s.get(Run, run_id)
        steps = {e.step: e.data.get("seconds") for e in s.scalars(select(Event).where(Event.run_id == run_id, Event.type == "step_finished"))}
        return {"status": r.status, "error": r.error, "steps": steps, "summary": r.summary}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, required=True, help="a large PDF to ingest")
    ap.add_argument("--vlm-url", default="")
    ap.add_argument("--workdir", default="")
    a = ap.parse_args()

    work = Path(a.workdir or tempfile.mkdtemp(prefix="rag-bench-"))
    work.mkdir(parents=True, exist_ok=True)
    pdf = a.pdf.resolve()
    if not pdf.exists():
        raise SystemExit(f"{pdf} not found")

    models = yaml.safe_load((ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
    models["vlm"]["base_url"] = a.vlm_url
    models["vlm"]["model"] = "mock-vl" if a.vlm_url else models["vlm"]["model"]
    models_file = work / "models.yaml"
    models_file.write_text(yaml.safe_dump(models, allow_unicode=True), encoding="utf-8")
    os.environ["RAG_DATA_DIR"] = str(work / "data")
    os.environ["RAG_MODELS_FILE"] = str(models_file)
    sys.path.insert(0, str(ROOT / "backend"))

    mon = PeakRSS()
    mon.start()
    t0 = time.perf_counter()
    res = asyncio.run(run(pdf))
    total = time.perf_counter() - t0
    mon.stop = True

    parse = res["summary"].get("parse", {})
    print(f"status: {res['status']} {res['error'] or ''}")
    print(f"total: {total:.1f}s   peak RSS (app): {mon.peak / 2**20:.0f} MB   pdf: {pdf.stat().st_size / 2**20:.1f} MB")
    for step, secs in res["steps"].items():
        print(f"  {step:<9} {secs:>7}s")
    print("  profile:", res["summary"].get("profile", {}).get("label_counts"))
    print("  parse:  ", {k: parse.get(k) for k in ("elements", "vlm_calls", "vlm_errors", "vlm_avg_seconds", "figures_described", "window_prepare_s", "window_vlm_wait_s", "vlm_image_mb")})
    print("  chunk:  ", {k: res["summary"].get("chunk", {}).get(k) for k in ("count", "tokens_avg", "too_short", "too_long")})


if __name__ == "__main__":
    main()
