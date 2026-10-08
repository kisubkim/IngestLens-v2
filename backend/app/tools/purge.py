"""Delete documents with everything derived from them: DB rows, Qdrant points, uploaded and converted files, page images."""

import shutil

from sqlalchemy import delete, select

from ..config import settings
from ..db import session
from ..models import Chunk, Decision, Document, Element, Event, PageProfile, Run
from . import lexical, vectorstore

ACTIVE = ("queued", "running")
FILE_DIRS = ("uploads", "converted", "pages")  # each keeps one sub-folder per document id


def active_runs(doc_ids: list[str] | None = None) -> list[str]:
    """Runs still queued or running. Their task would keep writing rows, so those documents cannot be deleted."""
    with session() as s:
        q = select(Run.id).where(Run.status.in_(ACTIVE))
        if doc_ids is not None:
            q = q.where(Run.document_id.in_(doc_ids))
        return list(s.scalars(q))


def _chunk_collections() -> list[str]:
    return [c.name for c in vectorstore.client().get_collections().collections if c.name.startswith("chunks__")]


def purge_documents(doc_ids: list[str]) -> dict:
    """Children first, so the order also holds where the DB enforces foreign keys."""
    with session() as s:
        run_ids = list(s.scalars(select(Run.id).where(Run.document_id.in_(doc_ids))))
        counts = {"documents": 0, "runs": len(run_ids), "chunks": 0, "elements": 0}
        if run_ids:
            for model, key in ((Chunk, "chunks"), (Element, "elements"), (PageProfile, None), (Decision, None), (Event, None)):
                n = s.execute(delete(model).where(model.run_id.in_(run_ids))).rowcount
                if key:
                    counts[key] = n
            s.execute(delete(Run).where(Run.id.in_(run_ids)))
        counts["documents"] = s.execute(delete(Document).where(Document.id.in_(doc_ids))).rowcount

    for name in _chunk_collections():
        for doc_id in doc_ids:
            vectorstore.delete_document(name, doc_id)
    for run_id in run_ids:
        lexical.forget(run_id)
    for doc_id in doc_ids:
        for d in FILE_DIRS:
            shutil.rmtree(settings.data_dir / d / doc_id, ignore_errors=True)
    return counts


def purge_all() -> dict:
    with session() as s:
        doc_ids = list(s.scalars(select(Document.id)))
    counts = purge_documents(doc_ids)
    # Drop the collections too: also removes points left by documents that are gone from the DB.
    for name in _chunk_collections():
        vectorstore.client().delete_collection(name)
    lexical.forget_all()
    for d in FILE_DIRS:
        root = settings.data_dir / d
        if root.is_dir():
            for child in root.iterdir():
                shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)
    return counts
