"""Captions: move a caption next to a figure or table into that element. Figure regions and crops come from the PDF engine."""

import re


def attach_captions(elements: list[dict], pattern: str, max_gap: float) -> list[dict]:
    """Move a caption-looking text block next to a figure/table into that element. Returns the new list."""
    rx = re.compile(pattern, re.I)
    targets = [e for e in elements if e["type"] in ("figure", "table")]
    used: set[int] = set()
    for t in targets:
        tb = t["bbox"]
        best, best_gap = None, max_gap + 1
        for i, e in enumerate(elements):
            if i in used or e["type"] not in ("text", "title") or not rx.match(e["content"].strip()):
                continue
            eb = e["bbox"]
            if min(eb[2], tb[2]) - max(eb[0], tb[0]) <= 0:  # no horizontal overlap
                continue
            gap = eb[1] - tb[3] if eb[1] >= tb[3] else tb[1] - eb[3]
            if -2 <= gap < best_gap:
                best, best_gap = i, gap
        if best is not None:
            used.add(best)
            caption = elements[best]["content"].strip()
            t.setdefault("meta", {})["caption"] = caption
            t["content"] = f"**{caption}**\n\n{t['content']}"
    return [e for i, e in enumerate(elements) if i not in used]
