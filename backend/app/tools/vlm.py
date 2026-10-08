"""Vision-language model client (vLLM OpenAI-compatible)."""

import asyncio
import base64
import json
import re
import time
import weakref
from dataclasses import dataclass

from openai import AsyncOpenAI

from ..config import models_cfg

PROMPTS = {
    "classify": (
        "Classify this document page. Answer JSON only: "
        '{"label": one of ["text","scanned","table","diagram","chart","image_heavy","mixed"], '
        '"reason": short reason}.'
    ),
    "ocr": (
        "Transcribe all text on this page in reading order as Markdown. "
        "Use '#' headings for titles and section headings, Markdown tables for tables. "
        "Do not add commentary. Output only the transcription."
    ),
    "figure": (
        "Analyze the figure in this image for search indexing.\n"
        "The first line must be exactly: TYPE: chart | diagram | photo | table | text\n"
        "Then:\n"
        "- chart: title, chart type, axes and units, series, the data values as a Markdown table, and a one-paragraph trend summary.\n"
        "- diagram: every component and label, and every connection or flow with its direction; describe the structure step by step.\n"
        "- photo: what is shown and any visible text.\n"
        "- table: the table as a Markdown table.\n"
        "- text: transcribe the text.\n"
        "Answer in the language used in the image. Output Markdown only."
    ),
    "table": "Transcribe this table as a Markdown table. Repeat the value in every cell a merged cell spans. Output only the table.",
}


@dataclass
class VLMResult:
    text: str
    finish_reason: str | None
    seconds: float


# One semaphore per event loop, shared by every run: max_concurrency bounds total load on the vLLM server.
_sems: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()


def _semaphore(limit: int) -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    if loop not in _sems:
        _sems[loop] = asyncio.Semaphore(limit)
    return _sems[loop]


class VLMClient:
    def __init__(self) -> None:
        cfg = models_cfg()["vlm"]
        self.cfg = cfg
        self.enabled = bool(cfg.get("base_url"))
        self.image_format = cfg.get("image_format", "jpeg")
        self._client = (
            AsyncOpenAI(base_url=cfg["base_url"], api_key=cfg.get("api_key") or "EMPTY",
                        timeout=cfg.get("timeout_s", 180), max_retries=cfg.get("max_retries", 2))
            if self.enabled else None
        )

    async def ask(self, image: bytes, prompt: str, max_tokens: int | None = None) -> VLMResult:
        if not self.enabled:
            raise RuntimeError("VLM is not configured (models.yaml vlm.base_url is empty)")
        mime = "image/png" if image.startswith(b"\x89PNG") else "image/jpeg"
        url = f"data:{mime};base64," + base64.b64encode(image).decode()
        async with _semaphore(self.cfg.get("max_concurrency", 4)):
            t0 = time.perf_counter()
            resp = await self._client.chat.completions.create(
                model=self.cfg["model"],
                messages=[{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": url}},
                    {"type": "text", "text": prompt},
                ]}],
                max_tokens=max_tokens or self.cfg.get("max_tokens", 2048),
                temperature=0,
            )
            secs = time.perf_counter() - t0
        choice = resp.choices[0]
        return VLMResult(choice.message.content or "", choice.finish_reason, round(secs, 2))

    async def classify(self, image: bytes) -> dict:
        raw = (await self.ask(image, PROMPTS["classify"], max_tokens=200)).text
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            return json.loads(m.group(0)) if m else {"label": None, "reason": raw}
        except json.JSONDecodeError:
            return {"label": None, "reason": raw}
