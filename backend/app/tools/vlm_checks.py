"""Scoring for the VLM evaluation (scripts/eval_vlm.py): compare one page's parsed elements with its expectations.

Every check returns {id, label, score 0..1, pass, value}. A page's score is the mean of its check scores.
Expectations (all optional) are documented in evals/README.md.
"""

import re

_MD = re.compile(r"[#*|`>_\-:]+")
_WS = re.compile(r"\s+")


def _letters(text: str) -> str:
    """Drop Markdown syntax and all whitespace, so OCR is compared on characters only."""
    return _WS.sub("", _MD.sub("", text))


def _norm(text: str) -> str:
    return _WS.sub(" ", text).strip().lower()


def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(output: str, truth: str) -> float:
    """Character error rate on whitespace- and Markdown-free text. 0 is perfect; can exceed 1."""
    o, t = _letters(output), _letters(truth)
    return levenshtein(o, t) / max(len(t), 1)


def hangul_ratio(text: str) -> float:
    """Share of Hangul among letters, ignoring Markdown tables (data values are not prose)."""
    prose = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("|"))
    letters = [c for c in prose if c.isalpha()]
    return sum("가" <= c <= "힣" for c in letters) / len(letters) if letters else 0.0


def table_columns(markdown: str) -> int:
    rows = [r for r in markdown.splitlines() if r.strip().startswith("|") and not re.fullmatch(r"[\s|:\-]+", r)]
    return max((r.strip().strip("|").count("|") + 1 for r in rows), default=0)


def _check(cid: str, label: str, score: float, value=None, threshold: float = 1.0) -> dict:
    score = max(0.0, min(1.0, score))
    return {"id": cid, "label": label, "score": round(score, 3), "pass": score >= threshold, "value": value}


def score_page(expect: dict, label: str | None, elements: list[dict]) -> list[dict]:
    """elements: [{type, content, meta}] of one page, in reading order."""
    text = "\n\n".join(e["content"] for e in elements)
    figures = [e for e in elements if e["type"] == "figure"]
    tables = [e for e in elements if e["type"] == "table"]
    out = []

    if "label" in expect:
        out.append(_check("label", "페이지 분류", float(label == expect["label"]), label))
    if "ocr_text" in expect:
        c = cer(text, expect["ocr_text"])
        out.append(_check("ocr_cer", "OCR 정확도 (1 - CER)", 1 - c, round(c, 3), threshold=0.95))
    if "facts" in expect:
        found = [f for f in expect["facts"] if _norm(f) in _norm(text)]
        missing = [f for f in expect["facts"] if f not in found]
        out.append(_check("facts", "핵심 사실 포함", len(found) / len(expect["facts"]), {"missing": missing}))
    if "title" in expect:
        titles = [e["content"] for e in elements if e["type"] == "title"]
        out.append(_check("title", "제목 인식", float(any(expect["title"] in t for t in titles)), titles))
    if expect.get("no_single_column_table"):
        bad = [e for e in tables if table_columns(e["content"]) == 1]
        out.append(_check("no_1col_table", "본문을 1열 표로 만들지 않음", float(not bad), len(bad)))
    if "table_cells" in expect:
        body = "\n".join(e["content"] for e in tables)
        found = [c for c in expect["table_cells"] if _norm(c) in _norm(body)]
        missing = [c for c in expect["table_cells"] if c not in found]
        out.append(_check("table_cells", "표 셀 값", len(found) / len(expect["table_cells"]), {"missing": missing}))
    if "table_columns" in expect:
        cols = max((table_columns(e["content"]) for e in tables), default=0)
        out.append(_check("table_columns", "표 열 수", float(cols == expect["table_columns"]), cols))
    if "figure_type" in expect:
        types = [(e.get("meta") or {}).get("figure_type") for e in figures]
        out.append(_check("figure_type", "그림 종류(TYPE)", float(expect["figure_type"] in types), types))
    if "figure_facts" in expect:
        body = "\n".join(e["content"] for e in figures)
        found = [f for f in expect["figure_facts"] if _norm(f) in _norm(body)]
        missing = [f for f in expect["figure_facts"] if f not in found]
        out.append(_check("figure_facts", "그림 내용(값·라벨)", len(found) / len(expect["figure_facts"]), {"missing": missing}))
    if expect.get("language") == "ko":
        r = hangul_ratio("\n".join(e["content"] for e in figures) or text)
        out.append(_check("language", "한국어로 답변", r / 0.5, round(r, 2)))
    if "caption" in expect:
        caps = [(e.get("meta") or {}).get("caption") or "" for e in figures + tables]
        out.append(_check("caption", "캡션 연결", float(any(expect["caption"] in c for c in caps)), caps))
    return out
