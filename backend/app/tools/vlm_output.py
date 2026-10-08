"""Turn VLM Markdown answers into elements."""

import re

FIGURE_TYPES = {"chart", "diagram", "photo", "table", "text"}
_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n(.*?)\n```\s*$", re.S)
_TYPE = re.compile(r"^\s*\**TYPE\**\s*[:：]\s*\**\s*([a-zA-Z_]+)", re.I)


def strip_fences(md: str) -> str:
    md = md.strip()
    m = _FENCE.match(md)
    return m.group(1).strip() if m else md


def parse_figure(md: str) -> tuple[str, str]:
    """First line is 'TYPE: <kind>' by prompt contract. Unknown or missing -> 'diagram'."""
    md = strip_fences(md)
    first, _, rest = md.partition("\n")
    m = _TYPE.match(first)
    if not m:
        return "diagram", md
    kind = m.group(1).lower()
    return (kind if kind in FIGURE_TYPES else "diagram"), rest.strip()


def md_to_elements(md: str, bbox: list[float], source_tool: str) -> list[dict]:
    """Split a Markdown transcription into title / table / text elements so section chunking still works.
    Positions inside the page are unknown, so every element carries the page bbox."""
    out: list[dict] = []
    para: list[str] = []
    table: list[str] = []

    def flush_para():
        if para:
            out.append({"type": "text", "bbox": bbox, "content": "\n".join(para).strip(), "source_tool": source_tool})
            para.clear()

    def flush_table():
        if table:
            out.append({"type": "table", "bbox": bbox, "content": "\n".join(table), "source_tool": source_tool})
            table.clear()

    for line in strip_fences(md).splitlines():
        s = line.strip()
        if s.startswith("|"):
            flush_para()
            table.append(s)
            continue
        flush_table()
        if s.startswith("#"):
            flush_para()
            title = s.lstrip("#").strip()
            if title:
                out.append({"type": "title", "bbox": bbox, "content": title, "source_tool": source_tool})
        elif not s:
            flush_para()
        else:
            para.append(s)
    flush_para()
    flush_table()
    return [e for e in out if e["content"]]
