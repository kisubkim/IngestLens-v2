"""The app's PDF engine. Every PDF operation of the pipeline goes through `engine()`.

Which engine (RAG_PDF_ENGINE):
  toolpdf  ToolPDF over HTTP (RAG_TOOLPDF_URL ...)
  local    the engine inside the app, on permissive libraries only (app/engines/local)
  auto     ToolPDF when it answers, else local (default). Asked again before a run while on local, at most
           every PROBE_S seconds, so a ToolPDF started after the app is picked up.

This layer adds what the engines do not know: the rules' engine options (`engine.tables`, `engine.image`), the
document's password (looked up by its PDF path, so callers just pass the path), and the pipeline's parser names.
"""

import threading
import time
from functools import lru_cache
from pathlib import Path

from sqlalchemy import or_, select

from ..config import rules_cfg, settings
from ..engines import EngineError, PasswordError, make_local, make_toolpdf  # noqa: F401  (re-exported)

# The pipeline's parser names -> the engine's extraction mode.
PARSER_MODE = {"vlm_ocr": "ocr", "vlm_figures": "figures"}
PROBE_S = 30
# Image options for page renders (UI pages, chunk previews); colorspace is for recognizer crops only.
RENDER_IMAGE_KEYS = ("jpeg_quality", "annots")
NAMES = {"toolpdf": "ToolPDF", "local": "내장 엔진"}


def engine_rules() -> dict:
    """The rules' `engine` section: {"tables": {...}, "image": {...}}."""
    return rules_cfg().get("engine") or {}


def password_for(pdf: Path) -> str | None:
    """The stored password of the document whose original or converted PDF is `pdf`."""
    from ..db import session
    from ..models import Document

    stored = settings.stored_path(Path(pdf))
    if Path(stored).is_absolute():  # not under data_dir: no document of this app (tests, scripts)
        return None
    with session() as s:
        return s.scalars(select(Document.password).where(or_(Document.pdf_path == stored, Document.path == stored),
                                                         Document.password.is_not(None))).first()


@lru_cache
def toolpdf():
    return make_toolpdf(settings.toolpdf_url, settings.toolpdf_api_key, settings.toolpdf_transfer, settings.data_dir,
                        settings.toolpdf_timeout_s)


@lru_cache
def local():
    return make_local(settings.soffice_path, settings.cjk_font)


class AppEngine:
    def __init__(self, mode: str):
        if mode not in ("auto", "toolpdf", "local"):
            raise ValueError(f"RAG_PDF_ENGINE must be auto, toolpdf or local, not {mode!r}")
        self.mode = mode
        self._impl = None
        self.reason = ""
        self._probed = 0.0
        self._lock = threading.Lock()

    # ---------- which engine ----------

    def select(self, recheck: bool = False):
        """The engine to use. recheck: in auto mode on the local engine, ask ToolPDF again (rate-limited)."""
        with self._lock:
            if self.mode != "auto":
                if self._impl is None:
                    self._impl = toolpdf() if self.mode == "toolpdf" else local()
                    self.reason = f"RAG_PDF_ENGINE={self.mode}"
                return self._impl
            stale = self._impl is None or (recheck and self._impl.name == "local" and time.monotonic() - self._probed > PROBE_S)
            if stale:
                self._probed = time.monotonic()
                try:
                    h = toolpdf().health(timeout_s=2)
                    self._impl, self.reason = toolpdf(), f"auto: ToolPDF {settings.toolpdf_url} 응답 (버전 {h.get('version')})"
                except Exception as e:
                    self._impl, self.reason = local(), f"auto: ToolPDF {settings.toolpdf_url} 응답 없음 ({type(e).__name__})"
            return self._impl

    @property
    def impl(self):
        return self.select()

    @property
    def name(self) -> str:
        return self.impl.name

    def selection(self) -> dict:
        impl = self.impl
        return {"engine": impl.name, "label": NAMES[impl.name], "mode": self.mode, "reason": self.reason}

    def use(self, impl) -> None:
        """Pin an engine (tests, scripts)."""
        with self._lock:
            self._impl, self.reason = impl, "pinned"

    # ---------- options ----------

    @staticmethod
    def _document(pdf: Path, password: str | None) -> dict:
        pw = password if password is not None else password_for(pdf)
        return {"document": {"password": pw}} if pw else {}

    def health(self, timeout_s: float = 3) -> dict:
        return self.impl.health(timeout_s)

    def options_schema(self) -> dict | None:
        return self.impl.options_schema()

    def capabilities(self) -> dict:
        return self.impl.capabilities()

    def reset(self) -> None:
        self.impl.reset()

    # ---------- operations ----------

    def info(self, pdf: Path, password: str | None = None) -> dict:
        """{encrypted, page_count, pages: [[w, h], ...]}"""
        return self.impl.info(pdf, self._document(pdf, password))

    def text(self, pdf: Path, limit: int = 6000) -> str:
        return self.impl.text(pdf, limit, self._document(pdf, None))

    def profile(self, pdf: Path, pages: list[int] | None = None) -> list[dict]:
        """[{page, features}]. Table counts follow the rules' table options, like extract."""
        options = {**self._document(pdf, None), "tables": dict(engine_rules().get("tables") or {})}
        return self.impl.profile(pdf, pages, options)

    def extract(self, pdf: Path, pages: list[tuple[int, str, int]], heading_min: float | None, pcfg: dict,
                vlm_on: bool, vcfg: dict) -> dict[int, dict]:
        """Per page: native elements, OCR fallback, figure regions and VLM jobs with crops (bytes).
        pages: (page, parser, drawing count); the parser picks the engine's mode. A table job's "target" is the
        element it may replace (resolved from the engine's index)."""
        rules = engine_rules()
        options = {
            **self._document(pdf, None),
            "tables": {**(rules.get("tables") or {}), "crop_empty_ratio": pcfg["tables"]["max_empty_cell_ratio"]},
            "image": {**(rules.get("image") or {}), "crops": vlm_on, "format": vcfg.get("image_format", "jpeg"),
                      "render_dpi": vcfg.get("render_dpi", 150), "crop_dpi": vcfg.get("crop_dpi", 170)},
        }
        figures = {"min_area_ratio": pcfg["figures"]["min_area_ratio"], "max_per_page": pcfg["figures"]["max_per_page"],
                   "on_all_pages": pcfg["figures"]["enrich_native_pages"]}
        specs = [{"page": p, "mode": PARSER_MODE.get(parser, "text"), "drawings": d} for p, parser, d in pages]
        out = self.impl.extract(pdf, specs, heading_min, figures, options)
        for prep in out.values():
            prep["jobs"] = prep.pop("crops")
            for job in prep["jobs"]:
                if job["kind"] == "table":
                    job["target"] = prep["elements"][job["target"]]
        return out

    def render(self, pdf: Path, page: int, dpi: int, fmt: str = "png", clip: list[float] | None = None, pad: float = 0,
               highlight: list[list[float]] | None = None) -> bytes:
        image = engine_rules().get("image") or {}
        options = {**self._document(pdf, None), "image": {k: image[k] for k in RENDER_IMAGE_KEYS if k in image}}
        return self.impl.render(pdf, page, dpi, fmt, clip, pad, highlight, options)

    def normalize(self, src: Path, filename: str, method: str, out: Path, hints: bool = True,
                  xlsx_rows_per_page: int = 24, xlsx_max_rows: int = 5000) -> dict:
        """Convert an image or Office file to the PDF `out`. Returns {hints, encrypted, page_count, pages}."""
        return self.impl.normalize(src, filename, method, out, hints, xlsx_rows_per_page, xlsx_max_rows)


@lru_cache
def engine() -> AppEngine:
    return AppEngine(settings.pdf_engine)
