"""Mock vLLM server (OpenAI-compatible) for exercising the VLM and embedding code paths without a GPU.

    python scripts/mock_vllm.py --port 8001 --latency 0.3

Then set models.yaml vlm.base_url (and optionally embedding.base_url) to http://127.0.0.1:8001/v1.
Answers are canned but follow the prompt contracts in backend/app/tools/vlm.py.
"""

import argparse
import asyncio
import base64
import hashlib
import math
import time

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="mock vLLM")
LATENCY = 0.3
DIM = 1024
stats = {"chat": 0, "embeddings": 0, "image_bytes": 0}

OCR = "# 스캔 문서 제목\n\n스캔 페이지에서 읽은 본문입니다. 장비 상태는 정상입니다.\n\n| 항목 | 값 |\n|---|---|\n| 온도 | 25 |\n| 압력 | 1.2 |"
FIGURE = {
    "chart": "TYPE: chart\n**월별 생산량** (막대 차트, 단위: 천 개)\n\n| 월 | 생산량 |\n|---|---|\n| 1월 | 120 |\n| 2월 | 135 |\n| 3월 | 150 |\n\n1월에서 3월까지 생산량이 꾸준히 증가한다.",
    "diagram": "TYPE: diagram\n구성 요소: 입력 모듈, 처리 서버, 저장소.\n\n1. 입력 모듈 → 처리 서버 (데이터 전송)\n2. 처리 서버 → 저장소 (결과 저장)",
}
TABLE = "| 구분 | 1분기 | 2분기 |\n|---|---|---|\n| 매출 | 100 | 120 |\n| 비용 | 80 | 90 |"


class ChatRequest(BaseModel):
    model: str
    messages: list[dict]
    max_tokens: int | None = None
    temperature: float | None = None


class EmbeddingRequest(BaseModel):
    model: str
    input: list[str] | str


def _answer(prompt: str, image: bytes) -> str:
    if prompt.startswith("Classify"):
        return '{"label": "diagram", "reason": "mock: vector shapes with little text"}'
    if prompt.startswith("Transcribe all text"):
        return OCR
    if "TYPE:" in prompt:
        # Deterministic variety: the image hash picks chart or diagram.
        return FIGURE["chart" if hashlib.md5(image).digest()[0] % 2 else "diagram"]
    if prompt.startswith("Transcribe this table"):
        return TABLE
    return "mock answer"


@app.get("/v1/models")
def models() -> dict:
    return {"object": "list", "data": [{"id": "mock-vl", "object": "model"}, {"id": "mock-embed", "object": "model"}]}


@app.post("/v1/chat/completions")
async def chat(req: ChatRequest) -> dict:
    content = req.messages[-1]["content"]
    if isinstance(content, str):
        prompt, image = content, b""
    else:
        prompt = next((c["text"] for c in content if c.get("type") == "text"), "")
        url = next((c["image_url"]["url"] for c in content if c.get("type") == "image_url"), "")
        if not url.startswith("data:image/"):
            raise HTTPException(400, "expected a base64 data URL image")
        image = base64.b64decode(url.split(",", 1)[1])
    stats["chat"] += 1
    stats["image_bytes"] += len(image)
    await asyncio.sleep(LATENCY)
    text = _answer(prompt, image)
    return {
        "id": f"mock-{stats['chat']}", "object": "chat.completion", "created": int(time.time()), "model": req.model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": len(text) // 2, "total_tokens": 1000 + len(text) // 2},
    }


def _embed(text: str) -> list[float]:
    v = [0.0] * DIM
    t = " ".join(text.lower().split())
    for i in range(max(1, len(t) - 2)):
        h = int.from_bytes(hashlib.blake2b(t[i:i + 3].encode(), digest_size=8).digest(), "little")
        v[h % DIM] += 1.0 if (h >> 63) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


@app.post("/v1/embeddings")
def embeddings(req: EmbeddingRequest) -> dict:
    inputs = [req.input] if isinstance(req.input, str) else req.input
    stats["embeddings"] += len(inputs)
    return {"object": "list", "model": req.model,
            "data": [{"object": "embedding", "index": i, "embedding": _embed(t)} for i, t in enumerate(inputs)],
            "usage": {"prompt_tokens": 0, "total_tokens": 0}}


class RerankRequest(BaseModel):
    model: str
    query: str
    documents: list[str]
    top_n: int | None = None


def _bigrams(t: str) -> set[str]:
    t = "".join(t.lower().split())
    return {t[i:i + 2] for i in range(len(t) - 1)}


@app.post("/v1/rerank")
def rerank(req: RerankRequest) -> dict:
    """Character-bigram overlap stands in for a cross-encoder score."""
    q = _bigrams(req.query)
    scored = [{"index": i, "relevance_score": round(len(q & _bigrams(d)) / (len(q) or 1), 4)} for i, d in enumerate(req.documents)]
    scored.sort(key=lambda r: r["relevance_score"], reverse=True)
    return {"id": "mock-rerank", "model": req.model, "results": scored[: req.top_n or len(scored)]}


class TokenizeRequest(BaseModel):
    model: str
    prompt: str


@app.post("/tokenize")
def tokenize(req: TokenizeRequest) -> dict:
    """vLLM serves /tokenize at the server root (not under /v1). Mock ratio: ~2.2 chars per token."""
    count = math.ceil(len(req.prompt) / 2.2)
    return {"count": count, "max_model_len": 8192, "tokens": list(range(count))}


@app.get("/stats")
def get_stats() -> dict:
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--latency", type=float, default=0.3, help="seconds per chat completion")
    ap.add_argument("--dim", type=int, default=1024)
    a = ap.parse_args()
    LATENCY, DIM = a.latency, a.dim
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")
