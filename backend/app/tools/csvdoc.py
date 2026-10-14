"""CSV/TSV as a table: parsed, judged, and written as a one-sheet xlsx so the engine's native spreadsheet renderer
draws it (header repeated on every page). Every chunk then carries the column names, which plain text loses after
the first lines. A file that is not really a table (too many columns, ragged rows) stays plain text."""

import csv
import io
from collections import Counter
from pathlib import Path

DELIMITERS = ",;\t|"
CONSISTENT_SHARE = 0.9  # rows with the most common column count; below this the file is not a table
SHEET_BAD = str.maketrans({c: "_" for c in "[]:*?/\\"})


def read_rows(src: Path, encoding: str, max_rows: int) -> tuple[list[list[str]], str, bool]:
    """Rows (at most max_rows + 1, header included), the delimiter, and whether more rows were left out."""
    text = Path(src).read_bytes().decode(encoding, errors="replace")
    if Path(src).suffix.lower() == ".tsv":
        delim = "\t"
    else:
        try:
            delim = csv.Sniffer().sniff(text[:20000], delimiters=DELIMITERS).delimiter
        except csv.Error:
            delim = ","
    rows, truncated = [], False
    for row in csv.reader(io.StringIO(text), delimiter=delim):
        if not any(c.strip() for c in row):
            continue
        if len(rows) > max_rows:
            truncated = True
            break
        rows.append(row)
    return rows, delim, truncated


def judge(rows: list[list[str]], max_columns: int) -> tuple[bool, dict]:
    """(is a table, evidence). A table has a header and data rows, at least 2 and at most max_columns columns,
    and nearly every row has the same number of cells."""
    counts = Counter(len(r) for r in rows)
    cols, n = (counts.most_common(1)[0] if counts else (0, 0))
    share = round(n / len(rows), 3) if rows else 0.0
    evidence = {"rows": len(rows), "columns": cols, "consistent_share": share, "max_columns": max_columns}
    if len(rows) < 2:
        return False, {**evidence, "reason": "fewer than 2 rows"}
    if cols < 2:
        return False, {**evidence, "reason": "a single column"}
    if cols > max_columns:
        return False, {**evidence, "reason": f"{cols} columns > {max_columns}: too narrow to draw as a table"}
    if share < CONSISTENT_SHARE:
        return False, {**evidence, "reason": f"only {share:.0%} of rows have {cols} cells (ragged, not a table)"}
    return True, evidence


def write_xlsx(rows: list[list[str]], out: Path, sheet: str) -> Path:
    """Cells are written as text so values keep their form (leading zeros, dates as written)."""
    import openpyxl

    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet(title=(sheet.translate(SHEET_BAD) or "Sheet1")[:31])
    width = max(len(r) for r in rows)
    for r in rows:
        ws.append([c for c in r] + [""] * (width - len(r)))
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out
