from typing import TypedDict

from sqlalchemy.orm.attributes import flag_modified

from ..db import session
from ..models import Document, Run


class PipelineState(TypedDict, total=False):
    run_id: str
    doc_id: str
    pdf_path: str
    format: str
    page_count: int
    profile: dict
    plan: dict
    hints: dict  # Office structure hints from the PDF engine (normalize); {} for PDF and images


def update_summary(run_id: str, key: str, value) -> None:
    with session() as s:
        run = s.get(Run, run_id)
        run.summary = {**(run.summary or {}), key: value}
        flag_modified(run, "summary")


def get_document(doc_id: str) -> Document:
    with session() as s:
        return s.get(Document, doc_id)
