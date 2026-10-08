"""Write small PDFs for tests without a PDF library: pages with Helvetica text (Latin only) and straight lines."""

from pathlib import Path


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_pdf(path: Path, pages: list[dict]) -> Path:
    """pages: [{"size": (w, h), "text": [(x, y_from_top, size, "text")], "lines": [(x0, y0, x1, y1)]}].
    Coordinates are points with the origin at the top left, like the rest of the app."""
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    pages_id = len(objs) + 1 + 2 * len(pages)  # reserved after every page and its content stream
    kids = []
    for pg in pages:
        w, h = pg.get("size", (595, 842))
        ops = ["0.6 w"]
        for x0, y0, x1, y1 in pg.get("lines", []):
            ops.append(f"{x0} {h - y0} m {x1} {h - y1} l S")
        for x, y, size, text in pg.get("text", []):
            ops.append(f"BT /F1 {size} Tf {x} {h - y} Td ({_esc(text)}) Tj ET")
        stream = "\n".join(ops).encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %s %s] /Contents %d 0 R "
                        b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (pages_id, str(w).encode(), str(h).encode(), content, font)))
    assert add(b"<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join(f"{k} 0 R" for k in kids).encode(), len(kids))) == pages_id
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, catalog, xref)
    path = Path(path)
    path.write_bytes(bytes(out))
    return path


def one_line_pdf(path: Path, text: str, size: float = 12) -> Path:
    return write_pdf(path, [{"text": [(72, 80, size, text)]}])
