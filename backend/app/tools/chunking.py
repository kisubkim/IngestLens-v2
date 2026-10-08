"""Structure-aware chunking over parsed elements.

Elements are split into units no longer than the chunk budget, then packed greedily.
Structural boundaries (new section, new page in page mode, tables and figures) close the
current chunk, so every chunk keeps an exact list of source elements for bbox overlays.
"""

import math

# Default mixed Korean/English ratio. The strategy agent replaces it per run with a ratio measured
# by the embedding model's tokenizer (vLLM /tokenize) when that endpoint is available.
CHARS_PER_TOKEN = 2.5

SEPARATORS = ["\n\n", "\n", ". ", "다. ", "? ", "! ", " "]
ATOMIC = {"table", "figure"}


def est_tokens(text: str, chars_per_token: float = CHARS_PER_TOKEN) -> int:
    return max(1, math.ceil(len(text) / chars_per_token))


def split_text(text: str, max_chars: int, seps: list[str] = SEPARATORS) -> list[str]:
    """Recursive split on the coarsest separator that exists; hard cut as last resort."""
    if len(text) <= max_chars:
        return [text]
    for i, sep in enumerate(seps):
        if sep in text:
            parts = [p + sep for p in text.split(sep)[:-1]] + [text.split(sep)[-1]]
            out, cur = [], ""
            for p in parts:
                if len(p) > max_chars:
                    if cur:
                        out.append(cur)
                        cur = ""
                    out.extend(split_text(p, max_chars, seps[i + 1:]))
                elif len(cur) + len(p) > max_chars:
                    out.append(cur)
                    cur = p
                else:
                    cur += p
            if cur:
                out.append(cur)
            return [o for o in out if o.strip()]
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]


def split_table(md: str, max_chars: int) -> list[str]:
    """Split a Markdown table by rows, repeating any caption lines and the header in every piece,
    so each chunk of a long table still says what its columns mean."""
    lines = md.splitlines()
    idx = next((i for i in range(len(lines) - 1)
                if lines[i].lstrip().startswith("|") and "-" in lines[i + 1] and set(lines[i + 1].replace("|", "").strip()) <= set("-: ")), None)
    if idx is None or len(md) <= max_chars:
        return split_text(md, max_chars)
    head = "\n".join(lines[: idx + 2])
    out, cur, size = [], [], len(head)
    for row in lines[idx + 2:]:
        if cur and size + len(row) + 1 > max_chars:
            out.append(head + "\n" + "\n".join(cur))
            cur, size = [], len(head)
        cur.append(row)
        size += len(row) + 1
    if cur:
        out.append(head + "\n" + "\n".join(cur))
    return out


def _size(units: list[tuple[dict, str]]) -> int:
    return sum(len(u) for _, u in units)


def chunk_elements(elements: list[dict], strategy: str, target_tokens: int, overlap_tokens: int,
                   chars_per_token: float = CHARS_PER_TOKEN) -> list[dict]:
    """elements: dicts with page, type, bbox, content, in reading order.
    strategy: "section" | "page" | "recursive".
    Returns chunk dicts: text, tokens, pages, bboxes, section, element_types."""
    max_chars = int(target_tokens * chars_per_token)
    overlap_chars = int(overlap_tokens * chars_per_token)
    chunks: list[dict] = []
    cur: list[tuple[dict, str]] = []
    section: str | None = None

    def emit(units: list[tuple[dict, str]], sec: str | None) -> None:
        text = "\n".join(u for _, u in units).strip()
        if not text:
            return
        seen, bboxes = set(), []
        for el, _ in units:
            key = (el["page"], tuple(el["bbox"]))
            if key not in seen:
                seen.add(key)
                bboxes.append({"page": el["page"], "bbox": el["bbox"]})
        body = text if not sec or text.startswith(sec) else f"{sec}\n{text}"
        chunks.append({
            "text": body,
            "tokens": est_tokens(body, chars_per_token),
            "pages": sorted({el["page"] for el, _ in units}),
            "bboxes": bboxes,
            "section": sec,
            "element_types": sorted({el["type"] for el, _ in units}),
        })

    def close(carry: bool) -> None:
        nonlocal cur
        if not cur:
            return
        emit(cur, section)
        if carry and overlap_chars:
            tail, size = [], 0
            for u in reversed(cur):
                if size + len(u[1]) > overlap_chars:
                    break
                tail.insert(0, u)
                size += len(u[1])
            if not tail:
                # Last unit is longer than the overlap: carry its trailing text, starting at a word boundary.
                el, text = cur[-1]
                cut = text[-overlap_chars:]
                cut = cut[cut.find(" ") + 1:] if " " in cut else cut
                tail = [(el, cut)] if cut.strip() else []
            cur = tail if len(tail) < len(cur) or tail[0][1] != cur[0][1] else []
        else:
            cur = []

    for el in elements:
        content = (el.get("content") or "").strip()
        if not content:
            continue
        if el["type"] == "title":
            if strategy == "section":
                close(carry=False)
            section = content.splitlines()[0][:200]
        if el["type"] in ATOMIC:
            close(carry=False)
            for piece in (split_table if el["type"] == "table" else split_text)(content, max_chars):
                emit([(el, piece)], section)
            continue
        if strategy == "page" and cur and el["page"] != cur[-1][0]["page"]:
            close(carry=False)
        for piece in split_text(content, max_chars):
            if cur and _size(cur) + len(piece) > max_chars:
                close(carry=True)
                if cur and _size(cur) + len(piece) > max_chars:
                    cur = []  # overlap tail + piece would overflow and re-emit the tail alone
            cur.append((el, piece))
    close(carry=False)
    return chunks


def chunk_stats(chunks: list[dict], target_tokens: int) -> dict:
    toks = [c["tokens"] for c in chunks]
    if not toks:
        return {"count": 0}
    edges = [0, 64, 128, 256, 384, 512, 768, 1024, 2048, 10**9]
    hist = [{"lo": lo, "hi": hi, "n": sum(lo <= t < hi for t in toks)} for lo, hi in zip(edges, edges[1:])]
    return {
        "count": len(toks),
        "tokens_min": min(toks),
        "tokens_avg": round(sum(toks) / len(toks), 1),
        "tokens_max": max(toks),
        "too_short": sum(t < target_tokens * 0.2 for t in toks),
        "too_long": sum(t > target_tokens * 1.5 for t in toks),
        "histogram": [h for h in hist if h["n"]],
    }
