"""Document search for an LLM (Open WebUI "tool server"): its own small app mounted at /api/tools/search, so its
OpenAPI document (/api/tools/search/openapi.json) lists only these operations.

The model searches every document IngestLens has processed (agents/retriever.py `search_all`: dense + BM25, RRF,
rerank when models.yaml has a reranker) and gets the chunks with document name, 1-based pages, section and a link to
the page image. Every operation needs RAG_API_KEY when it is set.
"""

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..agents.retriever import display_name, scope, search_all
from ..config import settings
from ..db import session
from ..models import Chunk, Document
from ..tools.reranker import Reranker
from .auth import require_key

TOP_K_MAX = 20

tools_app = FastAPI(
    title="IngestLens document search",
    version="1.0",
    description="Search the documents processed by IngestLens (manuals, reports, datasheets, logs ...). Use "
                "search_documents with a short query in the words the documents would use; cite the document name and "
                "pages of the results you use. list_documents shows which documents exist.",
    root_path_in_servers=False,
)
guard = [Depends(require_key)]


class SearchReq(BaseModel):
    query: str = Field(min_length=1, description="what to look for; short, in the documents' words (Korean or English)")
    top_k: int = Field(5, ge=1, le=TOP_K_MAX, description=f"number of results (at most {TOP_K_MAX})")
    documents: list[str] | None = Field(
        None, description="only these documents: names (or part of a name) or document_id from list_documents")


def _resolve(refs: list[str]) -> list[str]:
    """Document ids for names, parts of names (case-insensitive) or ids."""
    with session() as s:
        rows = s.execute(select(Document.id, Document.filename)).all()
    ids: list[str] = []
    for ref in refs:
        r = ref.strip().lower()
        found = [d for d, name in rows if d == ref.strip() or r and r in display_name(name).lower()]
        if not found:
            raise HTTPException(404, f"no document matches {ref!r}; use list_documents")
        ids += [d for d in found if d not in ids]
    return ids


def _base(request: Request) -> str:
    return (settings.public_url or str(request.base_url).replace("/api/tools/search/", "/")).rstrip("/")


@tools_app.post("/search", operation_id="search_documents", dependencies=guard)
async def search_documents(req: SearchReq, request: Request) -> dict:
    """Search all processed documents (meaning + keywords, then rerank) and return the best passages with their
    document, pages and section. Results are ordered best first."""
    ids = _resolve(req.documents) if req.documents else None
    res = await search_all(req.query, req.top_k, ids, "hybrid", Reranker().enabled)
    base = _base(request)
    return {
        "query": req.query,
        "documents_searched": res["documents"],
        "results": [{
            "rank": h["rank"], "document": h["filename"], "document_id": h["document_id"],
            "pages": ",".join(str(p + 1) for p in h["pages"]), "section": h["section"] or "",
            "text": h["text"], "page_image": f"{base}/api/chunks/{h['chunk_id']}/preview.png",
        } for h in res["hits"]],
        "notes": res["notes"],
    }


@tools_app.post("/documents", operation_id="list_documents", dependencies=guard)
def list_documents(limit: int = 100) -> list[dict]:
    """The documents that can be searched (processed successfully), newest first: name, document_id, pages, chunks."""
    runs = scope()
    with session() as s:
        docs = {d.id: d for d in s.scalars(select(Document).where(Document.id.in_([r["document_id"] for r in runs])))}
        counts = dict(s.execute(select(Chunk.run_id, func.count()).where(Chunk.run_id.in_([r["run_id"] for r in runs]))
                                .group_by(Chunk.run_id)).all())
    out = [{"document": display_name(r["filename"]), "document_id": r["document_id"],
            "pages": docs[r["document_id"]].page_count if r["document_id"] in docs else None,
            "chunks": counts.get(r["run_id"], 0), "created_at": docs[r["document_id"]].created_at.isoformat()}
           for r in runs if r["document_id"] in docs]
    out.sort(key=lambda d: d["created_at"], reverse=True)
    return out[: max(1, min(limit, 500))]
