"""Format detection. Conversion to PDF (images, Office files) is done by the PDF engine (tools/toolpdf.py)."""

from pathlib import Path

import filetype

OFFICE_EXT = {"doc", "docx", "ppt", "pptx", "xls", "xlsx", "odt", "odp", "ods", "rtf", "hwp"}
IMAGE_EXT = {"png", "jpg", "jpeg", "tif", "tiff", "bmp"}
NATIVE_FORMATS = {"docx", "pptx", "xlsx"}  # the engine renders these itself; the rest need LibreOffice on the engine


def detect(path: Path) -> dict:
    ext = path.suffix.lower().lstrip(".")
    kind = filetype.guess(str(path))
    magic_mime = kind.mime if kind else None
    magic_ext = kind.extension if kind else None

    if magic_ext == "pdf" or (magic_ext is None and ext == "pdf"):
        fmt = "pdf"
    elif ext in IMAGE_EXT or (magic_mime or "").startswith("image/"):
        fmt = "image"
    elif ext in OFFICE_EXT:
        # docx/pptx/xlsx are ZIP containers, so magic bytes say "zip"; the extension picks the kind.
        fmt = ext
    else:
        fmt = "unknown"
    return {"extension": ext, "magic_mime": magic_mime, "magic_ext": magic_ext, "format": fmt,
            "mismatch": bool(magic_ext and magic_ext not in (ext, "zip") and not (magic_ext == "jpg" and ext == "jpeg"))}
