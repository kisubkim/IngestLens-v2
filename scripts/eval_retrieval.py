"""Evaluate retrieval quality per search mode on documents with known answers.

    python scripts/eval_retrieval.py --dataset evals/synthetic/retrieval.json [--models my_models.yaml] [--k 5] [--out report.md]

Dataset: {"documents": [{"file": "<path relative to the dataset>", "queries": [
            {"q": "...", "pages": [<1-based pages>], "text": "<substring>", "kind": "lexical|paraphrase"}]}]}
A hit is relevant when it covers one of `pages` or contains `text` (give either or both).
Every document runs through the full pipeline in a scratch data dir with the given models.yaml,
then each query runs in dense, lexical and hybrid mode (and hybrid+rerank when a reranker is configured).
Metrics: hit@1, hit@k, MRR@k, overall and per query kind.
"""

import argparse
import asyncio
import json
import tempfile
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

from _inproc import ROOT, ingest, setup, shutdown


def relevant(hit: dict, qd: dict) -> bool:
    if qd.get("pages") and {p - 1 for p in qd["pages"]} & set(hit["pages"]):
        return True
    return bool(qd.get("text")) and qd["text"] in hit["text"]


async def evaluate(dataset: Path, k: int) -> dict:
    from app.agents.retriever import search
    from app.tools.reranker import Reranker

    spec = json.loads(dataset.read_text(encoding="utf-8"))
    modes = [("dense", False), ("lexical", False), ("hybrid", False)] + ([("hybrid", True)] if Reranker().enabled else [])
    ranks: dict[str, list[dict]] = defaultdict(list)
    docs_info = []
    for d in spec["documents"]:
        t0 = time.perf_counter()
        _, run_id, summary = await ingest((dataset.parent / d["file"]).resolve())
        docs_info.append({"file": d["file"], "seconds": round(time.perf_counter() - t0, 1), "chunks": summary.get("chunk", {}).get("count"),
                          "embedding": summary.get("embed", {}).get("model"), "chars_per_token": summary["plan"]["chunking"].get("chars_per_token")})
        for qd in d["queries"]:
            for mode, rr in modes:
                res = await search(qd["q"], k, run_id=run_id, mode=mode, rerank=rr)
                rank = next((h["rank"] for h in res["hits"] if relevant(h, qd)), None)
                ranks[mode + ("+rerank" if rr else "")].append({"doc": d["file"], "q": qd["q"], "kind": qd.get("kind", "-"), "rank": rank})
    return {"docs": docs_info, "ranks": ranks}


def metrics(rows: list[dict], k: int) -> dict:
    n = len(rows) or 1
    return {"n": len(rows), "hit@1": sum(r["rank"] == 1 for r in rows) / n, f"hit@{k}": sum(r["rank"] is not None for r in rows) / n,
            "mrr": sum(1 / r["rank"] for r in rows if r["rank"]) / n}


def report(res: dict, k: int, models_file: Path) -> str:
    out = [f"# Retrieval evaluation ({date.today()})", "", f"- models: `{Path(models_file).name}`", f"- k = {k}", "", "## Documents", "",
           "| file | chunks | embedding | chars/token | ingest s |", "|---|---|---|---|---|"]
    out += [f"| {d['file']} | {d['chunks']} | {d['embedding']} | {d['chars_per_token']} | {d['seconds']} |" for d in res["docs"]]
    kinds = sorted({r["kind"] for rows in res["ranks"].values() for r in rows})
    out += ["", "## Metrics", "", f"| mode | query kind | n | hit@1 | hit@{k} | MRR |", "|---|---|---|---|---|---|"]
    for mode, rows in res["ranks"].items():
        for kind in ["all"] + kinds:
            sel = rows if kind == "all" else [r for r in rows if r["kind"] == kind]
            m = metrics(sel, k)
            out.append(f"| {mode} | {kind} | {m['n']} | {m['hit@1']:.0%} | {m[f'hit@{k}']:.0%} | {m['mrr']:.2f} |")
    out += ["", "## Per query (rank of first relevant hit, — = not in top k)", "", "| doc | query | kind | " + " | ".join(res["ranks"]) + " |",
            "|---|---|---|" + "---|" * len(res["ranks"])]
    first = next(iter(res["ranks"].values()))
    for i, r in enumerate(first):
        cells = [str(rows[i]["rank"] or "—") for rows in res["ranks"].values()]
        out.append(f"| {r['doc']} | {r['q']} | {r['kind']} | " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--models", type=Path, default=ROOT / "config" / "models.yaml")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--workdir", type=Path)
    a = ap.parse_args()
    setup(a.workdir or Path(tempfile.mkdtemp(prefix="rag-eval-")), a.models.resolve())
    try:
        res = asyncio.run(evaluate(a.dataset.resolve(), a.k))
    finally:
        shutdown()
    text = report(res, a.k, a.models)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text, encoding="utf-8")
        print(f"report: {a.out}")
    print(text)


if __name__ == "__main__":
    main()
