from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..agents.retriever import search as run_search

router = APIRouter(prefix="/api/search", tags=["search"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(5, ge=1, le=50)
    document_id: str | None = None
    run_id: str | None = None
    mode: Literal["dense", "lexical", "hybrid"] = "hybrid"
    rerank: bool = False
    dense_weight: float = Field(1.0, ge=0, le=5)
    lexical_weight: float = Field(1.0, ge=0, le=5)


@router.post("")
async def search(req: SearchRequest) -> dict:
    if not (req.document_id or req.run_id):
        raise HTTPException(422, "document_id or run_id is required")
    return await run_search(req.query, req.top_k, req.document_id, req.run_id, req.mode, req.rerank, req.dense_weight, req.lexical_weight)


@router.get("/capabilities")
def capabilities() -> dict:
    from ..tools.embedding import Embedder
    from ..tools.reranker import Reranker

    r = Reranker()
    return {"embedding_model": Embedder().model, "reranker": r.model if r.enabled else None}
