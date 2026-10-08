import asyncio
import time

from fastapi.testclient import TestClient

from app.main import app

from .minipdf import one_line_pdf


def _wait(client: TestClient, run_id: str, timeout: float = 60) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in ("succeeded", "failed", "cancelled"):
            return run
        time.sleep(0.2)
    raise TimeoutError(run)


def test_upload_batch(tmp_path, sample_pdf):
    other = one_line_pdf(tmp_path / "other.pdf", "second file")

    with TestClient(app) as client:
        with sample_pdf.open("rb") as a, other.open("rb") as b:
            res = client.post(
                "/api/documents/batch",
                files=[
                    ("files", ("sample.pdf", a, "application/pdf")),
                    ("files", ("other.pdf", b, "application/pdf")),
                ],
            )
        assert res.status_code == 200, res.text
        body = res.json()
        assert [d["filename"] for d in body] == ["sample.pdf", "other.pdf"]
        assert [d["duplicate"] for d in body] == [False, False]
        names = {d["filename"] for d in client.get("/api/documents").json()}
        assert {"sample.pdf", "other.pdf"} <= names

        with sample_pdf.open("rb") as a, sample_pdf.open("rb") as b:
            again = client.post(
                "/api/documents/batch",
                files=[
                    ("files", ("copy-a.pdf", a, "application/pdf")),
                    ("files", ("copy-b.pdf", b, "application/pdf")),
                ],
            ).json()
        assert [d["duplicate"] for d in again] == [True, True]
        assert again[0]["id"] == again[1]["id"] == body[0]["id"]
        assert client.post("/api/documents/batch").status_code == 422


def test_batch_runs_execute_in_order(tmp_path, sample_pdf):
    other = one_line_pdf(tmp_path / "queued.pdf", "queued file")

    with TestClient(app) as client:
        with sample_pdf.open("rb") as a, other.open("rb") as b:
            docs = client.post(
                "/api/documents/batch",
                files=[("files", ("sample.pdf", a, "application/pdf")), ("files", ("queued.pdf", b, "application/pdf"))],
            ).json()
        ids = [d["id"] for d in docs]
        runs = client.post("/api/documents/runs", json={"document_ids": ids}).json()
        assert [r["document_id"] for r in runs] == ids
        assert [r["status"] for r in runs] == ["queued", "queued"]

        first, second = (_wait(client, r["id"]) for r in runs)
        assert first["status"] == second["status"] == "succeeded"
        assert second["started_at"] >= first["finished_at"]

        assert client.post("/api/documents/runs", json={"document_ids": []}).status_code == 400
        assert client.post("/api/documents/runs", json={"document_ids": ["nope"]}).status_code == 404


def test_cancel_queued_run(sample_pdf, monkeypatch):
    _mock_vlm(monkeypatch, delay=30)
    with TestClient(app) as client:
        with sample_pdf.open("rb") as f:
            doc = client.post("/api/documents", files={"file": ("sample.pdf", f, "application/pdf")}).json()
        busy, waiting = client.post("/api/documents/runs", json={"document_ids": [doc["id"]]}).json() + [
            client.post(f"/api/documents/{doc['id']}/runs").json()
        ]
        deadline = time.time() + 10
        while client.get(f"/api/runs/{busy['id']}").json()["status"] != "running" and time.time() < deadline:
            time.sleep(0.05)
        assert client.get(f"/api/runs/{waiting['id']}").json()["status"] == "queued"
        assert client.post(f"/api/runs/{waiting['id']}/cancel").json() == {"cancelled": True}
        run = _wait(client, waiting["id"], timeout=5)
        assert run["status"] == "cancelled" and run["started_at"] is None
        client.post(f"/api/runs/{busy['id']}/cancel")
        assert _wait(client, busy["id"], timeout=5)["status"] == "cancelled"


def test_end_to_end(sample_pdf):
    with TestClient(app) as client:
        with sample_pdf.open("rb") as f:
            doc = client.post("/api/documents", files={"file": ("sample.pdf", f, "application/pdf")}).json()
        with sample_pdf.open("rb") as f:
            assert client.post("/api/documents", files={"file": ("again.pdf", f, "application/pdf")}).json()["duplicate"]

        run = client.post(f"/api/documents/{doc['id']}/runs").json()
        run = _wait(client, run["id"])
        assert run["status"] == "succeeded", run["error"]

        summary = run["summary"]
        assert summary["profile"]["label_counts"] == {"text": 3, "table": 1, "diagram": 1, "scanned": 1}
        assert summary["plan"]["chunking"]["strategy"] == "section"
        assert summary["chunk"]["count"] > 0
        assert summary["embed"]["count"] == summary["chunk"]["count"]

        events = client.get(f"/api/runs/{run['id']}/events").json()
        started = [e["step"] for e in events if e["type"] == "step_started"]
        assert started == ["intake", "profile", "strategy", "parse", "chunk", "embed"]
        assert events[-1]["type"] == "run_finished"

        subjects = {d["subject"] for d in client.get(f"/api/runs/{run['id']}/decisions").json()}
        assert {"document format", "document profile", "parser selection", "chunking", "embedding model"} <= subjects

        tables = [e for e in client.get(f"/api/runs/{run['id']}/elements", params={"page": 2}).json() if e["type"] == "table"]
        assert tables and "r0c0" in tables[0]["content"]

        # SSE replays the finished run and closes.
        with client.stream("GET", f"/api/runs/{run['id']}/stream") as r:
            body = "".join(r.iter_text())
        assert "run_finished" in body

        hits = client.post("/api/search", json={"query": "Quarterly results r3c2", "document_id": doc["id"]}).json()["hits"]
        assert hits and 2 in hits[0]["pages"]

        assert client.get(f"/api/documents/{doc['id']}/pages/0.png").headers["content-type"] == "image/png"

        md = client.get(f"/api/runs/{run['id']}/parsed.md").text
        assert md.startswith("<!-- page 1 -->")
        assert "## 1. Introduction" in md
        assert "<!-- page 3 -->" in md and "r0c0" in md

        pages = client.get(f"/api/runs/{run['id']}/pages").json()
        assert pages[4]["features"]["evidence"]["conditions"]["max_text_chars"]["threshold"] == 50
        vlm_skip = client.get(f"/api/runs/{run['id']}/decisions", params={"subject": "VLM second opinion"}).json()
        assert [d["choice"] for d in vlm_skip] == ["skipped"]
        enrich = client.get(f"/api/runs/{run['id']}/decisions", params={"subject": "figure enrichment"}).json()
        assert enrich[0]["choice"].startswith("skipped") and enrich[0]["rule_id"] == "vlm_not_configured"


OCR_MD = "# 스캔 제목\n\n스캔 본문 문장.\n\n| a | b |\n|---|---|\n| 1 | 2 |"
CHART_MD = "TYPE: chart\n| q | v |\n|---|---|\n| Q1 | 10 |"


def _mock_vlm(monkeypatch, delay: float = 0.0):
    from app.tools import vlm

    orig_init = vlm.VLMClient.__init__
    calls = []

    def init(self):
        orig_init(self)
        self.enabled = True

    async def ask(self, image, prompt, max_tokens=None):
        assert image[:2] == b"\xff\xd8" or image.startswith(b"\x89PNG")
        calls.append(prompt)
        if delay:
            await asyncio.sleep(delay)
        if prompt == vlm.PROMPTS["ocr"]:
            return vlm.VLMResult(OCR_MD, "stop", 0.1)
        if prompt == vlm.PROMPTS["figure"]:
            return vlm.VLMResult(CHART_MD, "stop", 0.1)
        return vlm.VLMResult('{"label": null}', "stop", 0.1)

    monkeypatch.setattr(vlm.VLMClient, "__init__", init)
    monkeypatch.setattr(vlm.VLMClient, "ask", ask)
    return calls


def test_truncated_vlm_answer_is_retried_with_larger_limit(monkeypatch):
    from collections import Counter

    from app.agents import parser
    from app.tools import vlm

    limits = []

    class FakeVLM:
        cfg = {"max_tokens": 100, "max_tokens_retry": 300}

        async def ask(self, image, prompt, max_tokens=None):
            limits.append(max_tokens)
            if max_tokens is None:  # first call uses the configured limit and is cut off
                return vlm.VLMResult("# 표\n\n| a | b |\n|---|---|\n| 1 |", "length", 1.0)
            return vlm.VLMResult("# 표\n\n| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |", "stop", 2.0)

    decisions = []
    monkeypatch.setattr(parser, "record_decision", lambda *a, **k: decisions.append((a, k)))
    monkeypatch.setattr(parser, "emit_event", lambda *a, **k: None)
    job = {"kind": "ocr", "image": b"\xff\xd8x", "bbox": [0, 0, 100, 100]}
    preps = {0: {"elements": [], "fallback": [], "jobs": [job]}}
    stats = Counter()
    asyncio.run(parser._run_jobs(FakeVLM(), preps, stats))
    assert limits == [None, 300]
    assert job["retry"] == {"max_tokens": 100, "retry_max_tokens": 300, "first_seconds": 1.0}

    pcfg = {"captions": {"pattern": "^그림", "max_gap": 40}, "tables": {"max_empty_cell_ratio": 0.5}}
    els = parser._merge("run", 0, "scanned", preps[0], pcfg, stats)
    assert "| 3 | 4 |" in next(e["content"] for e in els if e["type"] == "table")
    assert stats["vlm_retried"] == 1 and stats["vlm_truncated"] == 0
    (args, kw), = decisions
    assert kw["rule_id"] == "vlm_truncated_retry" and kw["inputs"]["truncated_again"] is False


def test_vlm_parsers_with_mock(sample_pdf, monkeypatch):
    _mock_vlm(monkeypatch)
    with TestClient(app) as client:
        with sample_pdf.open("rb") as f:
            doc = client.post("/api/documents", files={"file": ("sample.pdf", f, "application/pdf")}).json()
        run = _wait(client, client.post(f"/api/documents/{doc['id']}/runs").json()["id"])
        assert run["status"] == "succeeded", run["error"]
        assert run["summary"]["plan"]["parser_usage"] == {"pymupdf_text": 3, "pymupdf_tables": 1, "vlm_figures": 1, "vlm_ocr": 1}
        parse = run["summary"]["parse"]
        assert parse["vlm_errors"] == 0 and parse["figures_described"] == 2 and parse["pages_relabeled"] == 1

        def els(page):
            return client.get(f"/api/runs/{run['id']}/elements", params={"page": page}).json()

        # diagram page: no figure region found -> whole page described; chart answer relabels the page
        fig = [e for e in els(3) if e["type"] == "figure"]
        assert len(fig) == 1 and fig[0]["meta"]["figure_type"] == "chart" and fig[0]["meta"]["region_source"] == "page"
        assert els(3)[-1]["type"] == "figure"  # whole-page figure after the page's native text
        pages = client.get(f"/api/runs/{run['id']}/pages").json()
        assert pages[3]["label"] == "chart" and pages[3]["rule_id"] == "vlm_figure_type"

        # scanned page: Markdown transcription split into structure
        assert [(e["type"], e["source_tool"]) for e in els(4)] == [("title", "vlm_ocr"), ("text", "vlm_ocr"), ("table", "vlm_ocr")]

        # text page with embedded figure: described at its bbox, caption moved into it
        page5 = els(5)
        fig = next(e for e in page5 if e["type"] == "figure")
        assert fig["bbox"] == [72.0, 380.0, 420.0, 600.0]
        assert fig["meta"]["caption"].startswith("그림 1.")
        assert not any(e["content"].startswith("그림 1.") for e in page5 if e["type"] == "text")

        chunks = client.get(f"/api/runs/{run['id']}/chunks").json()["items"]
        assert any(c["element_types"] == ["figure"] and "그림 1." in c["text"] for c in chunks)


def test_cancel_run(sample_pdf, monkeypatch):
    _mock_vlm(monkeypatch, delay=30)
    with TestClient(app) as client:
        with sample_pdf.open("rb") as f:
            doc = client.post("/api/documents", files={"file": ("sample.pdf", f, "application/pdf")}).json()
        run_id = client.post(f"/api/documents/{doc['id']}/runs").json()["id"]
        deadline = time.time() + 10
        # The slow mock VLM holds the run in profile (second opinion) and parse; cancel while it waits there.
        while client.get(f"/api/runs/{run_id}").json()["current_step"] not in ("profile", "parse") and time.time() < deadline:
            time.sleep(0.05)
        time.sleep(0.3)
        assert client.post(f"/api/runs/{run_id}/cancel").json() == {"cancelled": True}
        run = _wait(client, run_id, timeout=5)
        assert run["status"] == "cancelled"
        assert client.post(f"/api/runs/{run_id}/cancel").status_code == 409
