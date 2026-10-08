"""IngestLens model server: embedding (bge-m3) and rerank (bge-reranker-v2-m3) in ONE process, vLLM-compatible API.

Why: vLLM serves one model per process. On a GPU in Exclusive_Process compute mode (one CUDA context per device,
and no root to change it) two vLLM servers cannot share the card. This server loads both models in a single
process, so the card sees one CUDA context.

Needs only torch, transformers, fastapi and uvicorn, all of which a vLLM Python environment already has:

    python server.py --embed-model /models/bge-m3 --rerank-model /models/bge-reranker-v2-m3 --device cuda --port 8090

Endpoints (the shapes vLLM uses, so IngestLens only needs base_url changes):
    GET  /health, /models, /v1/models
    POST /v1/embeddings   {"model", "input": str | [str]}         -> {"data": [{"index", "embedding"}], ...}
    POST /v1/rerank, /rerank {"model", "query", "documents", "top_n"} -> {"results": [{"index", "relevance_score"}]}
    POST /tokenize        {"model", "prompt"}                     -> {"count", "max_model_len"}

Every option can also come from an environment variable (MS_EMBED_MODEL, MS_RERANK_MODEL, MS_DEVICE, ...),
which is how the docker image is configured.
"""

import argparse
import os
import threading
import time
from pathlib import Path

import torch
import torch.nn.functional as F
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from transformers import AutoModel, AutoModelForSequenceClassification, AutoTokenizer


def _args() -> argparse.Namespace:
    env = os.environ.get
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--embed-model", default=env("MS_EMBED_MODEL", ""), help="path or HF id of the embedding model; empty = off")
    ap.add_argument("--embed-name", default=env("MS_EMBED_NAME", ""), help="model name clients send (default: folder name)")
    ap.add_argument("--rerank-model", default=env("MS_RERANK_MODEL", ""), help="path or HF id of the cross-encoder; empty = off")
    ap.add_argument("--rerank-name", default=env("MS_RERANK_NAME", ""))
    ap.add_argument("--device", default=env("MS_DEVICE", "cuda" if torch.cuda.is_available() else "cpu"),
                    help="cuda, cuda:1 or cpu (CUDA_VISIBLE_DEVICES also works)")
    ap.add_argument("--rerank-device", default=env("MS_RERANK_DEVICE", ""), help="default: same as --device")
    ap.add_argument("--dtype", default=env("MS_DTYPE", "auto"), choices=["auto", "float16", "bfloat16", "float32"],
                    help="auto = float16 on GPU, float32 on CPU")
    ap.add_argument("--embed-max-length", type=int, default=int(env("MS_EMBED_MAX_LENGTH", "8192")))
    ap.add_argument("--rerank-max-length", type=int, default=int(env("MS_RERANK_MAX_LENGTH", "1024")))
    ap.add_argument("--max-batch-tokens", type=int, default=int(env("MS_MAX_BATCH_TOKENS", "16384")),
                    help="padded tokens per forward pass; lower it if the GPU runs out of memory")
    ap.add_argument("--host", default=env("MS_HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(env("MS_PORT", "8090")))
    ap.add_argument("--api-key", default=env("MS_API_KEY", ""), help="require 'Authorization: Bearer <key>' when set")
    return ap.parse_args()


def _dtype(name: str, device: str) -> torch.dtype:
    if name == "auto":
        return torch.float16 if device.startswith("cuda") else torch.float32
    return getattr(torch, name)


def _name(path: str, override: str) -> str:
    return override or Path(path.rstrip("/\\")).name or path


class Embedder:
    """bge-m3 dense output: CLS token of the last hidden state, L2-normalized (what vLLM's BgeM3 'embed' task returns)."""

    def __init__(self, path: str, name: str, device: str, dtype: torch.dtype, max_length: int):
        self.name, self.device, self.max_length = name, device, max_length
        self.tok = AutoTokenizer.from_pretrained(path)
        self.model = AutoModel.from_pretrained(path, torch_dtype=dtype).to(device).eval()

    def count(self, text: str) -> int:
        return len(self.tok(text, add_special_tokens=True, truncation=False)["input_ids"])

    @torch.inference_mode()
    def __call__(self, texts: list[str], max_batch_tokens: int) -> tuple[list[list[float]], int]:
        out: list[list[float] | None] = [None] * len(texts)
        lengths = [min(self.count(t), self.max_length) for t in texts]
        order = sorted(range(len(texts)), key=lambda i: lengths[i])  # similar lengths together: less padding
        start = 0
        while start < len(order):
            end = start + 1
            while end < len(order) and lengths[order[end]] * (end - start + 1) <= max_batch_tokens:
                end += 1
            idx = order[start:end]
            enc = self.tok([texts[i] for i in idx], padding=True, truncation=True, max_length=self.max_length,
                           return_tensors="pt").to(self.device)
            cls = self.model(**enc).last_hidden_state[:, 0]
            vecs = F.normalize(cls.float(), p=2, dim=-1).cpu().tolist()
            for i, v in zip(idx, vecs):
                out[i] = v
            start = end
        return out, sum(lengths)  # type: ignore[return-value]


class Reranker:
    """Cross-encoder relevance: sigmoid of the single logit, 0..1 (FlagReranker normalize=True, CrossEncoder default)."""

    def __init__(self, path: str, name: str, device: str, dtype: torch.dtype, max_length: int):
        self.name, self.device, self.max_length = name, device, max_length
        self.tok = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForSequenceClassification.from_pretrained(path, torch_dtype=dtype).to(device).eval()

    @torch.inference_mode()
    def __call__(self, query: str, docs: list[str], batch: int = 16) -> list[float]:
        scores: list[float] = []
        for s in range(0, len(docs), batch):
            enc = self.tok([query] * len(docs[s:s + batch]), docs[s:s + batch], padding=True, truncation="only_second",
                           max_length=self.max_length, return_tensors="pt").to(self.device)
            logits = self.model(**enc).logits.view(-1).float()
            scores += torch.sigmoid(logits).cpu().tolist()
        return scores


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str | None = None
    encoding_format: str | None = None


class RerankRequest(BaseModel):
    query: str
    documents: list[str]
    model: str | None = None
    top_n: int | None = None


class TokenizeRequest(BaseModel):
    prompt: str
    model: str | None = None


def build_app(args: argparse.Namespace) -> FastAPI:
    if not (args.embed_model or args.rerank_model):
        raise SystemExit("give --embed-model and/or --rerank-model")
    rerank_device = args.rerank_device or args.device
    t0 = time.perf_counter()
    embedder = (Embedder(args.embed_model, _name(args.embed_model, args.embed_name), args.device,
                         _dtype(args.dtype, args.device), args.embed_max_length) if args.embed_model else None)
    reranker = (Reranker(args.rerank_model, _name(args.rerank_model, args.rerank_name), rerank_device,
                         _dtype(args.dtype, rerank_device), args.rerank_max_length) if args.rerank_model else None)
    print(f"loaded in {time.perf_counter() - t0:.1f}s: embed={embedder and embedder.name}@{args.device} "
          f"rerank={reranker and reranker.name}@{rerank_device} pid={os.getpid()}", flush=True)
    lock = threading.Lock()  # one forward pass at a time: the models share one GPU and one CUDA context
    app = FastAPI(title="IngestLens model server")

    def check(served, requested: str | None, kind: str):
        if served is None:
            raise HTTPException(404, f"no {kind} model is loaded")
        if requested and requested != served.name:
            raise HTTPException(404, f"model {requested!r} is not served; {kind} model is {served.name!r}")
        return served

    def listing() -> dict:
        return {"object": "list", "data": [{"id": m.name, "object": "model", "owned_by": "ingestlens"}
                                           for m in (embedder, reranker) if m]}

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "pid": os.getpid(),
                "embed": embedder and {"model": embedder.name, "device": args.device},
                "rerank": reranker and {"model": reranker.name, "device": rerank_device}}

    app.get("/models")(listing)
    app.get("/v1/models")(listing)

    @app.post("/v1/embeddings")
    def embeddings(req: EmbeddingRequest) -> dict:
        model = check(embedder, req.model, "embedding")
        texts = [req.input] if isinstance(req.input, str) else req.input
        with lock:
            vecs, tokens = model(texts, args.max_batch_tokens)
        return {"object": "list", "model": model.name, "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
                "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vecs)]}

    def rerank(req: RerankRequest) -> dict:
        model = check(reranker, req.model, "rerank")
        if not req.documents:
            return {"model": model.name, "results": []}
        with lock:
            scores = model(req.query, req.documents)
        results = sorted(({"index": i, "relevance_score": s, "document": {"text": d}}
                          for i, (s, d) in enumerate(zip(scores, req.documents))), key=lambda r: -r["relevance_score"])
        return {"model": model.name, "results": results[: req.top_n] if req.top_n else results}

    app.post("/v1/rerank")(rerank)
    app.post("/rerank")(rerank)

    @app.post("/tokenize")
    def tokenize(req: TokenizeRequest) -> dict:
        model = check(embedder, req.model, "embedding")
        return {"count": model.count(req.prompt), "max_model_len": model.max_length}

    if args.api_key:  # applied to every route except /health
        @app.middleware("http")
        async def require_key(request, call_next):
            if request.url.path != "/health" and request.headers.get("authorization") != f"Bearer {args.api_key}":
                return JSONResponse({"detail": "invalid or missing API key"}, status_code=401)
            return await call_next(request)

    return app


if __name__ == "__main__":
    a = _args()
    # One worker, no reload: a second process would open a second CUDA context.
    uvicorn.run(build_app(a), host=a.host, port=a.port, workers=1, log_level="info")
