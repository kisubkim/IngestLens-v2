import re
import threading
import uuid

from qdrant_client import QdrantClient, models

from ..config import settings

_client: QdrantClient | None = None
_lock = threading.Lock()


def client() -> QdrantClient:
    # Embedded mode allows only one client per storage path, so share a single instance.
    global _client
    with _lock:
        if _client is None:
            if settings.qdrant_url:
                _client = QdrantClient(url=settings.qdrant_url)
            else:
                path = settings.data_dir / "qdrant"
                path.mkdir(parents=True, exist_ok=True)
                _client = QdrantClient(path=str(path))
        return _client


def close() -> None:
    global _client
    with _lock:
        if _client is not None:
            _client.close()
            _client = None


def collection_name(model: str, dim: int) -> str:
    return "chunks__" + re.sub(r"[^a-zA-Z0-9_]+", "_", model).strip("_").lower() + f"__{dim}"


def ensure_collection(name: str, dim: int) -> None:
    c = client()
    if not c.collection_exists(name):
        c.create_collection(name, vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE))


def _match(**kv) -> models.Filter:
    return models.Filter(must=[models.FieldCondition(key=k, match=models.MatchValue(value=v)) for k, v in kv.items() if v])


def delete_document(name: str, doc_id: str) -> None:
    client().delete(name, points_selector=models.FilterSelector(filter=_match(doc_id=doc_id)))


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


def upsert(name: str, items: list[tuple[str, list[float], dict]]) -> None:
    client().upsert(name, points=[models.PointStruct(id=point_id(cid), vector=vec, payload=payload) for cid, vec, payload in items])


def search(name: str, vector: list[float], top_k: int, doc_id: str | None = None, run_id: str | None = None) -> list[dict]:
    flt = _match(doc_id=doc_id, run_id=run_id) if (doc_id or run_id) else None
    res = client().query_points(name, query=vector, limit=top_k, query_filter=flt, with_payload=True)
    return [{"score": p.score, **(p.payload or {})} for p in res.points]


def run_vectors(name: str, run_id: str, limit: int) -> list[tuple[str, list[float]]]:
    """(chunk_id, vector) for every point of a run, up to limit."""
    out, offset = [], None
    while len(out) < limit:
        points, offset = client().scroll(name, scroll_filter=_match(run_id=run_id), limit=min(256, limit - len(out)),
                                         offset=offset, with_payload=["chunk_id"], with_vectors=True)
        out += [(p.payload["chunk_id"], p.vector) for p in points]
        if offset is None:
            break
    return out


def chunk_vector(name: str, chunk_id: str) -> list[float] | None:
    pts = client().retrieve(name, ids=[point_id(chunk_id)], with_vectors=True)
    return pts[0].vector if pts else None
