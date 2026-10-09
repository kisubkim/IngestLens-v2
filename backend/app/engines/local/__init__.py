"""PdfEngine inside the app, on permissive libraries only (no ToolPDF needed):

  pypdfium2 (PDFium)         open, decrypt, count, render          Apache-2.0 / BSD-3-Clause
  pdfplumber, pdfminer.six   text lines, sizes, paths, tables      MIT
  Pillow                     crops, JPEG, gray, highlights         MIT-CMU
  ReportLab                  image -> PDF, native Office render    BSD-3-Clause
  python-docx/-pptx, openpyxl  Office structure                    MIT
  LibreOffice (optional)     doc/ppt/hwp, run as its own process   MPL-2.0

Requests and results follow the same contract as ToolPDF (base.py). Work runs in the caller's thread; PDFium
calls are serialized by a process-wide lock.
"""

import shutil
import subprocess
import tempfile
from importlib.metadata import version as _pkg_version
from pathlib import Path

from ..base import CONTRACT_VERSION, STRATEGIES, EngineError, options_schema, resolve_options
from . import pdf as _pdf

NATIVE_FORMATS = {"docx", "pptx", "xlsx"}
SOFFICE_CANDIDATES = ["soffice", "libreoffice", "C:/Program Files/LibreOffice/program/soffice.exe",
                      "/usr/lib/libreoffice/program/soffice", "/opt/libreoffice/program/soffice",
                      "/Applications/LibreOffice.app/Contents/MacOS/soffice"]


def _v(pkg: str) -> str:
    try:
        return _pkg_version(pkg)
    except Exception:
        return "?"


class LocalEngine:
    name = "local"

    def __init__(self, soffice_path: str = "", cjk_font: str = "", soffice_timeout_s: int = 600):
        self.soffice_path, self.cjk_font, self.soffice_timeout_s = soffice_path, cjk_font, soffice_timeout_s

    def soffice(self) -> str | None:
        for c in ([self.soffice_path] if self.soffice_path else []) + SOFFICE_CANDIDATES:
            found = shutil.which(c) or (c if Path(c).is_file() else None)
            if found:
                return found
        return None

    # ---------- interface ----------

    def health(self, timeout_s: float = 3) -> dict:
        return {"status": "ok", "version": CONTRACT_VERSION, "contract": CONTRACT_VERSION,
                "engine": f"pypdfium2 {_v('pypdfium2')}, pdfplumber {_v('pdfplumber')}, pdfminer.six {_v('pdfminer.six')}",
                "libreoffice": self.soffice(), "transfer": [], "workers": 0}

    def options_schema(self) -> dict:
        return options_schema(CONTRACT_VERSION)

    def reset(self) -> None:
        pass

    def capabilities(self) -> dict:
        soffice = self.soffice()
        return {"options": True, "password": True, "table_strategies": list(STRATEGIES),
                "normalize": ["image", "native"] + (["libreoffice"] if soffice else []), "libreoffice": soffice}

    @staticmethod
    def _password(o: dict) -> str | None:
        return o["document"]["password"]

    def info(self, src: Path, options: dict | None = None) -> dict:
        o = resolve_options("info", options)
        return _pdf.info(src, self._password(o))

    def text(self, src: Path, limit: int = 6000, options: dict | None = None) -> str:
        o = resolve_options("text", options)
        return _pdf.sample_text(src, limit, self._password(o))

    def profile(self, src: Path, pages: list[int] | None = None, options: dict | None = None) -> list[dict]:
        o = resolve_options("profile", options)
        return _pdf.profile_pages(src, pages, o["tables"], self._password(o))

    def extract(self, src: Path, pages: list[dict], heading_min_size: float | None, figures: dict,
                options: dict | None = None) -> dict[int, dict]:
        o = resolve_options("extract", options)
        return _pdf.prepare_window(src, pages, heading_min_size, figures, o["tables"], o["image"], self._password(o))

    def render(self, src: Path, page: int, dpi: int = 96, fmt: str = "png", clip: list[float] | None = None,
               pad: float = 0, highlight: list[list[float]] | None = None, options: dict | None = None) -> bytes:
        if not 18 <= dpi <= 300:
            raise EngineError(f"dpi must be 18..300, not {dpi}")
        o = resolve_options("render", options)
        return _pdf.render(src, page, dpi, fmt, clip, pad, highlight, o["image"], self._password(o))

    def normalize(self, src: Path, filename: str, method: str, out: Path, hints: bool = True,
                  xlsx_rows_per_page: int = 24, xlsx_max_rows: int = 5000) -> dict:
        from . import office, pdfgen

        src, out = Path(src), Path(out)
        fmt = Path(filename).suffix.lower().lstrip(".")
        found: dict = {}
        with tempfile.TemporaryDirectory(prefix="ingestlens-normalize-") as w:
            named = _named(src, filename, Path(w))
            if method == "image":
                pdfgen.image_to_pdf(named, out)
            elif method == "native":
                if fmt not in NATIVE_FORMATS:
                    raise EngineError("the native renderer reads only docx, pptx and xlsx")
                found = office.render_native(named, out, fmt, xlsx_rows_per_page, xlsx_max_rows, self.cjk_font)
            elif method == "libreoffice":
                self._libreoffice(named, out, Path(w))
                if hints and fmt in NATIVE_FORMATS:
                    found = office.extract_hints(named, fmt)
            else:
                raise EngineError(f"unknown method {method!r}")
        return {"hints": found, **_pdf.info(out, None)}

    def _libreoffice(self, src: Path, out: Path, work: Path) -> None:
        exe = self.soffice()
        if not exe:
            raise EngineError("LibreOffice is not installed (set RAG_SOFFICE_PATH)")
        outdir = work / "out"
        # A private profile folder: a running LibreOffice of the user would otherwise take over the conversion.
        profile = (work / "profile").resolve().as_uri()
        subprocess.run([exe, f"-env:UserInstallation={profile}", "--headless", "--convert-to", "pdf",
                        "--outdir", str(outdir), str(src)], check=True, capture_output=True, timeout=self.soffice_timeout_s)
        pdf = outdir / (src.stem + ".pdf")
        if not pdf.exists():
            raise EngineError(f"LibreOffice produced no PDF for {src.name}")
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(pdf), out)


def _named(src: Path, filename: str, work: Path) -> Path:
    """The source under its original name: the Office readers and LibreOffice go by the extension, and a stored
    file may be named otherwise. Copies only when the name differs."""
    want = Path(filename).name
    if src.name == want:
        return src
    dest = work / want
    shutil.copyfile(src, dest)
    return dest
