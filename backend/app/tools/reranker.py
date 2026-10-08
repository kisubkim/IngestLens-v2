"""Cross-encoder reranker via vLLM's rerank API (POST {base_url}/rerank, Jina/Cohere-style)."""

import httpx

from ..config import models_cfg


class Reranker:
    def __init__(self) -> None:
        cfg = models_cfg().get("reranker") or {}
        self.cfg = cfg
        self.enabled = bool(cfg.get("base_url"))
        self.model = cfg.get("model")

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        """Relevance score per document, in input order."""
        url = self.cfg["base_url"].rstrip("/") + "/rerank"
        headers = {"Authorization": f"Bearer {self.cfg.get('api_key') or 'EMPTY'}"}
        async with httpx.AsyncClient(timeout=self.cfg.get("timeout_s", 60)) as c:
            r = await c.post(url, headers=headers, json={"model": self.model, "query": query, "documents": documents})
            r.raise_for_status()
        scores = [0.0] * len(documents)
        for item in r.json()["results"]:
            scores[item["index"]] = float(item["relevance_score"])
        return scores
