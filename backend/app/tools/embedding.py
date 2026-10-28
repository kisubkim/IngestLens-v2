"""Embedding client. Uses the vLLM endpoint when configured, else a dev-only hash embedder.

Some models expect different instructions on queries and documents (EmbeddingGemma: "task: search result | query: "
and "title: {title} | text: "; e5: "query: " / "passage: "). models.yaml embedding.query_prefix and
document_prefix add them; {title} in the document prefix becomes the chunk's section ("none" without one).
embedding.dimensions asks the server for shorter (Matryoshka) vectors."""

import hashlib
import math

import httpx
from openai import AsyncOpenAI

from ..config import models_cfg


class Embedder:
    def __init__(self) -> None:
        cfg = models_cfg()["embedding"]
        self.cfg = cfg
        self.remote = bool(cfg.get("base_url"))
        self.model = cfg["model"] if self.remote else "dev-hash"
        self.dim = cfg["dim"]
        self._client = AsyncOpenAI(base_url=cfg["base_url"], api_key=cfg.get("api_key") or "EMPTY") if self.remote else None

    def prefixes(self) -> dict:
        return {"query_prefix": self.cfg.get("query_prefix") or "", "document_prefix": self.cfg.get("document_prefix") or ""}

    def _with_prefix(self, texts: list[str], kind: str, titles: list[str | None] | None, query_prefix: str | None) -> list[str]:
        if kind == "query":
            p = (self.cfg.get("query_prefix") or "") if query_prefix is None else query_prefix
            return [p + t for t in texts]
        p = self.cfg.get("document_prefix") or ""
        if not p:
            return texts
        titles = titles or [None] * len(texts)
        return [p.replace("{title}", " ".join((title or "none").split())) + t for t, title in zip(texts, titles)]

    async def embed(self, texts: list[str], kind: str = "document", titles: list[str | None] | None = None,
                    query_prefix: str | None = None) -> list[list[float]]:
        """kind: "document" (chunks; titles fill {title}) or "query". query_prefix: the one the index was built
        with, when it differs from models.yaml now (see retriever)."""
        if self.remote:
            extra = {"dimensions": int(self.cfg["dimensions"])} if self.cfg.get("dimensions") else {}
            resp = await self._client.embeddings.create(model=self.cfg["model"],
                                                        input=self._with_prefix(texts, kind, titles, query_prefix), **extra)
            vecs = [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]
            self.dim = len(vecs[0])
            return vecs
        return [hash_embed(t, self.dim) for t in texts]


async def count_tokens(text: str) -> int | None:
    """Token count from the embedding server's tokenizer (vLLM POST /tokenize, served next to /v1).
    None when there is no remote model or the server has no such endpoint (e.g. Ollama)."""
    cfg = models_cfg()["embedding"]
    if not cfg.get("base_url"):
        return None
    root = cfg["base_url"].rstrip("/").removesuffix("/v1")
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{root}/tokenize", json={"model": cfg["model"], "prompt": text})
            r.raise_for_status()
            return int(r.json()["count"])
    except (httpx.HTTPError, KeyError, ValueError):
        return None


def hash_embed(text: str, dim: int) -> list[float]:
    """Character-trigram feature hashing. Lexical overlap only; for running the pipeline without a model."""
    v = [0.0] * dim
    t = " ".join(text.lower().split())
    for i in range(max(1, len(t) - 2)):
        h = int.from_bytes(hashlib.blake2b(t[i:i + 3].encode(), digest_size=8).digest(), "little")
        v[h % dim] += 1.0 if (h >> 63) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]
