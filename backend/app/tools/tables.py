"""Tidy table Markdown from the PDF engines before chunking.

Tables without horizontal rules (statistics tables in Korean government reports, for example) come out of the
engines' table finders with several rows stacked in one cell, joined by <br>:

    |2019년<br>2020년<br>2021년|302,676<br>272,337<br>260,562|295,110<br>304,948<br>317,680|

so the year and its values are no longer on one line and a chunk split by rows loses the pairing. `tidy` puts such
rows back (one row per line) when the stacking is unambiguous: at least two cells have the same number of lines, at
least one of them holds only numbers, and every other non-empty cell has one line (it is repeated, like a merged
label). Engine placeholder headers (`Col1`, `Col2` ... for empty header cells) take the name of the header cell on
their left (a spanning group header) or stay empty, and when the header was such a placeholder row, a following row
of plain labels (no numbers) is folded into it, so the repeated header of every table chunk names the columns.
"""

import re

_SPLIT = re.compile(r"(?<!\\)\|")
_SEP = re.compile(r"^\s*:?-{3,}:?\s*$")
_PLACEHOLDER = re.compile(r"^Col\d+$")
_NUMBER = re.compile(r"^[-–−+]?\(?[\d,.]+\)?%?p?$")
_BR = re.compile(r"<br\s*/?>", re.I)


def _cells(line: str) -> list[str]:
    parts = _SPLIT.split(line.strip())
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return [p.strip() for p in parts]


def _line(cells: list[str]) -> str:
    return "|" + "|".join(cells) + "|"


def _numeric(s: str) -> bool:
    return bool(_NUMBER.match(s.replace(" ", "")))


def _unstack(row: list[str]) -> list[list[str]] | None:
    pieces = [[p.strip() for p in _BR.split(c)] if c else [] for c in row]
    counts = {len(p) for p in pieces if len(p) > 1}
    if len(counts) != 1:
        return None
    k = counts.pop()
    stacked = [p for p in pieces if len(p) == k]
    if len(stacked) < 2 or not any(all(_numeric(x) for x in p if x) and any(p) for p in stacked):
        return None
    if any(len(p) not in (0, 1, k) for p in pieces):
        return None
    return [[p[i] if len(p) == k else (p[0] if p else "") for p in pieces] for i in range(k)]


def _tidy_block(lines: list[str], info: dict) -> list[str]:
    rows = [_cells(x) for x in lines]
    sep = next((i for i, r in enumerate(rows) if r and all(_SEP.match(c) for c in r)), None)
    if sep is None or sep == 0:
        return lines
    header, data = rows[0], rows[sep + 1:]
    placeholders = 0
    for j, h in enumerate(header):
        if _PLACEHOLDER.match(h):
            header[j] = header[j - 1] if j and header[j - 1] else ""
            placeholders += 1
    out: list[list[str]] = []
    splits = 0
    for r in data:
        split = _unstack(r)
        if split:
            splits += 1
            info["rows_split"] += 1
            info["rows_added"] += len(split) - 1
            out += split
        else:
            out.append(r)
    if not (splits or placeholders):
        return lines  # nothing to change: keep the engine's text as it is
    if placeholders and out:
        first = out[0]
        filled = [c for c in first if c]
        if filled and len(filled) * 2 >= len(first) and not any(_numeric(_BR.sub(" ", c)) for c in filled):
            header = [" ".join(dict.fromkeys(x for x in (h, _BR.sub(" ", c)) if x)) for h, c in
                      zip(header + [""] * (len(first) - len(header)), first + [""] * (len(header) - len(first)))]
            out = out[1:]
            info["header_rows_merged"] += 1
    info["placeholder_headers"] += placeholders
    width = max([len(header)] + [len(r) for r in out])
    return [_line(header + [""] * (width - len(header))), "|" + "---|" * width] + \
           [_line(r + [""] * (width - len(r))) for r in out]


def tidy(markdown: str) -> tuple[str, dict]:
    """The Markdown with every table block tidied, and what changed (counts)."""
    info = {"rows_split": 0, "rows_added": 0, "placeholder_headers": 0, "header_rows_merged": 0}
    lines = markdown.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            out += _tidy_block(lines[i:j], info)
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out), info
