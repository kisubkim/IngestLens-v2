"""Format detection. Conversion to PDF is done by the PDF engine (tools/engine.py); plain text by tools/textdoc.py;
other binary content gets an overview for format analysis (tools/binview.py)."""

from pathlib import Path

import filetype

from .textdoc import sniff

OFFICE_EXT = {"doc", "docx", "ppt", "pptx", "xls", "xlsx", "odt", "odp", "ods", "rtf", "hwp"}
IMAGE_EXT = {"png", "jpg", "jpeg", "tif", "tiff", "bmp"}
NATIVE_FORMATS = {"docx", "pptx", "xlsx"}  # the engine renders these itself; the rest need LibreOffice on the engine


def detect(path: Path) -> dict:
    """The real format from magic bytes, the extension and, for text, the content: a file whose bytes decode as
    text (UTF-8, UTF-16 with BOM, CP949) is "text" whatever its extension, also without one (README, syslog)."""
    ext = path.suffix.lower().lstrip(".")
    kind = filetype.guess(str(path))
    magic_mime = kind.mime if kind else None
    magic_ext = kind.extension if kind else None
    encoding = None

    if magic_ext == "pdf" or (magic_ext is None and ext == "pdf"):
        fmt = "pdf"
    elif ext in IMAGE_EXT or (magic_mime or "").startswith("image/"):
        fmt = "image"
    elif ext in OFFICE_EXT:
        # docx/pptx/xlsx are ZIP containers, so magic bytes say "zip"; the extension picks the kind.
        fmt = ext
    elif magic_ext is None and (encoding := sniff(path)):
        fmt = "text"
    else:
        fmt = "binary"  # any other content: device logs and other undocumented formats (tools/binview.py)
    return {"extension": ext, "magic_mime": magic_mime, "magic_ext": magic_ext, "format": fmt, "encoding": encoding,
            "mismatch": bool(magic_ext and magic_ext not in (ext, "zip") and not (magic_ext == "jpg" and ext == "jpeg"))}
