"""Plain text files (.txt, .log, files without an extension): sniff, decode and render as PDF pages.

Like every other format, text becomes PDF so profiling, parsing, page images and bbox overlays work the same way.
The PDF is written here with ReportLab (permissive, the same writer the local engine uses), so it works with either
PDF engine; the engine then reads it like any PDF. Lines are kept as they are (logs depend on them); long lines wrap.
"""

import codecs
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from ..engines.local.pdfgen import A4, cjk_font

SNIFF_BYTES = 64 * 1024
BOMS = ((codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16"))
# Tried in order when there is no BOM. cp949 covers EUC-KR; latin-1 never fails, so it is only a last resort.
ENCODINGS = ("utf-8", "cp949")
MARGIN = 40


def _printable_share(text: str) -> float:
    if not text:
        return 1.0
    ok = sum(1 for c in text if c.isprintable() or c in "\n\r\t\f")
    return ok / len(text)


def sniff(path: Path) -> str | None:
    """The encoding if the file looks like text, else None. Reads the first 64 KB."""
    with open(path, "rb") as f:
        head = f.read(SNIFF_BYTES)
    if not head:
        return None
    for bom, enc in BOMS:
        if head.startswith(bom):
            return enc
    if b"\x00" in head:  # binary (UTF-16 without BOM is not supported)
        return None
    for enc in ENCODINGS:
        try:
            # A multi-byte character may be cut at the 64 KB boundary: ignore up to 3 trailing bytes.
            text = head.decode(enc) if len(head) < SNIFF_BYTES else _decode_cut(head, enc)
        except UnicodeDecodeError:
            continue
        if _printable_share(text) >= 0.95:
            return enc
    return None


def _decode_cut(data: bytes, enc: str) -> str:
    for cut in range(4):
        try:
            return data[:len(data) - cut].decode(enc)
        except UnicodeDecodeError:
            if cut == 3:
                raise
    raise AssertionError


def _wrap(line: str, font: str, size: float, width: float) -> list[str]:
    """Break a line that is wider than the page by characters (logs have no reliable word boundaries)."""
    if pdfmetrics.stringWidth(line, font, size) <= width:
        return [line]
    out, cur, cur_w = [], "", 0.0
    for ch in line:
        w = pdfmetrics.stringWidth(ch, font, size)
        if cur and cur_w + w > width:
            out.append(cur)
            cur, cur_w = "", 0.0
        cur += ch
        cur_w += w
    out.append(cur)
    return out


def text_to_pdf(src: Path, out: Path, encoding: str, font_size: float, max_chars: int, font_path: str = "") -> dict:
    """Render the text file as A4 pages. Returns {encoding, lines, chars, truncated, pages, font}."""
    text = Path(src).read_bytes().decode(encoding, errors="replace")
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n").expandtabs(4)
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()

    font = cjk_font(font_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(out), pagesize=A4, pageCompression=1)
    c.setTitle(Path(src).name)
    width, height = A4[0] - 2 * MARGIN, A4[1]
    leading = font_size * 1.35
    per_page = int((height - 2 * MARGIN) // leading)
    y_index, pages = 0, 1
    c.setFont(font["name"], font_size)
    for line in lines:
        # Control characters other than tab/newline would print as boxes; drop them.
        line = "".join(ch for ch in line if ch.isprintable())
        for part in _wrap(line, font["name"], font_size, width) if line else [""]:
            if y_index == per_page:
                c.showPage()
                c.setFont(font["name"], font_size)
                y_index, pages = 0, pages + 1
            c.drawString(MARGIN, height - MARGIN - font_size - y_index * leading, part)
            y_index += 1
    c.save()
    return {"encoding": encoding, "lines": len(lines), "chars": len(text), "truncated": truncated, "pages": pages,
            "font": font["source"]}
