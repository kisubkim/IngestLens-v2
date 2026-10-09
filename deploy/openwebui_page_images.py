"""
title: IngestLens 쪽 이미지
author: IngestLens
version: 0.4.0
description: 답변에 쓴 지식 베이스 출처의 쪽 이미지를 답변의 썸네일 줄과 출처 카드에 보여준다. 문서는 IngestLens 문서 로더로 넣어야 한다.
"""

# Open WebUI(0.11.x) Filter 함수. 관리자 패널 → 함수 → 새 함수에 이 파일 내용을 붙여 넣는다(deploy/OPENWEBUI.md 10절).
#
# 동작 (outlet: 답변이 끝난 뒤 한 번)
#   1. 마지막 답변의 출처(sources) 가운데 IngestLens가 만든 청크(metadata에 document_id, chunk_id, page) 중에서
#      **답변 내용과 맞는 청크**를 고른다(SELECT=answer). 검색은 질문과 비슷한 청크를 5개쯤 가져오는데, 그 가운데에는
#      답에 쓰이지 않은 청크(다른 주제, 낮은 점수)도 섞인다. 검색 순서대로 앞의 몇 쪽을 보여주면 답과 상관없는 쪽이
#      썸네일이 된다(2026-10-09 재현: "혼인 건수" 답에 이혼 통계 쪽). 그래서 답변과 청크에 함께 나오는 숫자, 영어 단어,
#      한글 두 글자 조각을 비교해 점수를 매긴다. 여러 청크에 다 나오는 말(예: 연도)은 가볍게 센다.
#      맞는 청크가 없으면(답이 출처를 쓰지 않았을 때) 검색 1위 쪽 하나만 보여준다.
#   2. 답변에 쪽 썸네일 줄을 붙인다(embeds 이벤트, iframe). 청크 영역이 칠해진 이미지다(IngestLens
#      /api/chunks/{id}/preview.png). 썸네일을 누르면 그 자리에서 크게 펼쳐지고, 다시 누르면 접힌다.
#      Markdown 이미지는 Open WebUI가 원래 크기로 그리고, 눌렀을 때 미리보기 창도 원래 크기까지만 키운다.
#      그래서 "작은 썸네일 + 선명한 큰 이미지"를 한 번에 하려면 직접 그리는 embed가 필요하다.
#   3. 같은 이미지를 출처 이벤트로 보내, 그 문서의 출처 카드(팝업)에도 보이게 한다.
# 2와 3은 Open WebUI가 대화에 저장하므로 새로 고쳐도 남는다.
# 이미지는 사용자 브라우저가 직접 불러온다. INGESTLENS_URL 은 사용자 PC에서 열리는 주소여야 한다.

import re
from html import escape

from pydantic import BaseModel, Field

MARKER = "ingestlens-pages"
# Words that say nothing about which passage an answer came from.
STOP = {"the", "and", "for", "with", "that", "this", "are", "was", "were", "from", "has", "have", "its", "which", "into",
        "than", "also", "can", "not", "but", "use", "uses", "used", "using", "based", "such", "these", "their"}

GALLERY = """<!doctype html><meta charset="utf-8"><style>
*{box-sizing:border-box}html,body{overflow:hidden}
body{margin:0;padding:0 2px;font:13px/1.4 system-ui,sans-serif;color:#888;background:transparent}
.h{margin:2px 0 8px}
#row{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-start}
figure{margin:0}
#row figure{cursor:zoom-in}
#row img{display:block;max-width:SIZEpx;max-height:SIZEpx;border:1px solid rgba(128,128,128,.45);border-radius:6px;background:#fff}
figcaption{margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#row figcaption{max-width:SIZEpx}
#big{display:none;cursor:zoom-out}
#big img{display:block;max-width:100%;max-height:BIGpx;border:1px solid rgba(128,128,128,.45);border-radius:8px;background:#fff}
</style><div id="MARKER"><div class="h">참고한 쪽 · 누르면 크게 보기</div><div id="row">FIGURES</div>
<figure id="big"><img id="bigimg" alt=""><figcaption id="bigcap"></figcaption></figure></div>
<script>
// Measure the content box: documentElement.scrollHeight never drops below the current iframe height.
const box = document.getElementById("MARKER");
const post = () => parent.postMessage({type: "iframe:height", height: Math.ceil(box.getBoundingClientRect().bottom) + 4}, "*");
const row = document.getElementById("row"), big = document.getElementById("big");
row.querySelectorAll("figure").forEach(f => f.onclick = () => {
  document.getElementById("bigimg").src = f.querySelector("img").src;
  document.getElementById("bigcap").textContent = f.querySelector("figcaption").textContent + " · 누르면 접기";
  row.style.display = "none"; big.style.display = "block"; post();
});
big.onclick = () => { big.style.display = "none"; row.style.display = "flex"; post(); };
document.querySelectorAll("img").forEach(i => i.addEventListener("load", post));
new ResizeObserver(post).observe(box); post();
</script>"""


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=0, description="여러 필터가 있을 때 실행 순서")
        INGESTLENS_URL: str = Field(default="http://localhost:8000", description="사용자 브라우저에서 열리는 IngestLens 주소")
        MAX_PAGES: int = Field(default=3, description="답변 하나에 보여줄 최대 쪽 수")
        SELECT: str = Field(default="answer", description="answer: 답변 내용과 맞는 청크의 쪽만. rank: 예전 방식(검색 순서대로 앞의 쪽)")
        MIN_MATCH: float = Field(default=0.3, description="answer 방식에서 보여줄 최소 일치도(0~1). 가장 잘 맞는 청크의 65% 미만도 뺀다")
        THUMB_SIZE: int = Field(default=220, description="썸네일의 긴 변(px). 가로 문서는 가로가, 세로 문서는 세로가 이 크기")
        BIG_HEIGHT: int = Field(default=900, description="눌러서 크게 볼 때의 최대 높이(px). 폭은 답변 폭까지")
        DPI: int = Field(default=110, description="이미지 해상도. 썸네일, 크게 보기, 출처 카드가 같은 이미지를 쓴다")
        HIGHLIGHT: bool = Field(default=True, description="청크 영역을 칠한 이미지를 쓴다. 끄면 쪽 전체 이미지")
        SHOW_IN_CHAT: bool = Field(default=True, description="답변에 썸네일 줄을 붙인다")
        SHOW_IN_SOURCES: bool = Field(default=True, description="출처 카드(팝업)에 이미지를 넣는다")

    def __init__(self):
        self.valves = self.Valves()

    def _url(self, page: dict) -> str:
        base, v = self.valves.INGESTLENS_URL.rstrip("/"), self.valves
        if not page["chunk_id"]:  # no chunk metadata: plain page image
            return f"{base}/api/documents/{page['document_id']}/pages/{page['page']}.png?dpi={v.DPI}"
        hl = "" if v.HIGHLIGHT else "&highlight=false"
        return f"{base}/api/chunks/{page['chunk_id']}/preview.png?page={page['page']}&dpi={v.DPI}{hl}"

    def _gallery(self, pages: list[dict]) -> str:
        figures = "".join(
            f'<figure><img src="{escape(self._url(p))}" alt="{escape(label)}" loading="lazy">'
            f"<figcaption>{escape(label)}</figcaption></figure>"
            for p in pages for label in [f"{p['name']} {p['page'] + 1}쪽"])
        size = str(max(80, self.valves.THUMB_SIZE))
        return GALLERY.replace("BIG", str(max(200, self.valves.BIG_HEIGHT))).replace("SIZE", size).replace("MARKER", MARKER).replace("FIGURES", figures)

    @staticmethod
    def _chunks(sources: list) -> list[dict]:
        """IngestLens chunks in source order (the order Open WebUI ranked them), with their text."""
        out = []
        for src in sources or []:
            docs = src.get("document") or []
            for i, meta in enumerate(src.get("metadata") or []):
                if not isinstance(meta, dict) or meta.get("ingestlens_image"):
                    continue
                doc_id, page = meta.get("document_id"), meta.get("page")
                if not doc_id or not isinstance(page, int):
                    continue
                out.append({"document_id": doc_id, "page": page, "chunk_id": meta.get("chunk_id"),
                            "name": meta.get("name") or meta.get("source") or "문서", "file_id": meta.get("file_id"),
                            "text": docs[i] if i < len(docs) and isinstance(docs[i], str) else ""})
        return out

    @staticmethod
    def _terms(text: str) -> set[str]:
        """Numbers (commas dropped), English words of 3+ letters cut to 6 letters (license/licensed, model/models), and
        Hangul syllable bigrams."""
        t = text.lower()
        nums = {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", t) if len(n.replace(",", "")) >= 2}
        words = {w[:6] for w in (m.strip("-") for m in re.findall(r"[a-z][a-z\-]{2,}", t)) if len(w) >= 3 and w not in STOP}
        bigrams = {w[i:i + 2] for w in re.findall(r"[가-힣]{2,}", t) for i in range(len(w) - 1)}
        return nums | words | bigrams

    def _select(self, chunks: list[dict], answer: str) -> list[dict]:
        """Chunks whose text the answer draws on, best first. Each term counts 1/(chunks containing it), so words that
        every retrieved chunk shares (the year, the topic) weigh little and the passage-specific ones decide."""
        terms = [self._terms(c["text"]) for c in chunks]
        df: dict[str, int] = {}
        for ts in terms:
            for t in ts:
                df[t] = df.get(t, 0) + 1
        used = {t for t in self._terms(answer) if t in df}
        total = sum(1 / df[t] for t in used)
        if not total:
            return chunks[:1]
        scored = [(sum(1 / df[t] for t in used & ts) / total, i) for i, ts in enumerate(terms)]
        best = max(s for s, _ in scored)
        keep = [chunks[i] for s, i in sorted(scored, key=lambda x: (-x[0], x[1]))
                if s >= self.valves.MIN_MATCH and s >= best * 0.65]
        return keep or chunks[:1]

    def _pages(self, sources: list, answer: str = "") -> list[dict]:
        """One entry per (document, page): the answer-matched chunks (SELECT=answer) or all of them in rank order."""
        chunks = self._chunks(sources)
        if self.valves.SELECT == "answer" and chunks:
            chunks = self._select(chunks, answer or "")
        seen, out = set(), []
        for c in chunks:
            if (c["document_id"], c["page"]) not in seen:
                seen.add((c["document_id"], c["page"]))
                out.append(c)
        return out

    async def outlet(self, body: dict, __event_emitter__=None, __user__=None) -> dict:
        messages = body.get("messages") or []
        if not messages or messages[-1].get("role") != "assistant" or not __event_emitter__:
            return body
        last = messages[-1]
        if any(MARKER in e for e in last.get("embeds") or [] if isinstance(e, str)):  # already added
            return body
        pages = self._pages(last.get("sources"), last.get("content") or "")[: max(0, self.valves.MAX_PAGES)]
        if not pages:
            return body

        if self.valves.SHOW_IN_CHAT:
            await __event_emitter__({"type": "embeds", "data": {"embeds": [self._gallery(pages)]}})

        if self.valves.SHOW_IN_SOURCES:
            for p in pages:
                # Same `source` name as the text excerpts, so Open WebUI groups the image into that document's card.
                await __event_emitter__({
                    "type": "source",
                    "data": {
                        "source": {"id": p["name"], "name": p["name"]},
                        "document": [f"![{p['name']} {p['page'] + 1}쪽]({self._url(p)})"],
                        "metadata": [{"source": p["name"], "name": p["name"], "page": p["page"],
                                      **({"file_id": p["file_id"]} if p["file_id"] else {}),
                                      "ingestlens_image": True}],
                    },
                })
        return body
