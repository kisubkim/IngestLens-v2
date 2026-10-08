from app.config import rules_cfg
from app.tools.figures import attach_captions
from app.tools.toolpdf import engine
from app.tools.vlm_output import md_to_elements, parse_figure

from .minipdf import write_pdf

PCFG = {"tables": {"max_empty_cell_ratio": 0.5},
        "figures": {"min_area_ratio": 0.04, "max_per_page": 4, "enrich_native_pages": True}}


def test_sparse_table_job_targets_its_table_element(tmp_path):
    """Figure regions and empty-cell ratios are measured by the engine (ToolPDF tests); here: the client turns the
    engine's table index back into the element, so a VLM answer replaces the right table."""
    lines = [(72, 100 + r * 30, 372, 100 + r * 30) for r in range(5)] + [(72 + c * 100, 100, 72 + c * 100, 220) for c in range(4)]
    pdf = write_pdf(tmp_path / "sparse.pdf", [{"text": [(72, 70, 18, "Heading"), (80, 120, 9, "only"), (180, 150, 9, "two")], "lines": lines}])
    prep = engine().extract(pdf, [(0, "pymupdf_tables", len(lines))], 14.0, PCFG, True, {"image_format": "jpeg"})[0]
    job = next(j for j in prep["jobs"] if j["kind"] == "table")
    assert job["target"] is next(e for e in prep["elements"] if e["type"] == "table")
    assert job["target"]["meta"]["empty_cell_ratio"] > 0.5 and job["image"][:2] == bytes([0xFF, 0xD8])  # JPEG


def test_attach_captions_moves_caption_into_figure():
    pattern = rules_cfg()["parse"]["captions"]["pattern"]
    els = [
        {"type": "text", "bbox": [72, 100, 500, 300], "content": "본문"},
        {"type": "figure", "bbox": [72, 380, 420, 600], "content": "diagram text"},
        {"type": "text", "bbox": [72, 610, 300, 622], "content": "그림 1. 시스템 구성도"},
        {"type": "text", "bbox": [72, 700, 300, 712], "content": "그림 2. far away caption"},
    ]
    out = attach_captions(els, pattern, max_gap=40)
    assert [e["content"] for e in out if e["type"] == "text"] == ["본문", "그림 2. far away caption"]
    fig = next(e for e in out if e["type"] == "figure")
    assert fig["meta"]["caption"] == "그림 1. 시스템 구성도"
    assert fig["content"].startswith("**그림 1. 시스템 구성도**")


def test_attach_captions_bracketed_labels():
    """Government reports write captions as [그림 1], <표 1> or 【그림 1】, often above the figure."""
    pattern = rules_cfg()["parse"]["captions"]["pattern"]
    for caption in ("[그림 1] 전국 월별 출생 추이", "<표 2> 시도별 출생아 수", "【그림 3】 흐름도", "(Figure 4) Flow"):
        els = [{"type": "text", "bbox": [72, 300, 400, 312], "content": caption},
               {"type": "figure", "bbox": [72, 320, 420, 500], "content": "chart"}]
        out = attach_captions(els, pattern, max_gap=40)
        assert out[0]["meta"]["caption"] == caption, caption
    els = [{"type": "text", "bbox": [72, 300, 400, 312], "content": "[참고] 그림 1은 예시다"},
           {"type": "figure", "bbox": [72, 320, 420, 500], "content": "chart"}]
    assert len(attach_captions(els, pattern, max_gap=40)) == 2


def test_parse_figure():
    assert parse_figure("TYPE: chart\n| x | y |") == ("chart", "| x | y |")
    assert parse_figure("```markdown\n**TYPE:** Diagram\nA -> B\n```") == ("diagram", "A -> B")
    assert parse_figure("no type line") == ("diagram", "no type line")


def test_md_to_elements_keeps_structure():
    md = "# 제목\n\n첫 문단\n둘째 줄\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n## 소제목\n본문"
    els = md_to_elements(md, [0, 0, 10, 10], "vlm_ocr")
    assert [(e["type"], e["content"].splitlines()[0]) for e in els] == [
        ("title", "제목"), ("text", "첫 문단"), ("table", "| a | b |"), ("title", "소제목"), ("text", "본문")]
