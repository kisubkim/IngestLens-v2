"""Writing PDFs with ReportLab: image wrapping and the native Office renderer.

Korean needs a CJK font: the configured one (LocalEngine `cjk_font`), else the first TrueType font found on the
system, else ReportLab's built-in CID font, which is not embedded (text extraction works, but rendering the page
needs a Korean font on the machine that renders it).
"""

import threading
from pathlib import Path

from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

A4 = (595.28, 841.89)
FONT_CANDIDATES = [
    "C:/Windows/Fonts/malgun.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/nanum/NanumGothic.ttf",
    "/usr/share/fonts/naver-nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/unfonts-core/UnDotum.ttf",
    "/usr/share/fonts/truetype/baekmuk/gulim.ttf",
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    "/Library/Fonts/AppleGothic.ttf",
]
CID_FALLBACK = "HYGothic-Medium"
_font: dict | None = None
_lock = threading.Lock()


def cjk_font(configured: str = "") -> dict:
    """Registers the CJK font once per process. Returns {name, source, embedded, rule_id, tried}."""
    global _font
    with _lock:
        if _font is not None:
            return _font
        tried = []
        configured = (configured or "").strip()
        for path in ([configured] if configured else []) + FONT_CANDIDATES:
            if not Path(path).is_file():
                continue
            try:
                # TrueType outlines only: ReportLab cannot embed CFF-based .otf fonts (e.g. Noto Sans CJK).
                pdfmetrics.registerFont(TTFont("cjk", path))
            except Exception as e:  # unsupported font file: try the next one
                tried.append({"path": path, "error": f"{type(e).__name__}: {e}"})
                continue
            _font = {"name": "cjk", "source": path, "embedded": True,
                     "rule_id": "font_configured" if path == configured else "font_system", "tried": tried}
            return _font
        pdfmetrics.registerFont(UnicodeCIDFont(CID_FALLBACK))
        _font = {"name": CID_FALLBACK, "source": f"ReportLab CID {CID_FALLBACK}", "embedded": False,
                 "rule_id": "font_cid_fallback", "tried": tried}
        return _font


def image_to_pdf(src: Path, out: Path, default_dpi: float = 96) -> Path:
    """One page per image frame (multi-page TIFF), sized from the image's DPI (96 when missing)."""
    from PIL import Image, ImageSequence

    out.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(out), pageCompression=1)
    with Image.open(src) as im:
        single_jpeg = im.format == "JPEG" and getattr(im, "n_frames", 1) == 1
        for frame in ImageSequence.Iterator(im):
            dpi = frame.info.get("dpi") or (default_dpi, default_dpi)
            dx, dy = (float(v) if v and float(v) > 1 else default_dpi for v in dpi[:2])
            pw, ph = frame.width * 72 / dx, frame.height * 72 / dy
            c.setPageSize((pw, ph))
            if single_jpeg:  # embedded as is, without re-encoding
                c.drawImage(ImageReader(str(src)), 0, 0, pw, ph)
            else:
                f = frame.convert("RGBA" if "A" in frame.getbands() else "RGB")
                c.drawImage(ImageReader(f), 0, 0, pw, ph, mask="auto" if f.mode == "RGBA" else None)
            c.showPage()
    c.save()
    return out
