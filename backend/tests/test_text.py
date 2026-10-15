"""Plain text files (.txt, .log, no extension): detected from their content, drawn as PDF pages, ingested."""

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tools.engine import engine
from app.tools.office import detect
from app.tools.textdoc import text_to_pdf

LOG_KO = "\n".join(f"2026-10-15 09:{i % 60:02d}:00 INFO 센서 {i}번 측정값 정상, 온도 {20 + i % 7}도" for i in range(120)) + "\n"


def _write(path: Path, text: str, encoding: str = "utf-8") -> Path:
    path.write_bytes(text.encode(encoding))
    return path


def test_detect_text_by_content(tmp_path):
    assert detect(_write(tmp_path / "notes.txt", "hello\n"))["format"] == "text"
    log = detect(_write(tmp_path / "app.log", LOG_KO, "cp949"))
    assert log["format"] == "text" and log["encoding"] == "cp949"
    bare = detect(_write(tmp_path / "README", "# Title\n\n본문입니다.\n"))
    assert bare["format"] == "text" and bare["encoding"] == "utf-8" and bare["extension"] == ""
    assert detect(_write(tmp_path / "u16.txt", "﻿유니코드", "utf-16-le"))["encoding"] == "utf-16"
    assert detect(_write(tmp_path / "server.conf", "port = 8000\n"))["format"] == "text"
    binary = tmp_path / "blob"
    binary.write_bytes(bytes(range(256)) * 10)
    assert detect(binary)["format"] == "binary"
    # a real format keeps winning over the text sniff
    assert detect(Path(__file__).parent / "fixtures" / "sample.pdf")["format"] == "pdf"


def test_text_to_pdf_pages_wrap_and_cut(tmp_path):
    src = _write(tmp_path / "big.log", "\n".join(f"line {i} " + "x" * 300 for i in range(200)))
    res = text_to_pdf(src, tmp_path / "big.pdf", "utf-8", 9, 1_000_000)
    assert res["lines"] == 200 and not res["truncated"] and res["pages"] > 4  # 300-char lines wrap
    info = engine().info(tmp_path / "big.pdf")
    assert info["page_count"] == res["pages"]
    assert "line 0" in engine().text(tmp_path / "big.pdf", 200)
    cut = text_to_pdf(src, tmp_path / "cut.pdf", "utf-8", 9, 5000)
    assert cut["truncated"] and cut["chars"] == 5000


def _run(client: TestClient, path: Path) -> dict:
    with path.open("rb") as f:
        doc = client.post("/api/documents", files={"file": (path.name, f, "application/octet-stream")}).json()
    run = client.post(f"/api/documents/{doc['id']}/runs").json()
    deadline = time.time() + 60
    while (run := client.get(f"/api/runs/{run['id']}").json())["status"] not in ("succeeded", "failed") and time.time() < deadline:
        time.sleep(0.2)
    return run


def test_ingest_log_and_extensionless_file(tmp_path):
    with TestClient(app) as client:
        for path, enc in ((_write(tmp_path / "sensor.log", LOG_KO, "cp949"), "cp949"),
                          (_write(tmp_path / "CHANGELOG", "변경 내역\n\n1.2 버전에서 암호 PDF를 지원한다.\n" * 20), "utf-8")):
            run = _run(client, path)
            assert run["status"] == "succeeded", run["error"]
            d = next(x for x in client.get(f"/api/runs/{run['id']}/decisions").json() if x["subject"] == "document format")
            assert d["rule_id"] == "text_render" and d["inputs"]["encoding"] == enc
            chunks = client.get(f"/api/runs/{run['id']}/chunks").json()["items"]
            text = " ".join(c["text"] for c in chunks)
            assert ("센서 7번" in text) if enc == "cp949" else ("암호 PDF" in text)


def test_binary_without_extension_is_not_text(tmp_path):
    """Binary content is not mistaken for text; it gets the binary overview (test_binary.py)."""
    blob = tmp_path / "firmware"
    blob.write_bytes(bytes(range(256)) * 50)
    assert detect(blob)["format"] == "binary"


# ---------- CSV / TSV ----------

def _csv(path: Path, rows: list[list], delim: str = ",", encoding: str = "utf-8") -> Path:
    return _write(path, "\n".join(delim.join(str(c) for c in r) for r in rows) + "\n", encoding)


SALES = [["월", "지역", "판매량", "비율"]] + [[f"2026-{m:02d}", r, 1000 + m * 7 + i, f"0.{i}{m}"]
                                            for m in range(1, 13) for i, r in enumerate(["서울", "부산", "대구", "광주", "대전"])]


def test_judge_table_or_text(tmp_path):
    from app.tools.csvdoc import judge, read_rows

    rows, delim, cut = read_rows(_csv(tmp_path / "s.csv", SALES), "utf-8", 5000)
    assert delim == "," and not cut and judge(rows, 20)[0]
    rows, delim, _ = read_rows(_csv(tmp_path / "s.tsv", SALES, "\t"), "utf-8", 5000)
    assert delim == "\t" and judge(rows, 20)[0]
    rows, _, cut = read_rows(_csv(tmp_path / "long.csv", SALES), "utf-8", 10)
    assert cut and len(rows) == 11
    wide = [[f"c{i}" for i in range(30)]] + [[str(i)] * 30 for i in range(5)]
    ok, why = judge(read_rows(_csv(tmp_path / "w.csv", wide), "utf-8", 5000)[0], 20)
    assert not ok and "30 columns" in why["reason"]
    ragged = [["a", "b", "c"], ["1"], ["1", "2", "3", "4", "5"], ["x", "y"], ["only"]]
    assert not judge(read_rows(_csv(tmp_path / "r.csv", ragged), "utf-8", 5000)[0], 20)[0]


def test_csv_as_table_repeats_the_header(tmp_path):
    with TestClient(app) as client:
        run = _run(client, _csv(tmp_path / "sales.csv", SALES, encoding="cp949"))
        assert run["status"] == "succeeded", run["error"]
        decisions = {x["subject"]: x for x in client.get(f"/api/runs/{run['id']}/decisions").json()}
        d = decisions["document format"]
        assert d["rule_id"] == "csv_table" and d["inputs"]["columns"] == 4 and d["inputs"]["rows"] == 61
        assert decisions["chunking"]["rule_id"] == "sheets"
        chunks = client.get(f"/api/runs/{run['id']}/chunks").json()["items"]
        assert len(chunks) >= 3  # 60 rows, 24 per page
        assert all("판매량" in c["text"] for c in chunks)  # every chunk carries the column names
        assert any("2026-12" in c["text"] for c in chunks)


def test_wide_csv_stays_text(tmp_path):
    wide = [[f"col{i}" for i in range(30)]] + [[f"{r}-{i}" for i in range(30)] for r in range(10)]
    with TestClient(app) as client:
        run = _run(client, _csv(tmp_path / "wide.csv", wide))
        assert run["status"] == "succeeded", run["error"]
        decisions = {x["subject"]: x for x in client.get(f"/api/runs/{run['id']}/decisions").json()}
        assert decisions["CSV layout"]["rule_id"] == "csv_as_text"
        assert decisions["document format"]["rule_id"] == "text_render"
