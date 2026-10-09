from app.tools.chunking import chunk_elements, est_tokens, section_name, split_text


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


REGISTERS = [  # a datasheet register map (LIS3DH p29): a numbered heading extracted as two lines, a one-row bit table, a note
    el(28, "title", "8.6\nWHO_AM_I (0Fh)", 10), el(28, "table", "**Table 21. WHO_AM_I register**\n|0|0|1|1|0|0|1|1|\n|---|---|", 30),
    el(28, "text", "Device identification register.", 50),
    el(28, "title", "8.7\nTEMP_CFG_REG (1Fh)", 70), el(28, "table", "**Table 22. TEMP_CFG_REG register**\n|ADC_PD|TEMP_EN|0|0|\n|---|---|", 90),
]


def test_short_chunks_stay_apart_without_min_tokens():
    chunks = chunk_elements(REGISTERS, "section", 512, 64)
    assert len(chunks) == 5
    # The section prefix keeps the register name next to its bits even when they are separate chunks.
    assert chunks[1]["section"] == "8.6 WHO_AM_I (0Fh)" and chunks[1]["text"].startswith("8.6 WHO_AM_I (0Fh)\n**Table 21")


def test_section_name_joins_a_number_only_first_line():
    assert section_name("8.6\nWHO_AM_I (0Fh)") == "8.6 WHO_AM_I (0Fh)"
    assert section_name("3.2.1.\nPower-up") == "3.2.1. Power-up"
    assert section_name("Introduction\nmore") == "Introduction"
    assert section_name("제 3 장\n개요") == "제 3 장 개요"


def test_min_tokens_merges_within_a_section_and_keeps_all_boxes():
    chunks = chunk_elements(REGISTERS, "section", 512, 64, min_tokens=128)
    assert [c["section"] for c in chunks] == ["8.6 WHO_AM_I (0Fh)", "8.7 TEMP_CFG_REG (1Fh)"]  # never across sections
    who = chunks[0]
    assert "WHO_AM_I (0Fh)" in who["text"] and "|0|0|1|1|0|0|1|1|" in who["text"] and "Device identification" in who["text"]
    # The chunk starts with the two-line title itself, so the section name is not prefixed again.
    assert who["text"].startswith("8.6\nWHO_AM_I (0Fh)\n") and who["text"].count("WHO_AM_I (0Fh)") == 1
    assert [b["bbox"][1] for b in who["bboxes"]] == [10, 30, 50] and who["pages"] == [28]
    assert who["element_types"] == ["table", "text", "title"]


def test_min_tokens_does_not_merge_across_pages_in_page_mode():
    els = [el(0, "text", "slide one"), el(1, "text", "slide two")]
    assert len(chunk_elements(els, "page", 512, 0, min_tokens=128)) == 2
    assert len(chunk_elements(els, "recursive", 512, 0, min_tokens=128)) == 1


def test_merge_respects_the_budget_and_drops_repeated_overlap():
    """A short tail chunk merged back into the full chunk before it must not repeat the overlap it carried."""
    els = [el(0, "text", f"s{i:03d}", i) for i in range(52)]
    plain = chunk_elements(els, "recursive", target_tokens=40, overlap_tokens=4)
    merged = chunk_elements(els, "recursive", target_tokens=40, overlap_tokens=4, min_tokens=20)
    assert plain[-1]["tokens"] < 20 and len(merged) == len(plain) - 1
    assert all(c["tokens"] <= 40 + 20 for c in merged)
    lines = [ln for c in merged for ln in c["text"].splitlines()]
    tail = merged[-1]["text"].splitlines()
    assert len(tail) == len(set(tail))  # no line twice inside the merged chunk
    assert {f"s{i:03d}" for i in range(52)} <= set(lines)


def test_overlap_carries_whole_elements_when_they_fit():
    els = [el(0, "text", f"s{i}", i) for i in range(200)]
    chunks = chunk_elements(els, "recursive", target_tokens=40, overlap_tokens=4)
    prev, nxt = chunks[0]["text"].splitlines(), chunks[1]["text"].splitlines()
    carried = nxt[: nxt.index(prev[-1]) + 1]
    assert 1 <= len(carried) and carried == prev[-len(carried):]
