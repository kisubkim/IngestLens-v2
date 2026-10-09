"""The Open WebUI page-image filter (deploy/openwebui_page_images.py) shows the pages the answer drew on, not just the
first retrieved ones. The case below is the one reproduced on 2026-10-09: a marriage-count answer got a divorce-table
page as its second thumbnail because retrieval ranked it high."""

import asyncio
import importlib.util
from pathlib import Path

FILTER = Path(__file__).resolve().parents[2] / "deploy" / "openwebui_page_images.py"


def _filter(**valves):
    spec = importlib.util.spec_from_file_location("openwebui_page_images", FILTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    f = mod.Filter()
    for k, v in valves.items():
        setattr(f.valves, k, v)
    return f


def _source(chunks):
    """One Open WebUI source with IngestLens chunk metadata, in retrieval order."""
    return {"source": {"type": "collection"}, "document": [text for _, _, text in chunks],
            "metadata": [{"document_id": "doc1", "chunk_id": cid, "page": page, "name": "report.pdf", "source": "report.pdf"}
                         for cid, page, text in chunks]}


SOURCES = [_source([
    ("r-00032", 3, "□2025년 8월 혼인 건수는 19,449건, 전년동월대비 1,922건(11.0%) 증가함"),
    ("r-00042", 4, "□2025년 8월 이혼 건수는 7,196건, 전년동월대비 420건(-5.5%) 감소함 [표 9] 전국 이혼 건수 및 증감률"),
    ("r-00011", 0, "□자연증가(출생아 수 - 사망자 수)는 –8,105명, 혼인 건수와 이혼 건수 추이"),
    ("r-00033", 3, "[표 7] 전국 혼인 건수 및 증감률 | 2023년 | 2024년 | 2025년p | 19,449 | 11.0"),
])]
ANSWER = "2025년 8월 혼인 건수는 19,449건입니다 [1]. 이는 전년 동월 대비 1,922건(11.0%) 증가한 수치입니다 [1]."


def _shown(f, answer, sources):
    events = []

    async def emit(e):
        events.append(e)

    body = {"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": answer, "sources": sources}]}
    asyncio.run(f.outlet(body, __event_emitter__=emit))
    return [(e["data"]["metadata"][0]["page"]) for e in events if e["type"] == "source"]


def test_shows_only_the_pages_the_answer_used():
    assert _shown(_filter(), ANSWER, SOURCES) == [3]


def test_rank_mode_keeps_the_old_retrieval_order():
    assert _shown(_filter(SELECT="rank"), ANSWER, SOURCES) == [3, 4, 0]


def test_answer_without_source_terms_falls_back_to_the_top_hit():
    assert _shown(_filter(), "잘 모르겠습니다.", SOURCES) == [3]


def test_english_word_forms_match():
    """'MIT-licensed' in the passage matches 'MIT license' in the answer."""
    sources = [_source([("d-1", 1, "Docling is an easy to use, self-contained, MIT- licensed open-source package."),
                        ("d-2", 2, "To use Docling, you can simply install the docling package from PyPI.")])]
    assert _shown(_filter(), "Docling is distributed under the MIT license.", sources) == [1]
