from app.tools.chunking import chunk_elements, est_tokens, split_text


def el(page, type_, content, y=0):
    return {"page": page, "type": type_, "bbox": [0, y, 100, y + 10], "content": content}


def test_split_text_respects_max_and_keeps_all_text():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 40 for i in range(10))
    parts = split_text(text, 300)
    assert all(len(p) <= 300 for p in parts)
    assert "".join(parts).replace(" ", "").replace("\n", "") == text.replace(" ", "").replace("\n", "")


def test_split_text_hard_cuts_without_separators():
    assert split_text("x" * 250, 100) == ["x" * 100, "x" * 100, "x" * 50]


def test_section_strategy_breaks_on_titles_and_tags_section():
    els = [el(0, "title", "Intro"), el(0, "text", "a " * 20, 20), el(1, "title", "Method"), el(1, "text", "b " * 20, 20)]
    chunks = chunk_elements(els, "section", target_tokens=512, overlap_tokens=0)
    assert [c["section"] for c in chunks] == ["Intro", "Method"]
    assert chunks[1]["pages"] == [1]
    assert chunks[1]["text"].startswith("Method")


def test_tables_and_figures_are_atomic():
    els = [el(0, "text", "before"), el(0, "table", "| a | b |\n|---|---|\n| 1 | 2 |", 20), el(0, "text", "after", 40)]
    chunks = chunk_elements(els, "recursive", 512, 0)
    assert [c["element_types"] for c in chunks] == [["text"], ["table"], ["text"]]


def test_page_strategy_breaks_on_page_change():
    els = [el(0, "text", "slide one"), el(1, "text", "slide two")]
    assert len(chunk_elements(els, "page", 512, 0)) == 2
    assert len(chunk_elements(els, "recursive", 512, 0)) == 1


def test_recursive_packs_to_budget_with_overlap():
    els = [el(0, "text", f"sentence {i} " * 10, i * 10) for i in range(40)]
    chunks = chunk_elements(els, "recursive", target_tokens=100, overlap_tokens=20)
    assert len(chunks) > 1
    assert all(c["tokens"] <= est_tokens("x" * 250) + 5 for c in chunks)
    # overlap: chunk i+1 starts with the tail of chunk i
    head = chunks[1]["text"].splitlines()[0]
    assert 0 < len(head) <= 50 and chunks[0]["text"].endswith(head)


def test_overlap_carries_whole_elements_when_they_fit():
    els = [el(0, "text", f"s{i}", i) for i in range(200)]
    chunks = chunk_elements(els, "recursive", target_tokens=40, overlap_tokens=4)
    prev, nxt = chunks[0]["text"].splitlines(), chunks[1]["text"].splitlines()
    carried = nxt[: nxt.index(prev[-1]) + 1]
    assert 1 <= len(carried) and carried == prev[-len(carried):]
