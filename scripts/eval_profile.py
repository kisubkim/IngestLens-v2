"""Evaluate the profiler's page classification rules against hand labels, and search better thresholds.

    python scripts/eval_profile.py --labels evals/synthetic/profile_labels.json [--sweep] [--out evals/reports/profile.md]

Labels file: {"documents": [{"file": "<path relative to the labels file>", "pages": {"<1-based page>": "<label>"}}]}
Only the rules are evaluated (config/strategy_rules.yaml profiler section), not the VLM second opinion.
docx/pptx/xlsx files are rendered natively first, as the pipeline does without LibreOffice.
--sweep runs coordinate descent over every rule threshold and prints the changes that raise accuracy;
it never edits the config. With few labels it overfits: check the suggestions against more documents.
"""

import argparse
import copy
import json
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import rules_cfg  # noqa: E402
from app.tools.pdf import classify  # noqa: E402
from app.tools.toolpdf import engine  # noqa: E402  (PDF engine ToolPDF, RAG_TOOLPDF_URL)


def load_pages(labels_path: Path) -> list[dict]:
    spec = json.loads(labels_path.read_text(encoding="utf-8"))
    tmp = Path(tempfile.mkdtemp(prefix="eval-profile-"))
    rows = []
    for d in spec["documents"]:
        src = (labels_path.parent / d["file"]).resolve()
        pdf = src
        if src.suffix.lower().lstrip(".") in ("docx", "pptx", "xlsx"):
            pdf = tmp / (src.stem + ".native.pdf")
            engine().normalize(src, src.name, "native", pdf)
        feats = {f["page"]: f["features"] for f in engine().profile(pdf, [int(p) - 1 for p in d["pages"]])}
        for p, label in d["pages"].items():
            rows.append({"doc": d["file"], "page": int(p), "label": label, "features": feats[int(p) - 1]})
    return rows


def accuracy(rows: list[dict], rules: dict) -> tuple[float, list[str]]:
    preds = [classify(r["features"], rules)["label"] for r in rows]
    return sum(p == r["label"] for p, r in zip(preds, rows)) / len(rows), preds


def sweep(rows: list[dict], rules: dict, passes: int = 3) -> tuple[dict, list[dict]]:
    """Coordinate descent over every numeric threshold; candidates are midpoints between observed feature values."""
    best = copy.deepcopy(rules)
    best_acc, _ = accuracy(rows, best)
    params = [(ri, key) for ri, r in enumerate(best["rules"]) for key in r["when"]]
    for _ in range(passes):
        improved = False
        for ri, key in params:
            feat = key.split("_", 1)[1]
            vals = sorted({r["features"][feat] for r in rows})
            cands = {(a + b) / 2 for a, b in zip(vals, vals[1:])} | {best["rules"][ri]["when"][key]}
            cur = best["rules"][ri]["when"][key]
            for c in sorted(cands, key=lambda v: abs(v - cur)):  # nearest first: ties keep small changes
                trial = copy.deepcopy(best)
                trial["rules"][ri]["when"][key] = round(c, 4)
                acc, _ = accuracy(rows, trial)
                if acc > best_acc + 1e-9:
                    best, best_acc, improved = trial, acc, True
        if not improved:
            break
    changes = [{"rule": rules["rules"][ri]["id"], "condition": key, "from": rules["rules"][ri]["when"][key], "to": best["rules"][ri]["when"][key]}
               for ri, key in params if rules["rules"][ri]["when"][key] != best["rules"][ri]["when"][key]]
    return best, changes


def report(rows: list[dict], rules: dict, do_sweep: bool) -> str:
    acc, preds = accuracy(rows, rules)
    labels = sorted({r["label"] for r in rows} | set(preds))
    conf = defaultdict(Counter)
    for r, p in zip(rows, preds):
        conf[r["label"]][p] += 1
    out = [f"# Profiler evaluation ({date.today()})", "",
           f"- labeled pages: {len(rows)}", f"- accuracy (rules only): **{acc:.1%}**", "",
           "## Confusion matrix (rows = label, columns = predicted)", "",
           "| label \\ pred | " + " | ".join(labels) + " |", "|---|" + "---|" * len(labels)]
    for lab in labels:
        out.append(f"| {lab} | " + " | ".join(str(conf[lab][p]) for p in labels) + " |")
    wrong = [(r, p) for r, p in zip(rows, preds) if p != r["label"]]
    out += ["", "## Misclassified pages", ""]
    if not wrong:
        out.append("none")
    for r, p in wrong:
        f = {k: v for k, v in r["features"].items() if k != "size_hist"}
        out.append(f"- {r['doc']} p.{r['page']}: label **{r['label']}**, predicted **{p}** — `{f}`")
    if do_sweep:
        best, changes = sweep(rows, rules)
        new_acc, _ = accuracy(rows, best)
        out += ["", "## Threshold sweep", "", f"accuracy {acc:.1%} → **{new_acc:.1%}**", ""]
        if changes:
            out += ["| rule | condition | current | suggested |", "|---|---|---|---|"]
            out += [f"| {c['rule']} | {c['condition']} | {c['from']} | {c['to']} |" for c in changes]
            out += ["", "Apply by hand in `config/strategy_rules.yaml` after checking on more documents (few labels overfit)."]
        else:
            out.append("No threshold change improves accuracy on these labels.")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    rows = load_pages(a.labels)
    text = report(rows, rules_cfg()["profiler"], a.sweep)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text, encoding="utf-8")
        print(f"report: {a.out}")
    print(text)


if __name__ == "__main__":
    main()
