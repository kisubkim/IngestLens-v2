"""Intake agent: pick the PDF engine, detect the real format and normalize everything to PDF (conversion runs on
the PDF engine). An encrypted PDF opens with the document's stored password."""

import asyncio
from pathlib import Path

from ..config import rules_cfg, settings
from ..db import session
from ..events import emit_event, record_decision
from ..models import Document
from ..tools.csvdoc import judge, read_rows, write_xlsx
from ..tools.engine import PasswordError, engine
from ..tools.office import NATIVE_FORMATS, OFFICE_EXT, detect
from ..tools.textdoc import text_to_pdf
from .common import PipelineState, get_document, update_summary

STEP = "intake"
CSV_EXT = {"csv", "tsv"}


async def intake(state: PipelineState) -> dict:
    run_id = state["run_id"]
    doc = get_document(state["doc_id"])
    src = settings.resolve(doc.path)
    info = detect(src)
    fmt = info["format"]
    out_dir = settings.data_dir / "converted" / doc.id
    inputs = {**info, "size_mb": round(doc.size / 2**20, 2)}

    await asyncio.to_thread(_record_engine, run_id)
    if info["mismatch"]:
        emit_event(run_id, "warning", STEP, f"Extension .{info['extension']} does not match content ({info['magic_mime']})", info)

    hints: dict = {}
    alternatives: list = []
    if fmt == "pdf":
        pdf, rule, choice = src, "magic_pdf", "PDF: parse natively"
        try:
            pdf_info = await asyncio.to_thread(engine().info, pdf, doc.password)
        except PasswordError:
            raise ValueError("wrong PDF password: set the right one (document password) and run again") from None
    elif fmt == "image":
        pdf = out_dir / (src.stem + ".pdf")
        pdf_info = await asyncio.to_thread(engine().normalize, src, src.name, "image", pdf)
        rule, choice = "image_wrap", "Image: wrap as a one-page PDF"
    elif fmt in OFFICE_EXT:
        pdf, pdf_info, rule, choice, hints, alternatives = await _office(run_id, src, fmt, out_dir, inputs)
    elif fmt == "text" and info["extension"] in CSV_EXT and (table := await _csv_table(run_id, src, info["encoding"], out_dir, inputs)):
        pdf, pdf_info, rule, choice, hints, alternatives = table
        fmt = "csv"
    elif fmt == "text":
        pdf, pdf_info, rule, choice = await _text(run_id, src, info["encoding"], out_dir, inputs)
    else:
        raise ValueError(f"Unsupported format: .{info['extension']} ({info['magic_mime']})")

    if pdf_info["encrypted"]:
        if pdf_info["page_count"] is None:
            raise ValueError("PDF is password protected: set its password (document password) and run again")
        record_decision(run_id, STEP, "encrypted PDF", "open with the document password", rule_id="pdf_password",
                        inputs={"encrypted": True, "engine": engine().name}, confidence=1.0,
                        reasoning="The PDF needs a password to open. Every engine call for this document sends the stored "
                                  "password; it is not written to events or decisions.")
    page_count = pdf_info["page_count"]
    inputs["page_count"] = page_count

    record_decision(
        run_id, STEP, "document format", choice,
        rule_id=rule, inputs=inputs, alternatives=alternatives, confidence=1.0 if not info["mismatch"] else 0.7,
        reasoning="Every format is rendered as PDF pages so profiling, parsing and bbox overlays work the same way.",
    )
    if hints:
        update_summary(run_id, "office", _hint_summary(hints))

    with session() as s:
        d = s.get(Document, doc.id)
        d.format, d.pdf_path, d.page_count = fmt, settings.stored_path(pdf), page_count

    return {"pdf_path": str(pdf), "format": fmt, "page_count": page_count, "hints": hints}


def _record_engine(run_id: str) -> None:
    """Which PDF engine this run uses and why (RAG_PDF_ENGINE; auto asks ToolPDF first)."""
    eng = engine()
    impl = eng.select(recheck=True)
    sel = eng.selection()
    try:
        version = impl.health().get("version")
    except Exception:
        version = None
    other = "local" if impl.name == "toolpdf" else "toolpdf"
    if sel["mode"] != "auto":
        why = f"RAG_PDF_ENGINE={sel['mode']}"
    else:
        why = "ToolPDF did not answer" if impl.name == "local" else "ToolPDF answered and is preferred (PyMuPDF)"
    update_summary(run_id, "engine", {"engine": impl.name, "version": version, "mode": sel["mode"]})
    record_decision(run_id, STEP, "PDF engine", f"{impl.name} ({version})",
                    rule_id="pdf_engine_auto" if sel["mode"] == "auto" else "pdf_engine_configured",
                    inputs={"mode": sel["mode"], "engine": impl.name, "version": version, "reason": sel["reason"]},
                    alternatives=[{"choice": other, "reason_rejected": why}], confidence=1.0,
                    reasoning="Both engines follow the same contract (ToolPDF API 0.2.0). ToolPDF uses PyMuPDF; the local "
                              "engine uses permissive libraries inside the app (pypdfium2, pdfplumber).")


async def _csv_table(run_id: str, src: Path, encoding: str, out_dir: Path, inputs: dict):
    """CSV/TSV that is really a table: written as a one-sheet xlsx and drawn by the engine's spreadsheet renderer, so
    every page (and chunk) repeats the header row. Returns None (plain text instead) when it is not a table."""
    office, max_cols = rules_cfg()["office"], rules_cfg()["text"]["csv_max_columns"]
    rows, delim, truncated = await asyncio.to_thread(read_rows, src, encoding, office["xlsx_max_rows"])
    is_table, evidence = judge(rows, max_cols)
    evidence |= {"delimiter": delim, "encoding": encoding}
    if not is_table:
        record_decision(run_id, STEP, "CSV layout", "plain text (not a table)", rule_id="csv_as_text", inputs=evidence,
                        alternatives=[{"choice": "table (spreadsheet render)", "reason_rejected": evidence["reason"]}],
                        confidence=0.8,
                        reasoning="The rows do not form a regular table that fits a page, so the file is drawn line by line.")
        return None
    emit_event(run_id, "progress", STEP, f"Rendering CSV as a table ({evidence['rows']} rows x {evidence['columns']} columns)")
    xlsx = await asyncio.to_thread(write_xlsx, rows, out_dir / (src.name + ".xlsx"), src.stem or src.name)
    pdf = out_dir / (src.name + ".pdf")
    res = await asyncio.to_thread(engine().normalize, xlsx, xlsx.name, "native", pdf, True,
                                  office["xlsx_rows_per_page"], office["xlsx_max_rows"])
    inputs |= evidence | {"truncated": truncated}
    if truncated:
        record_decision(run_id, STEP, "CSV length", f"cut at {office['xlsx_max_rows']:,} rows", rule_id="csv_truncated",
                        inputs={"max_rows": office["xlsx_max_rows"]},
                        alternatives=[{"choice": "all rows", "reason_rejected": "more than office.xlsx_max_rows"}], confidence=1.0,
                        reasoning="Large tables are cut like spreadsheets; raise office.xlsx_max_rows on the rules screen to take more.")
    hints = {**res["hints"], "renderer": "native", "source": "csv"}
    alternatives = [{"choice": "plain text", "reason_rejected": "column names would appear only in the first chunk"}]
    return pdf, res, "csv_table", f"CSV: render as a table, header on every page ({evidence['rows']} rows x {evidence['columns']} columns)", hints, alternatives


async def _text(run_id: str, src: Path, encoding: str, out_dir: Path, inputs: dict):
    """Plain text (.txt, .log, no extension): decoded and drawn as A4 pages, one text line per PDF line."""
    cfg = rules_cfg()["text"]
    pdf = out_dir / (src.name + ".pdf")
    emit_event(run_id, "progress", STEP, f"Rendering text ({encoding}) as PDF pages")
    res = await asyncio.to_thread(text_to_pdf, src, pdf, encoding, cfg["font_size"], cfg["max_chars"], settings.cjk_font)
    inputs |= {"encoding": encoding, "lines": res["lines"], "chars": res["chars"], "font": res["font"]}
    if res["truncated"]:
        record_decision(run_id, STEP, "text length", f"cut at {cfg['max_chars']:,} characters", rule_id="text_truncated",
                        inputs={"max_chars": cfg["max_chars"], "size_mb": inputs.get("size_mb")},
                        alternatives=[{"choice": "whole file", "reason_rejected": "longer than text.max_chars"}], confidence=1.0,
                        reasoning="Very long text (large logs) would make thousands of pages; the rest of the file is not ingested. "
                                  "Raise text.max_chars on the rules screen to take more.")
    pdf_info = await asyncio.to_thread(engine().info, pdf)
    return pdf, pdf_info, "text_render", f"Text ({encoding}): render as PDF pages"


async def _office(run_id: str, src: Path, fmt: str, out_dir: Path, inputs: dict):
    """LibreOffice when the engine has it (best layout fidelity); native rendering otherwise, and always for xlsx
    by default. Both paths also read structure hints from the original file."""
    cfg = rules_cfg()["office"]
    soffice = (await asyncio.to_thread(engine().health)).get("libreoffice")
    native_ok = fmt in NATIVE_FORMATS
    use_native = native_ok and (cfg["prefer"] == "native" or not soffice or (fmt == "xlsx" and cfg["xlsx"] == "native"))
    inputs |= {"libreoffice": soffice or None, "native_renderer": native_ok, "prefer": cfg["prefer"]}

    if use_native:
        emit_event(run_id, "progress", STEP, f"Rendering .{fmt} natively")
        pdf = out_dir / (src.stem + ".native.pdf")
        res = await asyncio.to_thread(engine().normalize, src, src.name, "native", pdf, True,
                                      cfg["xlsx_rows_per_page"], cfg["xlsx_max_rows"])
        hints = {**res["hints"], "renderer": "native"}
        why = ("spreadsheets keep every table readable" if fmt == "xlsx" and soffice
               else "configured preference" if soffice else "LibreOffice is not installed")
        alternatives = [{"choice": "LibreOffice", "reason_rejected": why}]
        return pdf, res, "office_native", f"{fmt.upper()}: render natively ({why})", hints, alternatives
    if not soffice:
        raise ValueError(f".{fmt} needs LibreOffice (only docx/pptx/xlsx have a native renderer). Install it on the PDF engine (ToolPDF).")
    emit_event(run_id, "progress", STEP, f"Converting .{fmt} to PDF with LibreOffice")
    pdf = out_dir / (src.stem + ".pdf")
    res = await asyncio.to_thread(engine().normalize, src, src.name, "libreoffice", pdf, native_ok)
    hints = res["hints"]
    if hints:
        hints["renderer"] = "libreoffice"
    alternatives = [{"choice": "native renderer", "reason_rejected": "LibreOffice keeps the original layout"}] if native_ok else []
    return pdf, res, "office_convert", f"{fmt.upper()}: convert to PDF with LibreOffice", hints, alternatives


def _hint_summary(h: dict) -> dict:
    out = {"kind": h.get("kind"), "renderer": h.get("renderer")}
    if h.get("kind") == "pptx":
        out |= {"slides": len(h["slides"]), "with_notes": sum(bool(s["notes"]) for s in h["slides"]),
                "charts": sum(len(s["charts"]) for s in h["slides"])}
    elif h.get("kind") == "docx":
        out |= {"headings": len(h["headings"]), "images": h.get("images", 0)}
    elif h.get("kind") == "xlsx":
        out |= {"sheets": h["sheets"]}
    return out
