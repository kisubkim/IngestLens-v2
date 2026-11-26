from app.tools.tables import tidy

STACKED = """1. 총괄(전국)
|Col1|인구동태건수|Col3|인구동태율|
|---|---|---|---|
||출생|사망|조출생률|
|2019년<br>2020년<br>2022년|302,676<br>272,337<br>249,186|295,110<br>304,948<br>372,939 |5.9<br>5.3<br>4.9|
|2023. 2/4<br>3/4|56,147<br>56,765|83,209<br>86,957|4.4<br>4.4|
"""


def test_stacked_rows_split_and_header_named():
    md, info = tidy(STACKED)
    lines = md.splitlines()
    assert lines[0] == "1. 총괄(전국)"
    assert lines[1] == "||인구동태건수 출생|인구동태건수 사망|인구동태율 조출생률|"
    assert "|2022년|249,186|372,939|4.9|" in lines
    assert "|3/4|56,765|86,957|4.4|" in lines
    assert info == {"rows_split": 2, "rows_added": 3, "placeholder_headers": 2, "header_rows_merged": 1}


def test_wrapped_text_and_odd_cells_left_alone():
    wrapped = "|사진|설명|\n|---|---|\n||근정문은 정전의 정문으로<br>정면 3칸이다.<br>보물 제812호|\n"
    assert tidy(wrapped) == (wrapped, {"rows_split": 0, "rows_added": 0, "placeholder_headers": 0, "header_rows_merged": 0})
    # two wrapped text columns with the same line count: no column of numbers, so not split
    text2 = "|가|나|\n|---|---|\n|첫 줄<br>둘째 줄|하나<br>둘|\n"
    assert tidy(text2)[0] == text2
    # line counts differ between cells: ambiguous, kept
    mixed = "|연도|값|비|\n|---|---|---|\n|2019년<br>2020년|1<br>2<br>3|4<br>5|\n"
    assert tidy(mixed)[0].splitlines()[2] == "|2019년<br>2020년|1<br>2<br>3|4<br>5|"


def test_single_line_cell_repeats_and_escaped_pipe_kept():
    md, info = tidy("|시도|연도|값|\n|---|---|---|\n|서 울|2023<br>2024|10\\|1<br>20|\n")
    # "10\|1" is one cell with an escaped pipe; it is not a number, but the year column and value column are stacked
    assert md.splitlines()[2:] == ["|서 울|2023|10\\|1|", "|서 울|2024|20|"]
    assert info["rows_split"] == 1


def test_no_table_or_no_separator_unchanged():
    for text in ("본문만 있는 글\n둘째 줄", "|머리만|\n|값|\n"):
        assert tidy(text)[0] == text
