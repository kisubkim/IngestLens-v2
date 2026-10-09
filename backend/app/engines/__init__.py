"""PDF engines behind one interface (base.PdfEngine; the contract is ToolPDF's README, API 0.2.0):

  toolpdf  ToolPDF, a separate program over HTTP (AGPL-3.0 program, this client is MIT)
  local    inside the app, on permissive libraries only (pypdfium2, pdfplumber, Pillow, ReportLab, ...)

This package imports nothing from the rest of the app, so it can move to its own package later.
"""

from .base import CONTRACT_VERSION, EngineError, PasswordError, PdfEngine, resolve_options

KINDS = ("auto", "toolpdf", "local")


def make_toolpdf(url: str, api_key: str = "", transfer: str = "http", data_dir=None, timeout_s: float = 600):
    from .toolpdf import ToolPDFEngine

    return ToolPDFEngine(url, api_key, transfer, data_dir, timeout_s)


def make_local(soffice_path: str = "", cjk_font: str = ""):
    from .local import LocalEngine

    return LocalEngine(soffice_path, cjk_font)


__all__ = ["CONTRACT_VERSION", "KINDS", "EngineError", "PasswordError", "PdfEngine", "make_local", "make_toolpdf",
           "resolve_options"]
