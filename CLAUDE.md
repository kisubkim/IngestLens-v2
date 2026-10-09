# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

IngestLens is a multi-agent RAG ingestion pipeline with a web UI. A user uploads a document (PDF, Office, or image). Agents detect the format and profile each page's content type, then pick parsers and a chunking strategy. The chunks are embedded into Qdrant. The UI shows progress, the evidence behind every decision, and the parse, chunk, embedding and search results.

The target deployment is an offline environment: no internet and no external APIs. Models are served by vLLM through OpenAI-compatible endpoints. License: MIT (`LICENSE`, `NOTICE.md`). `docs/HANDOFF.md` has the status, backlog and gotchas, `PROGRESS.md` is the dated work log; read them before larger changes and update them after. `docs/AGENTS.md` explains each agent's role, decision rules, thresholds and `rule_id`s for readers; when you change a rule, threshold or decision, update it too.

## PDF work goes through ToolPDF

This app contains no PDF library. Every PDF operation (normalizing documents to PDF, page features, text/table/figure extraction, crops for the VLM, page images) is done by **ToolPDF**, a separate program called over its HTTP API.
- **The API contract is ToolPDF's README.** Use only what it documents; do not copy its code or install its PDF library here. Keep `pymupdf`/`fitz` imports out of this repository.
- `backend/app/tools/toolpdf.py` is the only place that talks to it: `engine().info/text/profile/extract/render/normalize/health`. It maps the pipeline's parser names to ToolPDF's extraction modes (`vlm_ocr` → `ocr`, `vlm_figures` → `figures`, else `text`) and turns the engine's table-crop index back into the element. Add new PDF needs there, using documented endpoints.
- The parser names `pymupdf_text`/`pymupdf_tables` (in `strategy_rules.yaml`, decisions, tests) are only labels for ToolPDF's `text` mode, not library use; keep them, since stored runs and tests depend on them.
- Settings (`RAG_` env vars / `.env`): `RAG_TOOLPDF_URL` (default `http://127.0.0.1:8095`), `RAG_TOOLPDF_API_KEY`, `RAG_TOOLPDF_TRANSFER` (`http`: upload by sha256; `shared`: ToolPDF mounts this app's data dir as its shared folder and files are named by their stored relative path), `RAG_TOOLPDF_TIMEOUT_S`. Files outside the data dir are uploaded in either mode.
- `api/status.py` checks ToolPDF (`/v1/health`) and reports LibreOffice from it; without the engine no document can be processed.

## Conventions

- Answer the user in Korean. Docs (`README.md`, `docs/`, `evals/`), UI strings and commit messages are in Korean.
- `docs/HANDOFF.md` §11 says how to update it: refresh the status table and backlog after a milestone, add measurements to §7 together with their conditions, and add new gotchas to §9.
- Docker runs as Docker Engine inside the WSL distro `Ubuntu-24.04` on this Windows PC (no Docker Desktop). `start_test.bat`/`.sh` and `scripts/build_offline_bundle.py` call `wsl -d Ubuntu-24.04 -u root -- docker ...` when Windows has no `docker`. From Git Bash: `MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu-24.04 -u root --cd '<windows path>' -- docker ... < /dev/null`; for nested quotes write a script file and pass its `/mnt/c/...` path.
- On Windows, do not write Python containing `\n`, `\x..` escapes or backslash paths through a bash heredoc: they get mangled. Use the Edit/Write tools.
- `docker/certs/*.crt` (this PC's antivirus root certificate) is gitignored; never commit it.

## Commands

First-time setup (from the repo root): `python -m venv .venv`, `.venv/Scripts/pip install -r backend/requirements-dev.txt`, then `npm install && npm run build` in `frontend/`. On Windows, `setup_local.bat` does this for both repositories (cloning ToolPDF if missing), `start_local.bat` runs ToolPDF and the app in one window each (`INGESTLENS_PORT`, `TOOLPDF_PORT`, `INGESTLENS_HOST`, `TOOLPDF_DIR`), and `stop_local.bat` stops them by command line. `start_webui_test.bat`/`stop_webui_test.bat` run the Docker stack plus the Open WebUI test container (`owui-test`, volume `owui-test-data`) through `scripts/webui_test.sh up|status|down` inside WSL; already-running parts are skipped and it waits until every model answers. `docs/WINDOWS.md` is the end-user guide for a Windows PC; keep it in step with these scripts. In this tool environment run bat files as `.\name.bat` from PowerShell (the current folder is not searched), and through `Start-Process -WindowStyle Hidden` because the child windows keep the output pipe open.

Relative paths in `RAG_DATA_DIR`, `RAG_MODELS_FILE` (and the rules/evals paths) resolve against the repository root, not the working directory (`config.py`).

Run backend commands from `backend/` with the repo venv. Tests need ToolPDF: `tests/conftest.py` starts it from `TOOLPDF_HOME` (default: a `ToolPDF` folder with its own `.venv` next to this repository) on a free port, or uses a running one when `RAG_TOOLPDF_URL` is set.

```bash
../.venv/Scripts/python -m pytest -q                                   # all tests (~20 s), shared-folder transfer
RAG_TOOLPDF_TRANSFER=http ../.venv/Scripts/python -m pytest -q          # same tests over HTTP upload
../.venv/Scripts/python -m pytest -q tests/test_pipeline.py -k end_to_end  # one file / matching tests
../.venv/Scripts/python -m uvicorn app.main:app --port 8000            # API + built UI at / (ToolPDF must be running)
```

Run frontend commands from `frontend/`: `npm run dev` (Vite; proxies `/api` to :8000), `npm run build` (tsc + vite build into `dist/`, which FastAPI serves), and `npm run typecheck`.

Run these scripts from the repo root (they need a running ToolPDF, `RAG_TOOLPDF_URL`):
- `scripts/mock_vllm.py`: a mock vLLM server (`--port 8001 --latency 0.3`). It also serves `/v1/embeddings`, `/v1/rerank` and `/tokenize`. Its classifier always answers `diagram`.
- `scripts/bench_large.py --pdf <big.pdf>`: the large-document benchmark on any large PDF.
- `scripts/eval_profile.py`, `scripts/eval_retrieval.py`: evaluation, see `evals/README.md`. `scripts/_inproc.py` is their shared helper for running ingestion in-process.
- `scripts/eval_vlm.py`: VLM quality evaluation on the committed case sets, synthetic (`evals/vlm/`) and 10 real public documents (`evals/samples/`, third-party licenses in `SOURCES.md`; add only redistributable sources). Scoring is in `app/tools/vlm_checks.py`. Results are JSON files in `evals/results/vlm/` (committed), compared on the "VLM 평가 비교" screen (`/#evals`, `api/evals.py`). The dataset version hashes the expectations and 40-dpi page renders from ToolPDF.
- `scripts/build_offline_bundle.py`: builds the offline deployment bundle (`release/`). `deploy/` holds the server side. It copies ToolPDF's own release folder (made by ToolPDF's `docker/release.sh`; newest `$TOOLPDF_DIR/release/toolpdf-*` or `--toolpdf-release`) unchanged into `toolpdf/`: images plus the ToolPDF and PyMuPDF sources the AGPL requires, so never trim it. `deploy/docker-compose.yml` runs `toolpdf` (shared-folder mode, no published port) next to the app; `singularity.sh` starts pdf → model → app and the bundle's `singularity.env` gets a random `TOOLPDF_API_KEY`. Production keeps the VLM on an existing vLLM and runs embedding + rerank in `docker/model-server/server.py` (one process, both models; vLLM-compatible `/v1/embeddings`, `/v1/rerank`, `/tokenize`, `/v1/models`). `--singularity` also converts images to `.sif`; `deploy/singularity.sh` runs them without root or Docker (host network). The app image's CMD uses `--app-dir` and `INGESTLENS_PORT` because Singularity ignores WORKDIR and port mappings.
- `docker-compose.yml`: a local stack with real models: ToolPDF (built from `TOOLPDF_DIR`, default `../ToolPDF`, sharing the data folder), app, Ollama with GPU, and the model server as a CPU reranker. The model volumes are named `ingestlens_ollama`/`ingestlens_hf`. From the host, use `config/models.docker-host.yaml`.

Other configuration (`RAG_` env vars or `.env`): `RAG_DATA_DIR` (default `./data`), `RAG_DB_URL`, `RAG_QDRANT_URL`, `RAG_MODELS_FILE`. `config/models.yaml` is a committed template with empty endpoints; put real `base_url`/`api_key` values in a `*.local.yaml` copy (gitignored).

## Architecture

**Pipeline** (`backend/app/graph/pipeline.py`): a linear LangGraph graph with the steps `intake → profile → strategy → parse → chunk → embed`. Each agent is in `backend/app/agents/<step>.py`. `_wrap()` adds the step_started/step_finished events and updates `Run.current_step`. Runs are in-process `asyncio` tasks (`start_run`), and `cancel_run` cancels them. A per-loop FIFO lock makes runs execute one at a time in start order. `POST /api/documents/runs` queues several documents in one call. `api/ingest.py` is the API for other systems: `POST /api/ingest`, and `PUT /api/openwebui/process`, which follows the Open WebUI External document loader contract (raw body plus `X-Filename`; waits for the run and returns `[{page_content, metadata}]`; metadata `page` is 0-based, `page_label` and `pages` are 1-based). Both are guarded by `RAG_API_KEY`. `deploy/OPENWEBUI.md` is the Open WebUI guide; `deploy/openwebui_page_images.py` is an Open WebUI filter that shows the pages behind an answer using `GET /api/chunks/{id}/preview.png`. When the server starts, it marks any run left `queued` or `running` as failed.

**State lives in the DB, not in the graph state.** `PipelineState` carries only ids, paths, the profile summary, the plan, and the Office `hints`. Page profiles, elements, and chunks are written to SQLite or Postgres tables (`models.py`), and the next agent reads them back. New nullable columns are added automatically at startup (`db._add_missing_columns`). `Document.path` and `pdf_path` are stored relative to the data dir: write them with `settings.stored_path()` and open them with `settings.resolve()`.

**Storage settings** (`api/settings.py`) write `data_dir`, `db_url` and `qdrant_url` to `RAG_SETTINGS_FILE`. Env vars and `.env` override that file and lock the field in the UI. Changing settings needs `RAG_API_KEY` when it is set, otherwise a local client (`api/auth.py` `is_local`, `RAG_ADMIN_HOSTS`).

**Home screen** (`api/overview.py`), **deletion** (`tools/purge.py`: DB rows, Qdrant points, BM25 cache and the document's `uploads/`, `converted/`, `pages/` folders; add any new table or per-document folder to the purge), **backend status** (`api/status.py`, cached 5 s; add a check for every new external dependency). The UI shows document names without the `<uuid>_` prefix Open WebUI adds (`displayName` in `frontend/src/api.ts`).

**Observability contract**: agents report only through `events.emit_event()` and `events.record_decision()` (DB first, then SSE; safe from threads). A `Decision` stores `rule_id`, `inputs`, `alternatives` (with the reason each was rejected), `confidence`, and `reasoning`; the UI shows it as "근거". **Every new automatic choice needs a `record_decision` call**, including each fallback.

**Everything is normalized to PDF** in intake (by ToolPDF `normalize`/`info`): images become one-page PDFs; Office files go through LibreOffice when ToolPDF reports it, otherwise (and for xlsx by default, `config/strategy_rules.yaml` `office`) through ToolPDF's native renderer. Both paths return `hints` (docx heading styles, slide titles, speaker notes, pptx chart data); the parser applies them. Legacy `.doc`, `.ppt`, `.hwp` need LibreOffice on ToolPDF. Bboxes are PDF points; pages are 0-based internally, 1-based in the UI.

**Rules are data**: `config/strategy_rules.yaml` holds `profiler.rules` (first match wins, evidence stored per page), `strategy.parsers` (page label → parser), chunking parameters, `parse` (window size, windows in flight, figures, captions, tables) and `office`. The "에이전트 규칙" screen (`/#rules`, `api/rules.py`, `frontend/src/RulesView.tsx`) edits them live: every editable value is declared once in `tools/rules_schema.py` `FIELDS` (agent, label, help, range; the screen is drawn from it and `validate()` checks saves), changes are stored as an override of only the changed keys in `<data_dir>/strategy_rules.override.yaml`, and `config.rules_cfg()` (shipped file merged with the override; dicts merge, lists replace) is cache-cleared on save so the next agent step uses them. An unusable override is ignored (shipped rules apply) and reported. Always read rules through `rules_cfg()`; a new rule value needs a `FIELDS` entry, and `rules_version()` is recorded in each run's plan. `config/models.yaml` holds the endpoints for `embedding`, `reranker` and `vlm`; an empty `base_url` degrades instead of failing and records the fallback (VLM parsers → `pymupdf_text`, embedding → `dev-hash`, rerank off).

**Profiling** (`agents/profiler.py`): ToolPDF measures page features; `tools/pdf.py` `classify()` applies the rules. Pages with low confidence (at most 10) get a VLM second opinion on a ToolPDF page render.

**Parsing** (`agents/parser.py`) works in page windows: ToolPDF `extract` returns each window's elements, figure regions and crops; the VLM calls for a window run while later windows are prepared (`parse.windows_in_flight`). A per-loop semaphore in `tools/vlm.py` bounds VLM concurrency.
- `vlm_ocr` sends the whole page; the Markdown answer is split into title/text/table elements (`tools/vlm_output.py`), with the text layer as fallback.
- Figure crops are described; the figure prompt's first line is `TYPE: chart|diagram|...`, and a large chart relabels the page to `chart`. A whole-page figure sorts after the page's own text.
- Captions are moved into the nearest figure or table element (`tools/figures.py`). Ruled tables with many empty cells are re-extracted by the VLM.
- An answer cut off at `vlm.max_tokens` is retried once with `vlm.max_tokens_retry` (decision `vlm_truncated_retry`). VLM failures fall back per page and never fail the run.

**Chunking** (`tools/chunking.py`) works on elements. Titles set the section; `table`/`figure` elements are atomic, long tables are split by rows with the header repeated; the `page` strategy (slides, sheets) breaks at page boundaries. Budgets are in model tokens, converted with `chars_per_token` measured via `/tokenize` on ToolPDF's text sample (default 2.5). `strategy.min_tokens` (128) then merges chunks under it into a neighbour of the same section (`merge_short`, never across pages in `page` mode, up to target + min), keeping all pages/bboxes and skipping repeated overlap; decision `chunk_merge`. A title whose first line is only a number ("8.6") names the section with its next line (`section_name`). Chunking belongs to IngestLens: Open WebUI must not re-split or merge (`deploy/OPENWEBUI.md` 4-4).

**Retrieval** (`agents/retriever.py`): dense (filtered by `run_id`), BM25 (`tools/lexical.py`, Hangul bigrams, cached per run), `hybrid` (RRF k=60), optional reranker. Every hit returns a per-stage `scores` breakdown; keep it when you change ranking. **Vector store** (`tools/vectorstore.py`): embedded Qdrant by default; always use `vectorstore.client()`.

**Prompt contracts**: `tools/vlm.py` `PROMPTS` defines the answer formats the code parses, and `scripts/mock_vllm.py` imitates them. **If you change a prompt, change its parser and the mock together.**

## Testing notes

- `tests/conftest.py` sets `RAG_DATA_DIR` and `RAG_SETTINGS_FILE` to temp paths and starts ToolPDF before any `app` import (settings are read at import). TestClient's default client host is not loopback; pass `client=("127.0.0.1", 50000)` for local-only endpoints.
- `sample_pdf` is the committed `tests/fixtures/sample.pdf` (6 pages: text, text, table, diagram, scanned, text with figure and caption) with a unique trailing comment per test, because uploads deduplicate by sha256. Small PDFs are written without a PDF library by `tests/minipdf.py`. `tests/office_fixtures.py` builds docx, pptx and xlsx files.
- Office/LibreOffice paths are tested by monkeypatching `engine().health` (LibreOffice present or not) and `engine().normalize`.
- Mock the VLM with `_mock_vlm()` in `tests/test_pipeline.py`. SQLite drops timezones, so `to_dict` attaches UTC. The VLM semaphore is per event loop because TestClient uses a new loop per test.

## Status and next steps (2026-10-09)

- Code and tests (78, both transfer modes) work against ToolPDF; the Docker stack runs with ToolPDF in shared-folder mode.
- License is MIT; `NOTICE.md` explains ToolPDF (AGPL-3.0) as a separate program. Docs must not describe this repository as derived from another IngestLens repository.
- Docs describe the ToolPDF structure. Verified on this PC (2026-10-09): the Docker bundle (WSL Docker), the `--singularity` bundle (`singularity.sh start` in an Apptainer container, model server on CPU), and the Windows path with Windows Ollama 0.40.1 (`docs/WINDOWS.md` §3). Not yet: the offline server and Singularity `--nv`.
- Pushed to `https://github.com/kisubkim/IngestLens-v2` (`origin/main`, public, MIT). Next: the bundle on the offline server (`docs/HANDOFF.md` §6).
- `tests/fixtures/sample.pdf` page 5 is a blank grey "scan": a real VLM returns an empty answer there (`vlm_error`, expected). Check real OCR with `evals/samples/ko_scan_kostat.pdf`.
