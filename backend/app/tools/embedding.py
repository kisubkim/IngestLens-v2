"""Embedding client. Uses the vLLM endpoint when configured, else a dev-only hash embedder."""

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

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self.remote:
            resp = await self._client.embeddings.create(model=self.cfg["model"], input=texts)
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
