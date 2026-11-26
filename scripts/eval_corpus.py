"""All-documents search evaluation: the same question set against IngestLens' all-documents search and against an Open
WebUI knowledge base, so the two can be compared on equal terms (evals/README.md 5절).

    # IngestLens: upload the set's documents (once; same files are not processed again) and search them all
    python scripts/eval_corpus.py ingestlens --url http://127.0.0.1:8000 [--key <RAG_API_KEY>] --name "IngestLens bge-m3"
    # Open WebUI: a knowledge base made of the same files (created and filled when it does not exist yet)
    python scripts/eval_corpus.py openwebui --url http://127.0.0.1:3000 --email <e> --password <p> \
        --knowledge eval-corpus-default --name "Open WebUI 기본 로더"
    # Side-by-side report of saved runs
    python scripts/eval_corpus.py report evals/results/corpus/*.json --out evals/reports/corpus_<이름>.md

A hit is a result chunk from the expected file (`file`, or one of `files`) whose text, with all whitespace removed,
contains one of `answer` (also without whitespace). That works for any loader: page numbers are not needed. Each run
is saved as JSON in evals/results/corpus/ with the settings, every query's top results and the timings.
Metrics: hit@1, hit@k, MRR@k, doc@1 (the top result is from the right document), the text the top k hand to an LLM
(characters) and the search time per query.
"""

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SET = ROOT / "evals" / "corpus" / "queries.json"
RESULTS = ROOT / "evals" / "results" / "corpus"


def norm(s: str) -> str:
    return "".join((s or "").split()).lower()


def load_set(path: Path) -> dict:
    d = json.loads(path.read_text(encoding="utf-8"))
    d["paths"] = [(path.parent / p).resolve() for p in d["documents"]]
    for q in d["queries"]:
        q["files"] = q.get("files") or [q["file"]]
    return d


def judge(q: dict, hits: list[dict]) -> dict:
    """hits: [{file, text}] best first."""
    answers = [norm(a) for a in q.get("answer", [])]
    rank = next((i + 1 for i, h in enumerate(hits)
                 if h["file"] in q["files"] and (not answers or any(a in norm(h["text"]) for a in answers))), None)
    return {"rank": rank, "doc_top1": bool(hits) and hits[0]["file"] in q["files"]}


# ---------- IngestLens ----------

def run_ingestlens(a, ds: dict) -> tuple[dict, list[dict]]:
    c = httpx.Client(base_url=a.url.rstrip("/"), timeout=3600,
                     headers={"Authorization": f"Bearer {a.key}"} if a.key else {})
    files = [("files", (p.name, p.read_bytes())) for p in ds["paths"]]
    items = c.post("/api/ingest", files=files).raise_for_status().json()
    doc_ids = [it["document"]["id"] for it in items]
    for it in items:
        while (run := c.get(f"/api/runs/{it['run']['id']}").json())["status"] in ("queued", "running"):
            time.sleep(2)
        print(f"  {it['document']['filename']}: {run['status']}", file=sys.stderr)
    modes = [m.strip() for m in a.modes.split(",") if m.strip()]
    caps = c.get("/api/search/capabilities").json()
    runs = []
    for mode in modes:
        body_mode, rerank = ("hybrid", True) if mode == "rerank" else (mode, False)
        rows = []
        for q in ds["queries"]:
            t0 = time.perf_counter()
            res = c.post("/api/search/all", json={"query": q["q"], "top_k": a.k, "mode": body_mode, "rerank": rerank,
                                                   "document_ids": doc_ids}).raise_for_status().json()
            ms = (time.perf_counter() - t0) * 1000
            hits = [{"file": h["filename"], "text": h["text"], "pages": [p + 1 for p in h["pages"]]} for h in res["hits"]]
            rows.append({"id": q["id"], "ms": round(ms), "hits": hits, **judge(q, hits)})
        runs.append({"mode": mode, "rows": rows})
    return {"system": "ingestlens", "url": a.url, "embedding_model": caps.get("embedding_model"),
            "reranker": caps.get("reranker"), "documents": len(doc_ids)}, runs


# ---------- Open WebUI ----------

def run_openwebui(a, ds: dict) -> tuple[dict, list[dict]]:
    c = httpx.Client(base_url=a.url.rstrip("/"), timeout=3600)
    token = a.token or c.post("/api/v1/auths/signin", json={"email": a.email, "password": a.password}
                              ).raise_for_status().json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    listing = c.get("/api/v1/knowledge/").raise_for_status().json()
    kbs = listing.get("items", listing) if isinstance(listing, dict) else listing
    kb = next((k for k in kbs if k["name"] == a.knowledge), None)
    if kb is None:
        kb = c.post("/api/v1/knowledge/create", json={"name": a.knowledge, "description": "eval_corpus.py"}
                    ).raise_for_status().json()
        for p in ds["paths"]:
            f = c.post("/api/v1/files/", files={"file": (p.name, p.read_bytes())}).raise_for_status().json()
            while (st := c.get(f"/api/v1/files/{f['id']}/process/status").json().get("status")) not in ("completed", "failed"):
                time.sleep(2)
            r = c.post(f"/api/v1/knowledge/{kb['id']}/file/add", json={"file_id": f["id"]})
            print(f"  {p.name}: {st}, add {r.status_code}", file=sys.stderr)
    else:
        print(f"  knowledge base {a.knowledge!r} exists: searching it as it is", file=sys.stderr)
    cfg = c.get("/api/v1/retrieval/config").json()
    rows = []
    for q in ds["queries"]:
        t0 = time.perf_counter()
        # With a reranker Open WebUI fetches k candidates and keeps k_reranker; --candidates sets the pool
        # (IngestLens reranks max(3 x top_k, top_k) candidates).
        body = {"collection_names": [kb["id"]], "query": q["q"], "k": a.candidates or a.k, "k_reranker": a.k}
        if a.hybrid is not None:
            body["hybrid"] = a.hybrid
        res = c.post("/api/v1/retrieval/query/collection", json=body).raise_for_status().json()
        ms = (time.perf_counter() - t0) * 1000
        docs, metas = (res.get("documents") or [[]])[0], (res.get("metadatas") or [[]])[0]
        hits = [{"file": (m or {}).get("name") or (m or {}).get("source") or "", "text": d,
                 "pages": [(m or {}).get("page_label") or ((m or {}).get("page", -1) + 1)]}
                for d, m in zip(docs, metas)][: a.k]
        rows.append({"id": q["id"], "ms": round(ms), "hits": hits, **judge(q, hits)})
    hybrid = bool(cfg.get("ENABLE_RAG_HYBRID_SEARCH")) if a.hybrid is None else a.hybrid
    mode = ("hybrid" + ("+rerank" if cfg.get("RAG_RERANKING_MODEL") else "")) if hybrid else "dense"
    emb = c.get("/api/v1/retrieval/embedding").json()
    return {"system": "openwebui", "url": a.url, "knowledge": a.knowledge,
            "embedding_model": emb.get("RAG_EMBEDDING_MODEL"), "reranker": cfg.get("RAG_RERANKING_MODEL") or None,
            "loader": cfg.get("CONTENT_EXTRACTION_ENGINE") or "default", "chunk_size": cfg.get("CHUNK_SIZE"),
            "chunk_overlap": cfg.get("CHUNK_OVERLAP"), "bm25_weight": cfg.get("HYBRID_BM25_WEIGHT")}, \
        [{"mode": mode, "rows": rows}]


# ---------- metrics and report ----------

def metrics(rows: list[dict], k: int, queries: dict) -> dict:
    n = len(rows)
    ranks = [r["rank"] for r in rows]
    out = {"n": n,
           "hit@1": sum(1 for x in ranks if x == 1) / n,
           f"hit@{k}": sum(1 for x in ranks if x and x <= k) / n,
           "mrr": sum(1 / x for x in ranks if x) / n,
           "doc@1": sum(1 for r in rows if r["doc_top1"]) / n,
           "context_chars": statistics.mean(sum(len(h["text"]) for h in r["hits"]) for r in rows),
           "ms_avg": statistics.mean(r["ms"] for r in rows),
           "ms_p95": sorted(r["ms"] for r in rows)[max(0, int(0.95 * n) - 1)]}
    kinds: dict[str, list[dict]] = {}
    for r in rows:
        kinds.setdefault(queries[r["id"]]["kind"], []).append(r)
    out["by_kind"] = {kd: {"n": len(rs), "hit@1": sum(1 for r in rs if r["rank"] == 1) / len(rs),
                           f"hit@{k}": sum(1 for r in rs if r["rank"] and r["rank"] <= k) / len(rs)}
                      for kd, rs in sorted(kinds.items())}
    return out


def save(a, ds: dict, info: dict, runs: list[dict]) -> Path:
    queries = {q["id"]: q for q in ds["queries"]}
    for r in runs:
        r["metrics"] = metrics(r["rows"], a.k, queries)
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = RESULTS / f"{stamp}_{''.join(ch if ch.isalnum() else '_' for ch in a.name)[:40]}.json"
    doc = {"name": a.name, "notes": a.notes, "created_at": datetime.now().isoformat(timespec="seconds"),
           "dataset": ds["name"], "dataset_queries": len(ds["queries"]), "k": a.k, **info, "runs": runs}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in runs:
        m = r["metrics"]
        print(f"{a.name} [{r['mode']}] hit@1 {m['hit@1']:.0%} hit@{a.k} {m[f'hit@{a.k}']:.0%} MRR {m['mrr']:.2f} "
              f"doc@1 {m['doc@1']:.0%} context {m['context_chars']:.0f} chars, {m['ms_avg']:.0f} ms")
    print("saved", path)
    return path


def report(paths: list[Path], out: Path | None, dataset: Path) -> str:
    ds = load_set(dataset)
    queries = {q["id"]: q for q in ds["queries"]}
    results = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    k = results[0]["k"]
    cols = [(r, run) for r in results for run in r["runs"]]
    label = [f"{r['name']} [{run['mode']}]" for r, run in cols]
    lines = [f"# 전체 문서 검색 비교: {ds['name']}", "",
             f"질문 {len(ds['queries'])}개, 상위 {k}개. 정답 판정은 `scripts/eval_corpus.py` 맨 위 설명.", "",
             "| 설정 | 시스템 | 임베딩 | 로더·청크 | 메모 |", "|---|---|---|---|---|"]
    for r in results:
        loader = (f"{r.get('loader')}, {r.get('chunk_size')}/{r.get('chunk_overlap')}" if r["system"] == "openwebui"
                  else "IngestLens 파이프라인")
        lines.append(f"| {r['name']} | {r['system']} | {r.get('embedding_model')} | {loader} | {r.get('notes') or ''} |")
    keys = ["hit@1", f"hit@{k}", "mrr", "doc@1", "context_chars", "ms_avg"]
    lines += ["", "| 지표 | " + " | ".join(label) + " |", "|---|" + "---|" * len(cols)]
    for key in keys:
        vals = []
        for _, run in cols:
            v = run["metrics"][key]
            vals.append(f"{v:.0%}" if key in ("hit@1", f"hit@{k}", "doc@1") else f"{v:.2f}" if key == "mrr" else f"{v:,.0f}")
        lines.append(f"| {key} | " + " | ".join(vals) + " |")
    kinds = sorted({kd for _, run in cols for kd in run["metrics"]["by_kind"]})
    lines += ["", "질문 종류별 hit@1 / hit@k:", "", "| 종류 (개수) | " + " | ".join(label) + " |", "|---|" + "---|" * len(cols)]
    for kd in kinds:
        n = cols[0][1]["metrics"]["by_kind"].get(kd, {}).get("n", 0)
        vals = [f"{run['metrics']['by_kind'][kd]['hit@1']:.0%} / {run['metrics']['by_kind'][kd][f'hit@{k}']:.0%}"
                if kd in run["metrics"]["by_kind"] else "-" for _, run in cols]
        lines.append(f"| {kd} ({n}) | " + " | ".join(vals) + " |")
    lines += ["", "질문별 정답 순위(없으면 -):", "", "| id | 질문 | " + " | ".join(label) + " |", "|---|---|" + "---|" * len(cols)]
    for qid, q in queries.items():
        vals = []
        for _, run in cols:
            row = next((x for x in run["rows"] if x["id"] == qid), None)
            vals.append("" if row is None else str(row["rank"] or "-"))
        lines.append(f"| {qid} | {q['q']} | " + " | ".join(vals) + " |")
    text = "\n".join(lines) + "\n"
    if out:
        out.write_text(text, encoding="utf-8")
        print("wrote", out)
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("ingestlens", "openwebui"):
        p = sub.add_parser(name)
        p.add_argument("--url", required=True)
        p.add_argument("--dataset", type=Path, default=DEFAULT_SET)
        p.add_argument("--k", type=int, default=5)
        p.add_argument("--name", required=True, help="이 설정의 이름 (결과 파일과 보고서에 쓴다)")
        p.add_argument("--notes", default="", help="모델, GPU, 설정 등 메모")
    il = sub.choices["ingestlens"]
    il.add_argument("--key", default="", help="RAG_API_KEY")
    il.add_argument("--modes", default="dense,lexical,hybrid", help="쉼표 목록: dense, lexical, hybrid, rerank")
    ow = sub.choices["openwebui"]
    ow.add_argument("--token", default="")
    ow.add_argument("--email", default="")
    ow.add_argument("--password", default="")
    ow.add_argument("--knowledge", required=True, help="지식 베이스 이름 (없으면 만들고 문서를 넣는다)")
    ow.add_argument("--candidates", type=int, default=0,
                    help="후보 수(RAG_TOP_K). reranker가 있을 때 이만큼 뽑아 rerank하고 상위 k개를 쓴다 (기본: k)")
    ow.add_argument("--hybrid", action=argparse.BooleanOptionalAction, default=None,
                    help="Open WebUI 설정 대신 hybrid를 켜거나 끈다 (기본: Open WebUI 설정대로)")
    rp = sub.add_parser("report")
    rp.add_argument("results", type=Path, nargs="+")
    rp.add_argument("--dataset", type=Path, default=DEFAULT_SET)
    rp.add_argument("--out", type=Path)
    a = ap.parse_args()
    if a.cmd == "report":
        text = report(a.results, a.out, a.dataset)
        if not a.out:
            print(text)
        return
    ds = load_set(a.dataset)
    info, runs = (run_ingestlens if a.cmd == "ingestlens" else run_openwebui)(a, ds)
    save(a, ds, info, runs)


if __name__ == "__main__":
    main()
