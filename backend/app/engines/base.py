"""The PDF engine interface. The contract is ToolPDF's README (API 0.2.0): every engine takes the same requests
and returns the same shapes, so the pipeline does not care which one runs.

This package must stay independent of the app (no `app.*` imports outside `app.engines`), so it can later
move to its own MIT package that other apps share. Engines get their settings as constructor arguments.

Shapes (pages 0-based, coordinates PDF points with a top-left origin):
  info      {encrypted, page_count, pages: [[w, h], ...]}; an encrypted PDF without password: page_count None
  text      plain text of the first pages, up to `limit` characters
  profile   [{page, features}]; features: text_chars, text_area_ratio, images, image_area_ratio, drawings,
            tables, table_area_ratio, table_text_share, size_hist
  extract   {page: {rect, elements, fallback, crops, regions, skipped_regions}}; crop images are bytes here
            (base64 only on the wire)
  render    image bytes; IndexError for a page out of range
  normalize {hints, encrypted, page_count, pages}, the PDF written to `out`
"""

from pathlib import Path
from typing import Protocol, runtime_checkable

CONTRACT_VERSION = "0.2.0"  # the ToolPDF API version whose shapes and options this interface follows


class EngineError(RuntimeError):
    """The engine refused or failed a request; the message carries the reason."""


class PasswordError(EngineError):
    """The PDF is encrypted and the password is missing or wrong."""


# ---------- options (ToolPDF README "옵션") ----------
# name -> (default, kind, allowed): kind "bool", "int", "float", "choice"; allowed is (min, max) or the choices.
STRATEGIES = ("lines", "lines_strict", "text")
OPTION_SPEC: dict[str, dict[str, tuple]] = {
    "document": {
        "password": (None, "str", None),
    },
    "tables": {
        "enabled": (True, "bool", None),
        "strategy": ("lines", "choice", STRATEGIES),
        "vertical_strategy": (None, "choice", STRATEGIES),
        "horizontal_strategy": (None, "choice", STRATEGIES),
        "snap_tolerance": (3.0, "float", (0, 50)),
        "join_tolerance": (3.0, "float", (0, 50)),
        "edge_min_length": (3.0, "float", (0, 50)),
        "intersection_tolerance": (3.0, "float", (0, 50)),
        "text_tolerance": (3.0, "float", (0, 50)),
        "min_words_vertical": (3, "int", (1, 100)),
        "min_words_horizontal": (1, "int", (1, 100)),
        "markdown_clean": (False, "bool", None),
        "markdown_fill_empty": (True, "bool", None),
        "crop_empty_ratio": (0.5, "float", (0, 1)),
    },
    "image": {
        "jpeg_quality": (85, "int", (30, 100)),
        "colorspace": ("rgb", "choice", ("rgb", "gray")),
        "annots": (True, "bool", None),
        "crops": (True, "bool", None),
        "format": ("jpeg", "choice", ("jpeg", "png")),
        "render_dpi": (150, "int", (18, 300)),
        "crop_dpi": (170, "int", (18, 300)),
        "crop_pad": (6.0, "float", (0, 72)),
    },
}
# Option groups each API takes; render takes only the image keys that apply to a page image.
API_GROUPS = {"info": ("document",), "text": ("document",), "profile": ("document", "tables"),
              "extract": ("document", "tables", "image"), "render": ("document", "image")}
RENDER_IMAGE_KEYS = ("jpeg_quality", "colorspace", "annots")
NULLABLE = {("document", "password"), ("tables", "vertical_strategy"), ("tables", "horizontal_strategy")}


def _check(group: str, key: str, value):
    default, kind, allowed = OPTION_SPEC[group][key]
    if value is None and (group, key) in NULLABLE:
        return None
    ok = {"bool": lambda v: isinstance(v, bool),
          "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
          "float": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
          "str": lambda v: isinstance(v, str),
          "choice": lambda v: v in allowed}[kind](value)
    if ok and kind in ("int", "float") and not allowed[0] <= value <= allowed[1]:
        ok = False
    if not ok:
        raise EngineError(f"options.{group}.{key}: invalid value {value!r}")
    return float(value) if kind == "float" else value


def resolve_options(api: str, options: dict | None) -> dict:
    """Defaults filled in and values checked, like the engine's request validation: unknown keys and values out
    of range are errors."""
    options = options or {}
    groups = API_GROUPS[api]
    if unknown := set(options) - set(groups):
        raise EngineError(f"{api}: unknown option groups {sorted(unknown)}")
    out = {}
    for g in groups:
        keys = RENDER_IMAGE_KEYS if (api, g) == ("render", "image") else tuple(OPTION_SPEC[g])
        given = options.get(g) or {}
        if unknown := set(given) - set(keys):
            raise EngineError(f"{api}: unknown options.{g} keys {sorted(unknown)}")
        out[g] = {k: _check(g, k, given[k]) if k in given else OPTION_SPEC[g][k][0] for k in keys}
    return out


def public_options(resolved: dict) -> dict:
    """Effective options for a response: everything except the document group (the password)."""
    return {g: v for g, v in resolved.items() if g != "document"}


def options_schema(version: str) -> dict:
    """Same shape as ToolPDF's GET /v1/options: {version, endpoints: {api: {schema, defaults}}}."""
    def prop(g, k):
        default, kind, allowed = OPTION_SPEC[g][k]
        p: dict = {"default": default}
        if kind == "choice":
            p["enum"] = list(allowed) + ([None] if (g, k) in NULLABLE else [])
        else:
            p["type"] = {"bool": "boolean", "int": "integer", "float": "number", "str": "string"}[kind]
            if allowed:
                p["minimum"], p["maximum"] = allowed
        return p

    endpoints = {}
    for api, groups in API_GROUPS.items():
        schema = {"type": "object", "properties": {}}
        for g in groups:
            keys = RENDER_IMAGE_KEYS if (api, g) == ("render", "image") else tuple(OPTION_SPEC[g])
            schema["properties"][g] = {"type": "object", "properties": {k: prop(g, k) for k in keys}}
        defaults = public_options(resolve_options(api, None))
        endpoints[api] = {"schema": schema, "defaults": defaults}
    return {"version": version, "endpoints": endpoints}


# ---------- interface ----------

@runtime_checkable
class PdfEngine(Protocol):
    name: str  # "toolpdf" | "local"

    def health(self, timeout_s: float = 3) -> dict:
        """{status, engine, version, libreoffice, ...}"""

    def capabilities(self) -> dict:
        """{options: bool, password: bool, table_strategies: [...], normalize: [...], libreoffice: str | None}"""

    def options_schema(self) -> dict | None:
        """GET /v1/options shape, or None when the engine takes no options (ToolPDF older than 0.2.0)."""

    def info(self, src: Path, options: dict | None = None) -> dict: ...

    def text(self, src: Path, limit: int = 6000, options: dict | None = None) -> str: ...

    def profile(self, src: Path, pages: list[int] | None = None, options: dict | None = None) -> list[dict]: ...

    def extract(self, src: Path, pages: list[dict], heading_min_size: float | None, figures: dict,
                options: dict | None = None) -> dict[int, dict]:
        """pages: [{page, mode, drawings}]; figures: {min_area_ratio, max_per_page, on_all_pages}."""

    def render(self, src: Path, page: int, dpi: int = 96, fmt: str = "png", clip: list[float] | None = None,
               pad: float = 0, highlight: list[list[float]] | None = None, options: dict | None = None) -> bytes: ...

    def normalize(self, src: Path, filename: str, method: str, out: Path, hints: bool = True,
                  xlsx_rows_per_page: int = 24, xlsx_max_rows: int = 5000) -> dict: ...
