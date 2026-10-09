"""PDF reading for the local engine, on permissive libraries only: pdfplumber / pdfminer.six parse a page (text
lines with font sizes, images, vector paths, tables), pypdfium2 (PDFium) opens, counts, decrypts and renders.

Every bbox is in PDF points with a top-left origin, relative to the crop box and after /Rotate: the same space
as the rendered page image, and the same as ToolPDF's.
"""

import io
import logging
import threading
from collections import Counter

import pdfplumber
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from pdfminer.layout import LTChar, LTContainer, LTCurve, LTImage, LTTextBox, LTTextLine
from PIL import Image, ImageDraw

from ..base import PasswordError

# boxes_flow=None: no reading-order analysis (blocks are sorted here); all_texts: also text inside form XObjects.
# line_margin 0.8 (pdfminer: 0.5) groups a paragraph's lines into one block about as often as ToolPDF does on the
# sample documents. char_margin stays 2.0: at 3 and more, two text columns 11-17 pt apart become one line.
LAPARAMS = {"all_texts": True, "boxes_flow": None, "line_margin": 0.8}
LINE_STRATEGIES = {"lines", "lines_strict"}
PDFIUM = threading.Lock()  # PDFium is not thread-safe: every call into it in this process runs under this lock
# pdfminer warns once per glyph run about harmless font quirks (e.g. a missing FontBBox); real PDFs flood the log.
logging.getLogger("pdfminer").setLevel(logging.ERROR)

HIGHLIGHT_STROKE = (237, 115, 13, 230)
HIGHLIGHT_FILL = (255, 209, 64, 46)


def _area(r) -> float:
    return max(0.0, (r[2] - r[0])) * max(0.0, (r[3] - r[1]))


def _clip(bbox, rect) -> list[float]:
    return [max(bbox[0], rect[0]), max(bbox[1], rect[1]), min(bbox[2], rect[2]), min(bbox[3], rect[3])]


def _r(b) -> list[float]:
    return [round(float(v), 1) for v in b]


def inside(inner, outer, tol: float = 2.0) -> bool:
    return inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol and inner[2] <= outer[2] + tol and inner[3] <= outer[3] + tol


# ---------- document ----------

def _is_password_error(e: Exception) -> bool:
    return "password" in str(e).lower()


def open_pdfium(path, password: str | None) -> pdfium.PdfDocument:
    """Call under PDFIUM. A missing or wrong password is PasswordError."""
    try:
        return pdfium.PdfDocument(str(path), password=password or None)
    except pdfium.PdfiumError as e:
        if _is_password_error(e):
            raise PasswordError("wrong password" if password else "missing password") from e
        raise


def needs_password(path) -> bool:
    with PDFIUM:
        try:
            pdfium.PdfDocument(str(path)).close()
        except pdfium.PdfiumError as e:
            if _is_password_error(e):
                return True
            raise
    return False


def info(path, password: str | None) -> dict:
    encrypted = needs_password(path)
    if encrypted and not password:
        return {"encrypted": True, "page_count": None, "pages": []}
    with PDFIUM:
        doc = open_pdfium(path, password)
        try:
            pages = []
            for i in range(len(doc)):
                w, h = doc.get_page_size(i)
                pages.append([round(w, 1), round(h, 1)])
        finally:
            doc.close()
    return {"encrypted": encrypted, "page_count": len(pages), "pages": pages}


def sample_text(path, limit: int, password: str | None) -> str:
    """Plain text from the first pages."""
    out, n = [], 0
    with PDFIUM:
        doc = open_pdfium(path, password)
        try:
            for i in range(len(doc)):
                page = doc[i]
                tp = page.get_textpage()
                t = tp.get_text_bounded().replace("\r\n", "\n").replace("\r", "\n").strip()
                tp.close()
                page.close()
                if t:
                    out.append(t)
                    n += len(t)
                if n >= limit:
                    break
        finally:
            doc.close()
    return "\n".join(out)[:limit]


# ---------- tables ----------

class Table:
    """A table found on the page: bbox and cell rows (None for a cell covered by a merged one)."""

    def __init__(self, bbox: list[float], rows: list[list]):
        self.bbox, self.rows = bbox, rows

    def empty_cell_ratio(self) -> float:
        cells = [c for row in self.rows for c in row]
        if not cells:
            return 1.0
        return round(sum(1 for c in cells if c is None or not str(c).strip()) / len(cells), 3)

    def to_markdown(self, clean: bool = False, fill_empty: bool = True) -> str:
        width = max(len(r) for r in self.rows)
        rows = [list(r) + [None] * (width - len(r)) for r in self.rows]
        if fill_empty:  # a merged cell's value fills the cells it covers: from the left, else from above
            for i, row in enumerate(rows):
                for j, c in enumerate(row):
                    if c is None:
                        row[j] = row[j - 1] if j and row[j - 1] is not None else rows[i - 1][j] if i else None

        def cell(c) -> str:
            s = ("" if c is None else str(c)).strip()
            if clean:
                for ch in "\\`*_{}[]()#+-.!~>":
                    s = s.replace(ch, "\\" + ch)
            return s.replace("\n", "<br>").replace("|", "\\|")

        lines = ["|" + "|".join(cell(c) for c in r) + "|" for r in rows]
        lines.insert(1, "|" + "---|" * width)
        return "\n".join(lines) + "\n\n"


def _table_settings(t: dict) -> dict:
    """Table options (ToolPDF names) -> pdfplumber table settings; the names are pdfplumber's own."""
    return {"vertical_strategy": t["vertical_strategy"] or t["strategy"],
            "horizontal_strategy": t["horizontal_strategy"] or t["strategy"],
            "snap_tolerance": t["snap_tolerance"], "join_tolerance": t["join_tolerance"],
            "edge_min_length": t["edge_min_length"], "intersection_tolerance": t["intersection_tolerance"],
            "text_x_tolerance": t["text_tolerance"], "text_y_tolerance": t["text_tolerance"],
            "min_words_vertical": t["min_words_vertical"], "min_words_horizontal": t["min_words_horizontal"]}


def needs_drawings(t: dict) -> bool:
    """Line strategies find nothing on a page without drawings, so the caller's drawing count may skip them."""
    return {t["vertical_strategy"] or t["strategy"], t["horizontal_strategy"] or t["strategy"]} <= LINE_STRATEGIES


def _open_side_edges(edges: list[dict], max_row_gap: float = 400) -> list[dict]:
    """Virtual left/right borders for open-sided tables (common in Korean government reports): horizontal rules
    span the full table width but the outer vertical borders are not drawn, so line strategies drop the first and
    last columns. Neighbouring rules with the same ends get a border at each end, but only where a real vertical
    rule lies between them (evidence of a grid, so plain separator lines do not become tables)."""
    hs = [e for e in edges if e["orientation"] == "h" and e["width"] >= 20]
    vs = [e for e in edges if e["orientation"] == "v"]
    groups: dict[tuple, list[dict]] = {}
    for e in hs:
        groups.setdefault((round(e["x0"] / 2), round(e["x1"] / 2)), []).append(e)
    out = []
    for rules in groups.values():
        rules.sort(key=lambda e: e["top"])
        x0, x1 = min(e["x0"] for e in rules), max(e["x1"] for e in rules)
        for a, b in zip(rules, rules[1:]):
            top, bottom = a["top"], b["top"]
            if not 2 < bottom - top <= max_row_gap:
                continue
            if not any(x0 + 2 < v["x0"] < x1 - 2 and v["top"] < bottom - 1 and v["bottom"] > top + 1 for v in vs):
                continue
            for x in (x0, x1):
                out.append({"object_type": "virtual_edge", "orientation": "v", "x0": x, "x1": x, "top": top,
                            "bottom": bottom, "doctop": a["doctop"], "width": 0, "height": bottom - top})
    return out


# ---------- page ----------

class Page:
    """One parsed page: text blocks with per-line font sizes, image boxes and vector paths."""

    def __init__(self, pp):
        self._pp = pp
        cx0, ctop, cx1, cbottom = pp.cropbox
        self.rect = [0.0, 0.0, float(cx1 - cx0), float(cbottom - ctop)]
        # pdfminer coordinates (bottom-left, mediabox based) -> top-left, crop box based.
        self._dx = float(pp.mediabox[0] - cx0)
        self._dy = float(pp.mediabox[1] - ctop)
        self._h = float(pp.height)
        self.blocks: list[dict] = []
        self.images: list[list[float]] = []
        self.drawings: list[list[float]] = []
        self._walk(pp.layout)

    def _box(self, o) -> list[float]:
        return [o.x0 + self._dx, self._h - o.y1 + self._dy, o.x1 + self._dx, self._h - o.y0 + self._dy]

    def _walk(self, container) -> None:
        for o in container:
            if isinstance(o, LTTextBox):
                self._block(o, list(o))
            elif isinstance(o, LTTextLine):
                self._block(o, [o])
            elif isinstance(o, LTImage):
                self.images.append(self._box(o))
            elif isinstance(o, LTCurve):  # LTLine and LTRect are curves too
                self.drawings.append(self._box(o))
            elif isinstance(o, LTContainer):  # LTFigure (form XObject)
                self._walk(o)

    def _block(self, box, lines) -> None:
        out = []
        for line in lines:
            text = line.get_text().strip()
            sizes = [c.size for c in line if isinstance(c, LTChar) and c.get_text().strip()]
            if text and sizes:
                out.append({"bbox": self._box(line), "text": text, "size": min(sizes), "sizes": sizes})
        if out:
            self.blocks.append({"bbox": self._box(box), "lines": out})

    def tables(self, topts: dict) -> list[Table]:
        """Tables by the table options. A single cell, row or column is a box, and a grid without any text (chart
        gridlines) is a figure, not a table."""
        if not topts["enabled"] or (not self.drawings and needs_drawings(topts)):
            return []
        settings = _table_settings(topts)
        if settings["vertical_strategy"] in LINE_STRATEGIES and (sides := _open_side_edges(self._pp.edges)):
            settings["explicit_vertical_lines"] = sides
        out = []
        cx0, ctop = self._pp.cropbox[:2]
        for t in self._pp.find_tables(settings):
            rows = t.extract(x_tolerance=topts["text_tolerance"], y_tolerance=topts["text_tolerance"])
            if len(rows) < 2 or max(len(r) for r in rows) < 2:
                continue
            if not any(c and str(c).strip() for r in rows for c in r):  # a grid without text: chart gridlines
                continue
            x0, top, x1, bottom = t.bbox
            out.append(Table([x0 - cx0, top - ctop, x1 - cx0, bottom - ctop], rows))
        return out

    def close(self) -> None:
        self._pp.close()


def _reading_key(block: dict) -> tuple:
    return (round(block["bbox"][1]), block["bbox"][0])


def open_plumber(path, password: str | None):
    try:
        return pdfplumber.open(str(path), password=password or "", laparams=LAPARAMS)
    except Exception as e:
        if "password" in type(e).__name__.lower() or _is_password_error(e):
            raise PasswordError("wrong password" if password else "missing password") from e
        raise


# ---------- profiling ----------

def path_count(doc: pdfium.PdfDocument, page: int) -> int:
    """Painted vector paths on the page, form XObjects included. PDFium keeps a path with several subpaths as one
    object (pdfminer splits it), so this counts like PyMuPDF's get_drawings(), which the `drawings` thresholds of
    the rules were set with."""
    with PDFIUM:
        pg = doc[page]
        try:
            return sum(1 for _ in pg.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_PATH], max_depth=15))
        finally:
            pg.close()


def page_features(page: Page, topts: dict, drawings: int) -> dict:
    rect = page.rect
    page_area = _area(rect) or 1.0
    found = page.tables(topts)
    table_boxes = [t.bbox for t in found]
    table_area = sum(_area(_clip(b, rect)) for b in table_boxes)

    text_chars = table_chars = 0
    text_area = 0.0
    size_hist: Counter = Counter()
    for block in page.blocks:
        text_area += _area(_clip(block["bbox"], rect))
        for line in block["lines"]:
            n = len(line["text"])
            text_chars += n
            for s in line["sizes"]:
                size_hist[str(round(s, 1))] += 1
            if any(inside(line["bbox"], b) for b in table_boxes):
                table_chars += n
    image_area = sum(_area(_clip(b, rect)) for b in page.images)
    return {
        "text_chars": text_chars,
        "text_area_ratio": round(min(text_area / page_area, 1.0), 3),
        "images": len(page.images),
        "image_area_ratio": round(min(image_area / page_area, 1.0), 3),
        "drawings": drawings,
        "tables": len(found),
        "table_area_ratio": round(min(table_area / page_area, 1.0), 3),
        # Share of the page's text inside tables: a small table with little text around it still dominates the page.
        "table_text_share": round(table_chars / text_chars, 3) if text_chars else 0.0,
        "size_hist": dict(size_hist),
    }


def profile_pages(path, pages: list[int] | None, topts: dict, password: str | None) -> list[dict]:
    with PDFIUM:
        doc = open_pdfium(path, password)
    try:
        with open_plumber(path, password) as pdf:
            todo = range(len(pdf.pages)) if pages is None else pages
            out = []
            for i in todo:
                if not 0 <= i < len(pdf.pages):
                    raise IndexError(i)
                pg = Page(pdf.pages[i])
                try:
                    out.append({"page": i, "features": page_features(pg, topts, path_count(doc, i))})
                finally:
                    pg.close()
            return out
    finally:
        with PDFIUM:
            doc.close()


# ---------- extraction ----------

def extract_text_elements(page: Page, heading_min_size: float | None) -> list[dict]:
    """Text blocks in reading order, split where lines switch between heading and body size (layout analysis
    often glues a heading to the paragraph next to it), between headings of different sizes and between headings
    set apart (a document title above its first section heading). Heading-size runs up to 200 chars are titles."""
    out = []
    for block in sorted(page.blocks, key=_reading_key):
        groups: list[list] = []  # [is_heading, lines, bbox, size]
        for line in block["lines"]:
            head = heading_min_size is not None and line["size"] >= heading_min_size
            lb = line["bbox"]
            g = groups[-1] if groups else None
            # a heading line of another size, or one set apart by more than a wrapped line's gap, starts a new title
            new_title = g is not None and head and (abs(g[3] - line["size"]) > 0.5 or lb[1] - g[2][3] > 0.5 * line["size"])
            if g is not None and g[0] == head and not new_title:
                g[1].append(line["text"])
                g[2] = [min(g[2][0], lb[0]), min(g[2][1], lb[1]), max(g[2][2], lb[2]), max(g[2][3], lb[3])]
            else:
                groups.append([head, [line["text"]], list(lb), line["size"]])
        for head, lines, bbox, _ in groups:
            text = "\n".join(lines)
            out.append({"type": "title" if head and len(text) <= 200 else "text", "bbox": _r(bbox), "content": text})
    return out


def _union(a, b) -> list[float]:
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _overlap_ratio(a, b) -> float:
    """Share of a covered by b."""
    return _area(_clip(a, b)) / (_area(a) or 1.0)


def cluster_drawings(page: Page, tol: float = 3.0) -> list[list[float]]:
    """Bounding boxes of vector paths lying within tol points of each other (chained), for paths inside the page.
    Clusters no wider or taller than tol (rules, underlines) are dropped."""
    rect = page.rect
    clusters: list[list[float]] = []
    for b in sorted((d for d in page.drawings if d[0] >= rect[0] and d[1] >= rect[1] and d[2] <= rect[2] and d[3] <= rect[3]),
                    key=lambda d: (d[3], d[0])):
        b = list(b)
        merged = True
        while merged:  # a new box can join clusters that were apart until now
            merged = False
            for i, c in enumerate(clusters):
                if not (c[2] < b[0] - tol or c[0] > b[2] + tol or c[3] < b[1] - tol or c[1] > b[3] + tol):
                    b = _union(c, b)
                    clusters.pop(i)
                    merged = True
                    break
        clusters.append(b)
    return [c for c in clusters if c[2] - c[0] > tol and c[3] - c[1] > tol]


def figure_regions(page: Page, table_bboxes: list[list[float]], min_area_ratio: float, max_regions: int) -> list[dict]:
    """Embedded images and vector-drawing clusters large enough to be figures, merged when they overlap.
    Drawing clusters that are table ruling lines are dropped."""
    rect = page.rect
    page_area = _area(rect) or 1.0
    cands: list[dict] = []
    for img in page.images:
        b = _clip(img, rect)
        if _area(b) / page_area >= min_area_ratio:
            cands.append({"bbox": b, "source": "image"})
    for r in cluster_drawings(page):
        b = _clip(r, rect)
        if _area(b) / page_area < min_area_ratio or any(_overlap_ratio(b, t) > 0.5 for t in table_bboxes):
            continue
        cands.append({"bbox": b, "source": "drawing"})

    merged: list[dict] = []
    for c in sorted(cands, key=lambda c: -_area(c["bbox"])):
        for m in merged:
            if _area(_clip(m["bbox"], c["bbox"])) > 0:
                m["bbox"] = _union(m["bbox"], c["bbox"])
                if c["source"] not in m["source"]:
                    m["source"] += "+" + c["source"]
                break
        else:
            merged.append(dict(c))
    merged = merged[:max_regions]
    for m in merged:
        m["bbox"] = _r(m["bbox"])
        m["area_ratio"] = round(_area(m["bbox"]) / page_area, 3)
    return sorted(merged, key=lambda m: (m["bbox"][1], m["bbox"][0]))


# ---------- rendering ----------

class Renderer:
    """Page images from PDFium, one bitmap per (page, dpi) reused for every crop of that page."""

    def __init__(self, doc: pdfium.PdfDocument, popts: dict):
        self.doc, self.popts = doc, popts
        self._cache: dict[tuple, Image.Image] = {}

    def page_image(self, page: int, dpi: int, highlight: list[list[float]] | None = None) -> Image.Image:
        key = (page, dpi)
        if highlight or key not in self._cache:
            annots = self.popts["annots"]
            with PDFIUM:
                pg = self.doc[page]
                try:
                    img = pg.render(scale=dpi / 72, draw_annots=annots, may_draw_forms=annots).to_pil()
                finally:
                    pg.close()
            img = img.convert("L" if self.popts["colorspace"] == "gray" else "RGB")
            if highlight:
                return _highlight(img, highlight, dpi)
            self._cache = {key: img}  # only the current page stays
        return self._cache[key]

    def clip(self, page: int, rect: list[float], bbox: list[float], dpi: int, fmt: str, pad: float = 0,
             highlight: list[list[float]] | None = None) -> bytes:
        box = _clip([bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad], rect)
        img = self.page_image(page, dpi, highlight)
        s = dpi / 72
        crop = img.crop((int(box[0] * s), int(box[1] * s), max(int(box[0] * s) + 1, round(box[2] * s)),
                         max(int(box[1] * s) + 1, round(box[3] * s))))
        return encode(crop, fmt, self.popts)

    def full(self, page: int, dpi: int, fmt: str, highlight: list[list[float]] | None = None) -> bytes:
        return encode(self.page_image(page, dpi, highlight), fmt, self.popts)


def _highlight(img: Image.Image, boxes: list[list[float]], dpi: int) -> Image.Image:
    s = dpi / 72
    w, h = img.size
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(over)
    for b in boxes:
        x0, y0, x1, y1 = (b[0] - 3) * s, (b[1] - 3) * s, (b[2] + 3) * s, (b[3] + 3) * s
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w - 1, x1), min(h - 1, y1)
        if x1 > x0 and y1 > y0:
            draw.rectangle((x0, y0, x1, y1), fill=HIGHLIGHT_FILL, outline=HIGHLIGHT_STROKE, width=max(1, round(2 * s)))
    mode = img.mode
    return Image.alpha_composite(img.convert("RGBA"), over).convert(mode)


def encode(img: Image.Image, fmt: str, popts: dict) -> bytes:
    buf = io.BytesIO()
    if fmt == "jpeg":
        img.save(buf, "JPEG", quality=popts["jpeg_quality"])
    else:
        img.save(buf, "PNG")
    return buf.getvalue()


def page_rect(doc: pdfium.PdfDocument, page: int) -> list[float]:
    with PDFIUM:
        if not 0 <= page < len(doc):
            raise IndexError(page)
        w, h = doc.get_page_size(page)
    return [0.0, 0.0, float(w), float(h)]


def render(path, page: int, dpi: int, fmt: str, clip, pad: float, highlight, popts: dict, password: str | None) -> bytes:
    with PDFIUM:
        doc = open_pdfium(path, password)
    try:
        r = Renderer(doc, popts)
        rect = page_rect(doc, page)
        if clip is not None:
            return r.clip(page, rect, clip, dpi, fmt, pad, highlight)
        return r.full(page, dpi, fmt, highlight)
    finally:
        with PDFIUM:
            doc.close()


def prepare_window(path, pages: list[dict], heading_min: float | None, figures: dict, topts: dict, iopts: dict,
                   password: str | None) -> dict[int, dict]:
    """Per page: text-layer elements, OCR fallback text, figure regions and image crops for a recognizer
    (OCR, table, figure). A "table" crop names the table it may replace by its index in "elements"."""
    fmt, crops_on, pad = iopts["format"], iopts["crops"], iopts["crop_pad"]
    out: dict[int, dict] = {}
    with PDFIUM:
        doc = open_pdfium(path, password)
    try:
        renderer = Renderer(doc, iopts)
        with open_plumber(path, password) as pdf:
            for spec in pages:
                p, mode, drawings = spec["page"], spec.get("mode", "text"), spec.get("drawings")
                if not 0 <= p < len(pdf.pages):
                    raise IndexError(p)
                pg = Page(pdf.pages[p])
                try:
                    out[p] = _prepare_page(pg, p, mode, drawings, renderer, heading_min, figures, topts, fmt, crops_on, pad, iopts)
                finally:
                    pg.close()
    finally:
        with PDFIUM:
            doc.close()
    return out


def _prepare_page(pg: Page, p: int, mode: str, drawings, renderer: Renderer, heading_min, figures: dict, topts: dict,
                  fmt: str, crops_on: bool, pad: float, iopts: dict) -> dict:
    rect = _r(pg.rect)
    prep = {"rect": rect, "elements": [], "fallback": [], "crops": [], "regions": [], "skipped_regions": 0}
    text_els = [{**e, "source_tool": "pymupdf_text"} for e in extract_text_elements(pg, heading_min)]

    if mode == "ocr":
        prep["fallback"] = text_els
        prep["crops"].append({"kind": "ocr", "bbox": rect, "image": renderer.clip(p, rect, rect, iopts["render_dpi"], fmt)})
        return prep

    tables, table_crops = [], []
    # The caller's drawing count may skip the slow table finder, as with ToolPDF; the page's own count decides otherwise.
    found = [] if drawings == 0 and needs_drawings(topts) else pg.tables(topts)
    for t in found:
        el = {"type": "table", "bbox": _r(t.bbox), "source_tool": "pymupdf_tables",
              "content": t.to_markdown(clean=topts["markdown_clean"], fill_empty=topts["markdown_fill_empty"]),
              "meta": {"empty_cell_ratio": t.empty_cell_ratio()}}
        if crops_on and el["meta"]["empty_cell_ratio"] > topts["crop_empty_ratio"]:
            image = renderer.clip(p, rect, el["bbox"], iopts["crop_dpi"], fmt, pad)
            table_crops.append((len(tables), {"kind": "table", "bbox": el["bbox"], "image": image}))
        tables.append(el)
    table_boxes = [t["bbox"] for t in tables]
    kept = [e for e in text_els if not any(inside(e["bbox"], b) for b in table_boxes)]
    prep["elements"] = kept + tables
    for i, job in table_crops:
        prep["crops"].append({**job, "target": len(kept) + i})

    if mode == "figures" or figures["on_all_pages"]:
        regions = figure_regions(pg, table_boxes, figures["min_area_ratio"], figures["max_per_page"])
        if mode == "figures" and not regions:
            regions = [{"bbox": rect, "source": "page", "area_ratio": 1.0}]
        prep["regions"] = regions
        if crops_on:
            for r in regions:
                prep["crops"].append({"kind": "figure", "bbox": r["bbox"], "region": r,
                                      "image": renderer.clip(p, rect, r["bbox"], iopts["crop_dpi"], fmt, pad)})
        else:
            prep["skipped_regions"] = len(regions)
    return prep
