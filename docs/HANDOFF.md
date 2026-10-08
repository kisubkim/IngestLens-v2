# HANDOFF: 다른 환경에서 이어서 개선하기 위한 문서

최종 갱신: 2026-10-09. 이 문서는 현재 상태, 새 환경 준비, 실제 모델 연결 절차, 튜닝 방법, 남은 일, 개발 중 겪은 함정을 정리한다.
원래 계획은 `docs/PLAN.md`, 평가 방법은 `evals/README.md`에 있다.

---

## 1. 한눈에 보기

**무엇**: 웹에서 문서를 올리면 6개 agent가 LangGraph 파이프라인으로 처리한다. 형식 판별 → 페이지 성격 분석 → 파서·청킹 전략 결정 → 파싱(VLM 포함) → 청킹 → 임베딩(Qdrant). 모든 자동 결정의 근거(규칙, 입력값, 대안, 신뢰도)를 저장하고 웹 화면에 보여준다.

**대상 환경**: 직접 운영하는 서버. 외부 API를 쓰지 않고 직접 띄운 vLLM(OpenAI 호환 API)만 호출하므로 인터넷이 없는 환경에서도 동작한다.

**PDF 엔진**: 이 저장소에는 PDF 라이브러리가 없다. PDF로 바꾸기, 쪽 특징 측정, 텍스트·표·그림 추출, VLM용 잘라낸 이미지, 쪽 이미지는 모두 별도 프로그램 [ToolPDF](https://github.com/kisubkim/ToolPDF)(AGPL-3.0)의 HTTP API로 한다. 호출하는 곳은 `backend/app/tools/toolpdf.py` 하나이고, API 규약은 ToolPDF의 README다. 이 저장소는 MIT다(`NOTICE.md`).

| 마일스톤 | 상태 | 내용 |
|---|---|---|
| M1 골격 | 완료 | FastAPI, SQLite, LangGraph, SSE, 진행 화면, 텍스트 PDF 전체 경로 |
| M2 분석·전략 | 완료 | 페이지 feature, 규칙 분류, VLM 2차 판단, 결정 근거, 파싱 리포트 화면 |
| M3 VLM 파싱 | 완료 | OCR, 그림 영역 설명, 캡션 연결, 표 재추출, 프로세스 풀, 150MB 벤치마크, 실행 취소 |
| M4 Office | 완료 | LibreOffice 경로와 자체 렌더링 경로, 헤딩·노트·차트 데이터 힌트, 시트 표 헤더 반복 |
| M5 결과 화면 | 완료 | 청크, 임베딩(PCA, 이웃), 검색(dense/BM25/hybrid, rerank, 단계별 점수) |
| M6 튜닝 | 도구만 완료 | 평가 스크립트, 합성 세트, `/tokenize` 토큰 보정, `table_text_share` 규칙. 실제 데이터 튜닝은 남음 |
| 실제 모델 검증 (10-04) | 완료 | Ollama(qwen2.5vl, bge-m3)와 rerank 서버로 로컬 스택, VLM 평가 도구와 비교 화면, 실제 공개 문서 10종 평가 세트 |
| 화면 보강 (10-04) | 완료 | 첫 화면 현황판, 백엔드 상태 표시, 문서·전체 삭제, 파싱 리포트 통계 차트 |
| 오프라인 배포 (10-05~07) | 완료 | 배포 묶음(Docker + Singularity `.sif`), 임베딩·rerank 단일 프로세스 모델 서버, Open WebUI v0.11.3 연동 검증 |
| PDF 엔진 ToolPDF (10-08~09) | 완료 | 모든 PDF 처리를 ToolPDF HTTP API로, 파일 전송 두 방식(HTTP 업로드, 공유 폴더), Docker 스택과 배포 묶음(Docker, Singularity)에 ToolPDF 포함, MIT 라이선스 |

### 검증 수준: 이어받는 사람이 가장 먼저 알아야 할 것

| 항목 | 검증 방법 | 실제 환경 검증 |
|---|---|---|
| 파이프라인 전체, UI 6개 탭, 여러 파일 순차 실행, HTTP 수집 API, 저장 위치 설정, VLM 평가 비교, 첫 화면, 상태 표시, 삭제 | 백엔드 테스트 61개(실제 ToolPDF를 띄워 공유 폴더 방식과 HTTP 방식 각각), 화면은 headless Edge 캡처와 DevTools 조작으로 확인 | 개발 PC(Windows)의 Docker 스택(ToolPDF 공유 폴더 방식). 오프라인 서버에서 사용자가 sif로 앱을 실행해 봄(2026-10-06): 문서 하나 삭제가 401로 실패하는 버그를 찾아 고침 |
| PDF 엔진 ToolPDF | 테스트가 ToolPDF를 직접 띄움(`tests/conftest.py`), Docker 스택 | ToolPDF를 넣은 배포 묶음은 아직 오프라인 서버에서 시험하지 않음 |
| VLM (OCR, 그림, 표, 분류) | 코드 mock, HTTP mock, **Ollama `qwen2.5vl:7b`** (Docker, 2026-10-04) | 실제 VL 모델로 응답 형식 확인: `TYPE:` 첫 줄, OCR 제목 분리, 차트 표, 분류 JSON 모두 동작. 합성 세트에서 7b 92%·3b 86%, 실제 공개 문서 10종에서 7b 92%·3b 51%(7절). **vLLM과 큰 모델로는 아직 안 함** |
| 임베딩 | dev-hash, mock HTTP, **Ollama `bge-m3`** | 합성 세트로 측정(7절). vLLM으로는 안 함 |
| 임베딩 + reranker 모델 서버 | **`docker/model-server/server.py`** (transformers, 프로세스 하나에 bge-m3와 bge-reranker-v2-m3) | 이 PC의 GPU에서 확인: GPU 프로세스 1개, Ollama bge-m3와 벡터 일치(코사인 1.0), 합성 세트 측정(7절). 운영 GPU(Exclusive_Process 모드)에서는 아직 |
| `/tokenize` | mock HTTP, 모델 서버 | 모델 서버의 `/tokenize`로 실제 토큰 비율 측정 확인(2.185 등). vLLM으로는 안 함 |
| LibreOffice 변환 | `engine().health`/`normalize`를 바꿔 끼운 테스트 | **LibreOffice로 실제 변환해 본 적 없음** (개발 PC의 ToolPDF에 미설치) |
| Office 자체 렌더링 (ToolPDF) | 생성한 docx/pptx/xlsx | 실제 문서로 검증 안 함 |
| 150MB 대용량 | `bench_large.py --pdf` | ToolPDF 구조로는 아직 측정 안 함 |
| Linux(운영 서버) | Docker 이미지(python:3.12-slim), Apptainer 1.4.5 컨테이너 | Linux 컨테이너에서 파이프라인 전체 동작 확인. 오프라인 서버에서 sif로 앱 실행됨(사용자 시험) |
| 오프라인 배포 묶음 | `build_offline_bundle.py` | 이미지를 지우고 묶음만으로 설치·실행, `--network none` 컨테이너에서 처리·검색, Singularity `.sif`로 처리·검색까지 확인(ToolPDF를 넣기 전, 10-05~06). ToolPDF를 넣은 묶음은 10-09에 Docker로 설치·처리 확인(7절). Singularity `--nv`(GPU)는 Windows에서 시험 불가 |
| Open WebUI 연동 | Open WebUI v0.11.3 컨테이너 | 파일 추가 → IngestLens 처리 → 지식 베이스 → LLM 답변과 출처(쪽 번호)까지 확인(`deploy/OPENWEBUI.md`). 쪽 이미지 필터로 답변의 썸네일 줄과 출처 팝업 이미지까지 가로·세로 문서로 화면에서 확인(10절) |

---

## 2. 폴더 지도

```
IngestLens-v2/
  backend/app/
    agents/     intake, profiler, strategy, parser, chunker, embedder, retriever (+ common)
    graph/      pipeline.py: LangGraph 정의, 실행/취소
    api/        chunks(청크 영역 칠한 쪽 이미지), documents, runs(이벤트·SSE·결정·페이지·요소·청크·임베딩·이웃), search, ingest(외부 수집·Open WebUI 로더), settings(저장 위치), evals(VLM 평가 결과), status(백엔드 상태), overview(첫 화면 현황), auth
    tools/      toolpdf(PDF 엔진 클라이언트, 유일한 연결 지점), pdf(쪽 분류 규칙), figures, office(형식 판별), vlm, vlm_output, vlm_checks, embedding, reranker, lexical, chunking, vectorstore, purge
    models.py   Document, Run, Event, Decision, PageProfile, Element, Chunk
    events.py   emit_event / record_decision + SSE fan-out
  backend/tests/   pytest 61개 (conftest가 ToolPDF를 띄움, fixtures/sample.pdf, minipdf.py로 만드는 작은 PDF, office_fixtures)
  config/     models.yaml (모델 endpoint 템플릿), models.docker.yaml (Docker 스택용), strategy_rules.yaml (모든 규칙과 파라미터)
  docker/     app.Dockerfile, model-server/ (임베딩+rerank 모델 서버: server.py, 개발용 Dockerfile, 운영용 release.Dockerfile), certs/ (추가 신뢰 CA)
  docker-compose.yml   로컬 검증 스택: app + ToolPDF(../ToolPDF에서 빌드) + Ollama + reranker(모델 서버, CPU)
  deploy/     오프라인 서버용: docker-compose.yml(app + ToolPDF), models.yaml, install.sh, model-server.sh, singularity.sh, README.md(설치), OPENWEBUI.md(연동), openwebui_page_images.py(Open WebUI 쪽 이미지 필터)
  start_test.bat/.sh, stop_test.bat/.sh   로컬 Docker 스택 시작·중지 (Windows는 WSL의 Docker Engine, 3-1)
  PROGRESS.md 날짜별 진행 기록
  frontend/   React + Vite. build 결과물 dist/는 FastAPI가 / 경로로 서빙
  scripts/    mock_vllm, bench_large, eval_profile, eval_retrieval, eval_vlm, build_offline_bundle, _inproc(평가 스크립트 공용)
  evals/      synthetic/ (합성 평가 세트), vlm/ (합성 VLM 평가 세트), samples/ (실제 공개 문서 10종, 출처는 SOURCES.md), reports/ (측정 보고서), results/vlm/ (VLM 평가 결과 JSON, 화면에서 비교), README.md
  docs/       PLAN.md, HANDOFF.md (이 문서), EMBEDDING_MODELS.md (임베딩 모델 후보와 교체 방법)
../ToolPDF/   PDF 엔진(별도 저장소, AGPL-3.0). 테스트, Docker 스택, 배포 묶음이 이 위치를 기본으로 찾는다
```

---

## 3. 새 환경에서 시작하기

### 3-1. 개발 PC (인터넷 가능)

ToolPDF를 이 저장소 옆에 준비한다. 테스트는 그 폴더의 `.venv`로 ToolPDF를 직접 띄운다(`TOOLPDF_HOME`으로 위치를 바꿀 수 있다).

```bash
git clone https://github.com/kisubkim/ToolPDF ../ToolPDF
(cd ../ToolPDF && python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt)
```

```bash
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements-dev.txt     # Linux: .venv/bin/pip
cd frontend && npm install && npm run build && cd ..
cd backend && ../.venv/Scripts/python -m pytest -q             # 61 passed 확인 (공유 폴더 방식)
RAG_TOOLPDF_TRANSFER=http ../.venv/Scripts/python -m pytest -q # 61 passed 확인 (HTTP 방식)
../ToolPDF/.venv/Scripts/python -m uvicorn --app-dir ../ToolPDF toolpdf.server:app --port 8095 &   # 서버를 띄울 때는 ToolPDF 먼저
../.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

**Windows에서 Docker 스택(실제 모델)을 쓰려면 WSL의 Docker Engine**을 준비한다. 2026-10-08에 Docker Desktop을 지우고 이 방식으로 옮겼다. Docker Desktop은 엔진이 멈추는 일이 잦았고, WSL 메모리 한도(9GB) 때문에 Ollama가 메모리 부족으로 죽었다.

1. `wsl --install -d Ubuntu-24.04 --no-launch`. 명령은 `wsl -d Ubuntu-24.04 -u root -- <명령>`으로 root로 실행한다.
2. Ubuntu 안에 Docker 공식 apt 저장소로 `docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin`을 설치한다. 배포판은 systemd로 Docker를 띄운다.
3. GPU: NVIDIA 저장소에서 `nvidia-container-toolkit`을 설치하고 `nvidia-ctk runtime configure --runtime=docker`, `systemctl restart docker`. `docker run --rm --gpus all ubuntu:24.04 nvidia-smi`로 확인한다. Windows의 NVIDIA 드라이버만 있으면 되고, WSL 안에 드라이버를 설치하지 않는다.
4. `%USERPROFILE%\.wslconfig`(이 PC의 값):
   ```ini
   [general]
   instanceIdleTimeout=-1   # 없으면 wsl 명령이 끝날 때 배포판이 꺼지고 Docker도 멈춘다
   [wsl2]
   memory=24GB              # 기본은 PC 메모리의 절반. 9GB에서 Ollama가 OOM으로 죽었다
   vmIdleTimeout=-1
   ```
   바꾼 뒤 `wsl --shutdown`.
5. `start_test.bat`으로 시작한다. 배포판이 꺼져 있으면 이 스크립트가 깨운다. Windows가 다시 켜진 뒤 자동으로 시작하지는 않는다(필요할 때 깨워서 쓴다).

배포 묶음(`scripts/build_offline_bundle.py`)도 Windows에 `docker`가 없으면 같은 WSL 엔진으로 빌드한다. 경로 인자는 `/mnt/d/...`로 바꿔 넘긴다.

### 3-2. 오프라인 환경 반입

**권장: Docker 배포 묶음** (`deploy/README.md`). 인터넷 되는 PC에서 ToolPDF 저장소의 `bash docker/release.sh`로 ToolPDF 배포 폴더를 만든 뒤, 이 저장소에서 `python scripts/build_offline_bundle.py`로 파일 하나(`release/ingestlens-<버전>-offline.tar`, 약 380MB)를 만들어 반입한다. 서버에서는 `tar xf` 후 `./install.sh`만 하면 된다.
- 묶음 내용: 앱 이미지, `toolpdf/`(ToolPDF 배포 폴더 그대로: Docker 이미지, `.sif`, ToolPDF·PyMuPDF 소스, 라이선스), `docker-compose.yml`(app + toolpdf), `models.yaml`, `.env`, 설치 스크립트, 모델 서버(`model-server/server.py`, `model-server.sh`), 무결성 파일. 모델 가중치는 따로 받아 반입한다.
- `toolpdf/` 폴더는 AGPL 소스 제공을 위한 것이라 묶음을 넘길 때 빼지 않는다(`NOTICE.md` 2절).
- **모델 배치(운영 조건 기준):** VLM은 이미 운영 중인 vLLM(Qwen3-VL)을 쓴다. 임베딩과 reranker는 **모델 서버 프로세스 하나**로 남은 GPU 1장에 함께 올린다. 그 GPU가 Exclusive_Process 모드(프로세스 1개만 허용)이고 root가 없어 모드를 바꿀 수 없기 때문이다. vLLM은 프로세스 하나에 모델 하나라 이 조건에서 두 모델을 띄울 수 없다.
- 모델 서버(`docker/model-server/server.py`)는 torch, transformers, fastapi, uvicorn만 쓴다. vLLM이 설치된 Python으로 root나 Docker 없이 실행한다. API는 vLLM과 같다(`/v1/embeddings`, `/v1/rerank`, `/tokenize`, `/v1/models`).
- 2026-10-05에 이 PC에서 확인한 것: 이미지를 지운 뒤 묶음만으로 설치, 실행, 검색까지 됨. 네트워크를 완전히 끊은(`--network none`) 컨테이너에서도 문서 처리와 검색이 됨. 운영 설정에서 설정 변경과 삭제는 `RAG_API_KEY` 없이 401.
- 2026-10-05 모델 서버 확인(이 PC의 RTX 5070 Ti, torch 2.11 cu128, transformers 5.18):
  - 두 모델을 한 프로세스에 올렸을 때 GPU 컴퓨트 프로세스가 1개였다.
  - bge-m3 벡터가 Ollama bge-m3와 같았다(코사인 1.0).
  - 묶음의 앱 컨테이너가 호스트의 모델 서버에 `host.docker.internal`로 붙어 처리, `/tokenize` 측정, rerank까지 됐다.
  - Exclusive_Process 모드 자체는 Windows에서 켤 수 없어 시험하지 못했다. 운영 GPU에서 `./model-server.sh status`로 프로세스가 1개인지 확인한다.

**Singularity/Apptainer (Docker·root 없이):** `python scripts/build_offline_bundle.py --singularity`로 앱과 모델 서버의 `.sif` 이미지를 묶음에 넣는다. ToolPDF의 `.sif`는 `toolpdf/`에 이미 들어 있다.
- 앱 이미지는 145MB, 모델 서버 이미지는 3.9GB다(CUDA 12.8 torch 포함), ToolPDF 폴더는 약 270MB다. 묶음 전체는 약 4.4GB다.
- 서버에서는 `./singularity.sh start`로 ToolPDF, 모델 서버, 앱을 함께 띄운다(`deploy/README.md` 5-B절).
- 2026-10-06 확인:
  - 이 PC의 Apptainer 1.4.5 컨테이너 안에서 묶음의 `singularity.sh`로 앱과 모델 서버 `.sif`를 띄웠다(ToolPDF를 넣기 전). 문서 처리, bge-m3 임베딩, 검색, rerank까지 됐다(모델 서버는 CPU).
  - 같은 모델 서버 이미지를 Docker `--gpus all`로 띄워 GPU에서 확인했다(rerank 15개 0.054초).
  - `apptainer --nv`는 Windows(WSL2) 위의 컨테이너에서 GPU 장치를 찾지 못해 이 PC에서는 시험할 수 없었다. 실제 Linux 서버에서 처음 띄울 때 `./singularity.sh status`로 GPU 프로세스를 확인한다.

Docker도 Singularity도 쓸 수 없는 서버라면 아래처럼 Python wheel로 설치한다. 인터넷이 되는 PC에서 준비한다. ToolPDF도 같은 방식으로 ToolPDF의 `requirements.txt`를 wheel로 받아 따로 설치하고 먼저 띄운다(ToolPDF README 2절).

```bash
# (1) Python wheel. 운영 서버의 OS/CPU/Python 버전에 맞춘다. 예: Linux x86_64, Python 3.12
pip download -r backend/requirements.txt -d wheelhouse \
  --platform manylinux2014_x86_64 --platform manylinux_2_28_x86_64 \
  --python-version 3.12 --only-binary=:all:
# (2) 프론트엔드는 빌드 결과물만 반입한다. 운영 서버에 Node.js가 필요 없다.
cd frontend && npm ci && npm run build        # frontend/dist 를 반입
# (3) 소스 반입. 제외: .venv, frontend/node_modules, data, __pycache__
```

운영 서버에서 설치한다.

```bash
python3.12 -m venv .venv
.venv/bin/pip install --no-index --find-links wheelhouse -r backend/requirements.txt
RAG_TOOLPDF_URL=http://127.0.0.1:8095 \
  bash -c 'cd backend && ../.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000'
```

- **LibreOffice(선택)**: ToolPDF 쪽에 설치한다. 없어도 docx/pptx/xlsx는 ToolPDF의 자체 렌더링으로 처리된다. doc/ppt/hwp를 처리하거나 원본 레이아웃이 필요할 때만 설치한다. 위치는 ToolPDF의 `TOOLPDF_SOFFICE_PATH`로 정한다. LibreOffice를 쓴다면 한글 폰트(나눔 등)도 설치해야 변환 결과가 깨지지 않는다. ToolPDF 이미지는 `WITH_LIBREOFFICE=1`로 빌드하면 둘 다 들어간다.
- **데이터 위치**: `RAG_DATA_DIR`(기본 `./data`)에 업로드 원본, 변환 PDF, 페이지 이미지 캐시, SQLite, 내장 Qdrant가 저장된다. 백업 대상이다.
- **같은 서버면 공유 폴더 방식**: ToolPDF의 `TOOLPDF_SHARED_ROOT`를 이 앱의 데이터 폴더로 두고 `RAG_TOOLPDF_TRANSFER=shared`로 하면 파일을 복사하지 않는다. 기본(`http`)은 파일을 올린다.

### 3-3. 모델 준비 (vLLM)

`config/models.yaml`의 `base_url`만 채우면 된다. 비워 두면 해당 기능은 대체 동작(fallback)하고, 그 사실이 결정 기록으로 남는다.

| 용도 | 권장 모델 | vLLM 실행 예 | 쓰는 API |
|---|---|---|---|
| VLM (필수 권장) | Qwen2.5-VL 7B 급 | `vllm serve Qwen/Qwen2.5-VL-7B-Instruct` | `/v1/chat/completions` (이미지 data URL) |
| 임베딩 (필수) | BAAI/bge-m3 (한국어, 8192 토큰) | `vllm serve BAAI/bge-m3 --task embed` ※ | `/v1/embeddings`, `/tokenize` |
| reranker (선택) | BAAI/bge-reranker-v2-m3 | `vllm serve BAAI/bge-reranker-v2-m3 --task score` ※ | `/v1/rerank` |

※ vLLM 버전에 따라 pooling 모델 실행 옵션 이름이 다르다(`--task` 또는 `--runner pooling` 계열). 설치된 버전의 문서를 확인한다.

**개발 PC에서 실제 모델로 쓰려면 Docker 스택**(`docker compose up -d --build`, README "로컬 PC에서 실제 모델로 실행"):
- `ollama` 컨테이너(GPU)가 `qwen2.5vl:7b`와 `bge-m3`를 서빙하고, `ollama-pull`이 첫 실행 때 모델을 받는다. 모델은 볼륨에 남는다.
- Ollama에는 `/rerank`가 없어서 모델 서버(`docker/model-server/server.py`)를 rerank 전용, CPU로 띄운다. vLLM과 같은 형식의 `POST /v1/rerank`를 제공한다. 같은 서버가 운영에서는 임베딩까지 맡는다(3-2). 다른 후보는 `dragonkue/bge-reranker-v2-m3-ko`(한국어 미세조정), `BAAI/bge-reranker-base`(작음), `jinaai/jina-reranker-v2-base-multilingual`(`RERANK_TRUST_REMOTE_CODE=1` 필요)다.
- Ollama에는 `/tokenize`도 없다. 그래서 토큰 비율은 기본값 2.5를 쓰고, 이 사실이 결정 기록으로 남는다.
- 호스트에서 eval 스크립트를 돌릴 때는 `models.docker.yaml`의 `ollama:11434`를 `localhost:11435`, `reranker:8080`을 `localhost:8081`로 바꾼 사본을 쓴다.

**GPU 없이 흐름만 확인**: `python scripts/mock_vllm.py --port 8001`을 실행하고 모든 `base_url`을 `http://127.0.0.1:8001/v1`로 설정한다.

### 3-4. Open WebUI 연동 (선택)

Open WebUI에 파일을 추가하면 이 서버가 파일을 받아 파이프라인을 자동으로 실행하게 할 수 있다. Open WebUI의 **External 문서 로더**(콘텐츠 추출 엔진) 기능을 쓴다. Open WebUI 쪽에는 코드 수정이나 플러그인이 필요 없다.

**이 서버 설정** (`.env` 또는 환경 변수)

```bash
RAG_API_KEY=<임의의 긴 문자열>        # Open WebUI가 보내는 Bearer 키. 비우면 인증 없이 받는다
RAG_INGEST_WAIT_SECONDS=3600          # 실행 완료를 기다리는 최대 시간(초). 넘으면 504
```

Open WebUI 서버에서 이 서버의 포트(기본 8000)에 접속할 수 있어야 한다. 그래서 `--host 0.0.0.0`으로 실행한다.

**Open WebUI 설정**: 관리자 화면이나 환경 변수 중 하나로 설정한다.

| 관리자 화면 (관리자 설정 → 문서) | 환경 변수 | 값 |
|---|---|---|
| 콘텐츠 추출 엔진 | `CONTENT_EXTRACTION_ENGINE` | `External` (환경 변수는 `external`) |
| URL | `EXTERNAL_DOCUMENT_LOADER_URL` | `http://<이 서버 주소>:8000/api/openwebui` (끝에 `/process`를 붙이지 않는다. Open WebUI가 붙인다) |
| API 키 | `EXTERNAL_DOCUMENT_LOADER_API_KEY` | 위 `RAG_API_KEY`와 같은 값 |

**동작**
1. Open WebUI가 `PUT {URL}/process`를 호출한다. 본문은 파일 바이트이고, 헤더는 `X-Filename`(URL 인코딩된 파일 이름), `Content-Type`, `Authorization: Bearer <키>`다.
2. 이 서버는 파일을 저장하고 실행을 대기열에 넣는다. 화면에서 시작한 실행과 같은 줄이라 하나씩 순서대로 처리된다. 같은 파일(sha256)의 성공한 실행이 있으면 다시 실행하지 않는다.
3. 실행이 끝나면 청크를 `[{page_content, metadata}]`로 돌려준다. metadata는 `source`(파일 이름), `document_id`, `run_id`, `chunk_id`, `page`(0부터, LangChain PDF 로더와 같아서 Open WebUI가 +1 해서 보여준다), `page_label`(1부터), `pages`(1부터, 쉼표 구분), `section`, `element_types`이고 모두 문자열이나 숫자다.
4. Open WebUI는 받은 청크를 자기 임베딩으로 다시 색인한다. 이 서버의 Qdrant에도 같은 문서가 색인되며, 처리 과정과 결정 근거는 이 서버 화면에서 볼 수 있다.

**연결 확인 순서**
1. Open WebUI 서버에서 `curl -X PUT -H "Authorization: Bearer <키>" -H "X-Filename: test.pdf" --data-binary @test.pdf http://<이 서버>:8000/api/openwebui/process`를 실행해 JSON 배열이 오는지 본다. 401이면 키가, 연결 오류면 방화벽이나 host 설정이 문제다.
2. Open WebUI에서 작은 PDF를 지식 베이스나 채팅에 추가한다. 이 서버 화면의 문서 목록에 나타나고 `succeeded`가 되는지 본다.
3. 큰 문서로 timeout을 확인한다. Open WebUI는 이 서버가 응답할 때까지 업로드 처리를 기다린다. 중간에 reverse proxy(nginx 등)가 있으면 `proxy_read_timeout`을 처리 시간보다 길게 잡는다.

**오류 응답**: 지원하지 않는 형식 등으로 실행이 실패하면 502이고 detail에 실행 오류가 들어간다. 대기 시간을 넘기면 504, 빈 파일은 400이다. Open WebUI에는 파일 처리 실패로 보인다.

**Open WebUI의 임베딩·rerank도 모델 서버에 맡길 때**(GPU 프로세스 1개 공유): `deploy/README.md` 8절. 2026-10-07 Open WebUI v0.11.3으로 실제 연결을 검증했다: 파일 추가 → IngestLens 처리 → 지식 베이스 → LLM 답변과 출처까지(`deploy/OPENWEBUI.md`).

**답변에 쪽 이미지 보여주기**: Open WebUI 필터 함수 `deploy/openwebui_page_images.py`가 출처 메타데이터의 `chunk_id`로 `GET /api/chunks/{id}/preview.png`(청크 영역을 칠한 쪽 이미지)를 답변의 썸네일 줄(임베드, 누르면 펼침)과 출처 팝업에 넣는다. 설치는 `deploy/OPENWEBUI.md` 10절.

범용 HTTP 수집(`POST /api/ingest`, multipart, 등록만 하고 바로 응답)은 README "HTTP 수집 API"를 본다.

---

## 4. 실제 모델을 연결한 뒤 첫 검증 순서

1. `models.yaml`을 설정하고 서버를 재시작한다.
2. 검색 화면 capabilities에 임베딩 모델과 reranker 이름이 보이는지 확인한다.
3. 문서 1개를 실행하고 "진행 현황 → 결정 로그"에서 다음을 확인한다.
   - `token estimate`가 `tokenizer_calibrated`(측정값)인지. `default`면 `/tokenize` 경로를 확인한다. `embedding.base_url`의 `/v1` 앞 주소에 `/tokenize`가 있어야 한다.
   - `embedding model`이 dev-hash가 아닌지.
4. 스캔 페이지와 그림 페이지가 있는 문서로 **VLM 응답 형식**을 확인한다. 파싱 리포트에서 다음을 본다.
   - 그림 element의 `figure_type` 태그가 chart/diagram 등으로 붙는지. 답의 첫 줄 `TYPE:` 규약을 모델이 지키는지 보는 것이다. 안 지키면 전부 `diagram`이 된다.
   - OCR 결과가 제목, 본문, 표로 나뉘는지. 모델이 Markdown `#` 헤딩을 쓰는지 보는 것이다.
   - 경고/오류 탭에 `truncated at max_tokens`가 뜨면 `vlm.max_tokens`를 올린다.
   - prompt를 고치면 `tools/vlm_output.py`의 파서와 `scripts/mock_vllm.py`도 함께 고친다.
5. 평가 기준선을 측정한다: `scripts/eval_retrieval.py --models <실제 models.yaml>`. 합성 세트의 바꿔 쓴 질의(paraphrase) 점수가 dev-hash의 62%(hybrid hit@1)보다 크게 오르는지 본다.
6. VLM 품질을 측정한다: `scripts/eval_vlm.py --models <실제 models.yaml> --name "<모델 이름>" --notes "<GPU, 양자화>"`. 결과 파일을 커밋하고 "VLM 평가 비교" 화면에서 Ollama 7b/3b 기준선과 비교한다(evals/README 3절).
7. 속도를 측정한다: `scripts/bench_large.py --vlm-url <실제 VLM>`. VLM 1회 평균 시간과 `vlm.max_concurrency`를 조정한다. GPU 여유를 보면서 올린다.

---

## 5. 튜닝 방법 (M6 도구)

자세한 형식은 `evals/README.md`에 있다. 요약하면 다음과 같다.

1. **실제 문서로 평가 세트를 만든다**. 문서 5~20개, 페이지 라벨, 질의 20~50개가 필요하다. 가장 효과가 큰 작업이다.
2. `eval_profile.py --sweep`: 틀린 페이지와 feature 값을 보고 규칙을 고친다.
   - sweep 제안을 그대로 쓰지 말고, 새 feature나 규칙을 만드는 쪽을 먼저 생각한다.
   - 예: 작은 표 페이지 문제는 임계값을 낮추는 대신 `table_text_share` feature와 규칙을 추가해서 해결했다.
3. `eval_retrieval.py`: 청킹 크기(`strategy.target_tokens`), 모드, 가중치, rerank를 **하나씩** 바꾸며 비교한다.
4. 좋아진 변경은 `config/strategy_rules.yaml`에 반영한다. 규칙 변경은 `tests/test_profiler.py`에 회귀 테스트로 남긴다.
5. 측정 결과를 아래 7절 표에 추가한다.

튜닝 후보:
- `profiler.rules`의 임계값: 특히 슬라이드는 글자가 적어 `mixed`로 분류되고 VLM 2차 판단이 늘어날 수 있다.
- `vlm_review_below` / `vlm_review_max_pages`
- `parse.figures.min_area_ratio`: 작은 아이콘이 그림으로 잡히는지 확인한다.
- `captions.pattern`
- `tables.max_empty_cell_ratio`
- `strategy.target_tokens` / `overlap_tokens`
- `section_min_page_ratio`

---

## 6. 남은 일 (우선순위)

**P0: 실제 환경 반입 직후**
- [ ] 4절 체크리스트로 실제 VLM, 임베딩, reranker를 연결하고 검증한다.
- [~] Linux에서 실행을 확인한다(프로세스 풀, 경로, 권한). Linux 컨테이너와 오프라인 서버의 Singularity에서 앱이 돎. 서버에서 문서 처리 전체와 모델 서버(GPU, Exclusive_Process 모드)는 사용자 시험 중이다.
- [ ] **인증과 접근 제어**가 없다. 설정 변경, 삭제, 수집 API만 `RAG_API_KEY`로 막혀 있고, 화면 조회·업로드·검색은 열려 있다. 내부 네트워크에서만 쓰더라도 접속할 수 있는 누구나 업로드, 조회, 검색할 수 있다. 배포 전에 최소한 SSO나 reverse proxy 인증을 붙인다.
- [x] Open WebUI 연동을 실제 Open WebUI(v0.11.3)로 검증했다(2026-10-07, `deploy/OPENWEBUI.md`). 그 과정에서 출처 쪽 번호가 1씩 크던 문제(`page` 0부터로 수정)와, Open WebUI가 청크를 다시 자르는 문제(설정으로 해결)를 찾았다. 남은 확인: 큰 문서에서 reverse proxy timeout. Open WebUI 로더 자체는 시간 제한 없이 기다리고, IngestLens는 `RAG_INGEST_WAIT_SECONDS`(기본 3600초)가 지나면 504를 준다.
- [ ] LibreOffice를 쓴다면 실제 변환을 검증한다(ToolPDF를 `WITH_LIBREOFFICE=1`로 빌드). 한글 폰트, 슬라이드 1장 = 1페이지인지(노트 페이지 출력 옵션이 꺼져 있는지) 확인한다.
- [ ] ToolPDF를 넣은 배포 묶음을 오프라인 서버에서 시험한다. Docker(`install.sh`)와 Singularity(`singularity.sh start`) 모두, `/#status`의 PDF 엔진이 정상인지, 문서 처리가 끝까지 되는지 본다.

**P1: 품질**
- [ ] 실제 공개 문서 10종 평가(2026-10-04, `qwen2.5vl:7b`)에서 모델과 상관없이 실패한 항목. 파이프라인 과제다:
  - 선 없는 표(논문의 booktabs 스타일, Docling Table 1)를 표로 잡지 못하고 문단으로 나눈다. `pymupdf_tables` 파서(ToolPDF `extract`의 `text` 모드)의 표 찾기가 괘선 기준이라서다. 고치려면 ToolPDF 쪽 옵션이나 VLM 재추출 조건을 바꾼다.
  - 숫자가 빽빽한 스캔 표(NACA Table I)는 재시도 한도 4096에서도 잘린다. 이런 문서가 많으면 `vlm.max_tokens_retry`를 올리거나(Ollama는 `OLLAMA_CONTEXT_LENGTH`도 함께) 페이지를 나눠 OCR한다.
  - 국가데이터처 보도자료의 벡터 차트를 `diagram`으로 답했다(7b). 차트 위에 숫자 라벨이 많아서로 보인다.
- [ ] `qwen2.5vl:3b`는 같은 토큰을 반복하다가 Ollama가 응답을 중단했다(`token repeat limit reached`, VLM 호출 47회 중 41회). 작은 모델을 쓸 거라면 `frequency_penalty`/`repeat_penalty`를 요청에 넣는 것을 검토한다.
- [ ] 그림 설명이 영어로 나온다(Ollama `qwen2.5vl:7b`, 3b도 흐름도에서 같음). prompt에는 이미 "이미지의 언어로 답하라"가 있다. 큰 모델로 `eval_vlm.py`를 돌려 보고도 영어면 prompt를 "한국어로" 쪽으로 바꾼다. 7b의 차트 추세 요약은 데이터와 맞지 않았다("증가 추세"라고 했지만 3월에 줄었다).
- [ ] 제목 바로 뒤에 표나 그림이 오면 제목만 있는 청크(`2. 비상 대응 절차`)가 따로 생긴다. 짧은 청크 병합과 함께 처리한다.
- [ ] 실제 문서로 평가 세트를 만들고 기준선을 측정한다.
- [ ] 짧은 청크를 병합한다. 현재 섹션이 짧으면 `too_short` 청크가 많이 생긴다. 최소 크기에 못 미치면 같은 섹션 안의 다음 청크와 합치는 방식이다.
- [ ] 스캔 OCR 결과의 위치 정보: 지금은 모든 element가 페이지 전체 bbox를 갖는다. VLM grounding 출력이나 OCR 엔진 bbox로 개선한다.
- [ ] Office 자체 렌더링(ToolPDF)의 누락 항목: docx 머리글/바닥글/각주/텍스트 상자, pptx SmartArt·도형 텍스트 일부. ToolPDF 저장소의 과제다.
- [ ] 대용량 벤치마크(`bench_large.py --pdf`)를 ToolPDF 구조로 다시 재고 7절에 남긴다. 앱과 ToolPDF의 메모리를 따로 잰다.
- [x] 문서 삭제와 전체 삭제(2026-10-04): `DELETE /api/documents/{id}`, `DELETE /api/documents?confirm=all`, 문서 화면의 "문서 삭제", 저장 위치 설정의 "데이터 비우기". run 하나만 지우는 기능은 없다(다시 실행하면 이전 run의 벡터는 지워지고 기록은 남는다).

**P2: 기능과 확장**
- [ ] 모든 문서를 대상으로 하는 검색 API와 Open WebUI 도구 연결. 지금 `POST /api/search`는 문서 하나(실행 하나) 안에서만 검색한다. LLM이 IngestLens를 직접 검색하게 하려면 필요하다(`deploy/OPENWEBUI.md` 9절).
- [ ] 화면에서 버튼이 꺼진 이유(바꾼 값 없음, 관리자 키 필요)를 표시한다. 사용자가 저장 위치 설정의 저장 버튼이 왜 꺼져 있는지 헷갈려 했다.
- [ ] 임베딩 질의·문서 접두어(`query_prefix`/`document_prefix`)와 차원 축소 지원. e5, Qwen3-Embedding으로 바꾸려면 필요하다(`docs/EMBEDDING_MODELS.md` 4절).
- [ ] 검색 결과로 LLM 답변 생성과 인용(텍스트 LLM endpoint 추가)
- [ ] 여러 서버 인스턴스로 확장: Qdrant 서버(`RAG_QDRANT_URL`), PostgreSQL(`RAG_DB_URL`), 작업 큐(arq 등)
- [ ] 임베딩 2D 투영을 UMAP으로 바꾸고 겹친 점을 구분한다(현재 PCA).
- [ ] HWP 자체 처리 (현재는 LibreOffice 필요)
- [ ] BM25 영어 어간 처리, 불용어 처리

---

## 7. 측정 기록

| 날짜 | 조건 | 결과 | 비고 |
|---|---|---|---|
| 2026-09-30 | 합성 세트 페이지 분류(12p) | 91.7% → 100% | `table_text_share` 규칙 추가 후 |
| 2026-09-30 | 합성 세트 검색 22문항, dev-hash | hybrid hit@1 82% (lexical 93%, paraphrase 62%) | 실제 임베딩 연결 후 비교 기준 |
| 2026-10-04 | 합성 세트 검색 22문항, Ollama `bge-m3` + `qwen2.5vl:7b`, reranker `bge-reranker-v2-m3`(CPU). RTX 5070 Ti, Docker | dense hit@1 95%, hybrid 82% (paraphrase 50%), hybrid+rerank 100% | `evals/reports/retrieval_synthetic_ollama.md`. 실제 임베딩에서는 BM25가 paraphrase를 끌어내려 hybrid가 dense보다 낮다. 가중치 조정 후보 |
| 2026-10-04 | 3페이지 PDF(텍스트, 스캔, 차트 그림), 같은 스택 | 전체 60s(모델 첫 로드 포함), 그림 설명 1회 8.0s, rerank 15개 1.6~2.2s(CPU) | manual.pdf 12p는 32s |
| 2026-10-07 | Open WebUI v0.11.3 + IngestLens 개발 스택, 국가데이터처 보도자료 5쪽 | Open WebUI 기본 청크 설정(1000자, 겹침 100, Markdown 헤더 분할)에서 IngestLens 청크 49개 → Open WebUI 조각 58개. `CHUNK_SIZE=8000`, 겹침 0, 분할 끔이면 26 → 26(Docling 논문) | 큰 표 9개가 잘렸다. `deploy/OPENWEBUI.md` 4-3 |
| 2026-10-09 | 배포 묶음(Docker, ToolPDF 0.1.0 포함), WSL Docker Engine에 묶음만으로 설치(포트 8100), 모델 주소 비움 | 묶음 376MB(앱 이미지 105MB, ToolPDF 폴더 270MB). `install.sh`로 두 이미지 불러오기와 시작, 상태의 PDF 엔진 정상(공유 폴더). sample.pdf 6쪽과 pptx 4장 처리 성공 | pptx는 ToolPDF 자체 렌더링으로 데이터 폴더의 `converted/`에 PDF를 씀. Singularity 묶음은 아직 시험 안 함 |
| 2026-10-06 | 배포 묶음 `--singularity`(앱 + 모델 서버 `.sif`) | 묶음 4.2GB(앱 sif 145MB, 모델 서버 sif 3.9GB, Docker 앱 이미지 149MB). 모델 서버 이미지 GPU: rerank 15개 0.054초, 임베딩 210개 0.8초 | CUDA 12.8 torch. Apptainer 안의 CPU 실행은 rerank 15개 약 8초 |
| 2026-10-05 | 모델 서버(bge-m3 + bge-reranker-v2-m3, 프로세스 1개, float16), RTX 5070 Ti | 임베딩 210개(약 330토큰씩) 0.75초, rerank 15개 0.06초, GPU 메모리 약 2.3GB. 합성 세트 dense hit@1 95%(Ollama와 같음) | `/tokenize`로 토큰 비율을 실제로 재서 청크 경계가 조금 바뀜(manual.pdf 17 → 19청크). hybrid+rerank 95%(한 문항 2위) |
| 2026-10-04 | 실제 공개 문서 10종, `qwen2.5vl:7b`, 대괄호 캡션 규칙과 잘림 재시도 적용 후 | 90% → 92%(38/43). 스캔 통계표 75% → 100%, 보도자료 `[그림 1]` 캡션 연결 | 재시도 3회 중 2회 해결, NACA 숫자 표 1회는 4096에서도 잘림 |
| 2026-10-04 | 실제 공개 문서 10종(17페이지 채점, `c8e06ba6495f`), 같은 스택 | `qwen2.5vl:7b` 90%(36/43), `qwen2.5vl:3b` 51%(18/43) | 3b는 VLM 호출 41/47 실패(반복 중단). 7b는 처리 393초, VLM 1회 평균 10.6초 |
| 2026-10-04 | VLM 평가 세트 5p(`a86b25c26f53`), Ollama Q4_K_M, RTX 5070 Ti | `qwen2.5vl:7b` 92%(17/19), `qwen2.5vl:3b` 86%(16/19). 두 모델 모두 OCR CER 0 | 7b 실패는 그림 설명 언어뿐. 3b는 스캔 제목 미인식, 차트를 diagram으로 분류. `evals/results/vlm/` |

---

## 8. 설계 결정과 이유

| 결정 | 이유 | 다시 생각할 조건 |
|---|---|---|
| 모든 형식을 PDF 페이지로 통일 | 분석, 파싱, 위치 표시, 화면을 한 가지 방식으로 처리 | 페이지 개념이 없는 형식(긴 HTML 등)을 주로 다룰 때 |
| 규칙이 먼저 분류하고 VLM은 애매한 페이지만 | 속도와 부하, 근거 설명 가능성 | VLM이 충분히 빠르고 규칙 정확도가 낮을 때 |
| PDF 처리는 별도 프로그램 ToolPDF(HTTP API) | 이 저장소를 MIT로 두고, AGPL인 PyMuPDF는 ToolPDF 안에만 둔다. 병렬 처리는 ToolPDF의 프로세스(`TOOLPDF_WORKERS`)가 맡는다 | 요청 지연이나 전송량이 문제가 될 때 |
| 같은 서버면 공유 폴더로 파일 전달 | 큰 문서를 복사하지 않음. DB에 데이터 폴더 기준 상대 경로를 저장하므로 그 경로를 그대로 쓴다 | 앱과 ToolPDF를 다른 서버에 둘 때(`http` 방식) |
| 쪽 창(window) 단위로 추출을 미리 요청 | VLM 호출과 다음 창 준비가 겹친다(`parse.windows_in_flight`가 `TOOLPDF_WORKERS`보다 크게) | 메모리가 부족하면 `window_pages`를 줄인다 |
| Redis/arq 대신 서버 안 asyncio 작업 | 서버 1대면 충분하고 반입할 구성요소가 적음 | 여러 인스턴스, 재시작 후 이어서 실행이 필요할 때 |
| SQLite + 내장 Qdrant 기본 | 설치 없이 동작 | 동시 사용자 증가, 이중화 |
| BM25(한글 bigram) + RRF, sparse 벡터 안 씀 | 형태소 분석기와 모델 의존성 없이 오프라인 환경에서 동작 | bge-m3 sparse 출력을 vLLM에서 쓸 수 있게 되면 |
| PCA(numpy), UMAP 안 씀 | 반입할 의존성을 줄임 | 시각화 품질이 중요해질 때 |
| xlsx는 기본 자체 렌더링 | LibreOffice는 넓은 시트를 페이지마다 잘라 표가 깨짐 | — |
| 재실행 시 이전 run의 벡터 삭제 | 문서당 최신 인덱스 하나만 검색되게 함 | run끼리 비교 검색이 필요할 때 (run별 collection) |

---

## 9. 개발 중 겪은 함정

- **평가 결과가 이상하면 먼저 입력 이미지를 직접 본다**: 합성 문서를 PyMuPDF 내장 `korea` 폰트로 그리면 영문과 숫자가 전각 폭이라 `NF3`가 실제로 `N F 3`처럼 띄어져 보인다. 처음에는 이것을 VLM의 OCR 오류로 잘못 보고했다. 합성 평가 문서를 새로 만들 때 주의한다.
- **벤치마크 PDF는 크기를 확인한다**: 같은 이미지를 반복 삽입하면 PDF는 이미지 스트림을 한 번만 저장해서, 150MB를 의도한 파일이 2.4MB가 됐다.
- **ToolPDF가 없으면 아무 문서도 처리할 수 없다**: 상태 화면의 "PDF 엔진 (ToolPDF)"를 먼저 본다. 테스트는 `tests/conftest.py`가 `TOOLPDF_HOME`(기본 `../ToolPDF`의 `.venv`)으로 ToolPDF를 띄우므로, 그 폴더나 `.venv`가 없으면 시작하지 못한다.
- **공유 폴더 방식은 두 쪽이 같은 폴더를 봐야 한다**: 앱의 데이터 폴더와 ToolPDF의 `TOOLPDF_SHARED_ROOT`가 같은 곳이어야 한다(Docker에서는 둘 다 `/data`). 데이터 폴더 밖의 파일은 어느 방식이든 HTTP로 올린다.
- **ToolPDF API 규약은 ToolPDF README다**: 문서에 없는 동작에 기대지 않는다. 새로 필요한 PDF 기능은 `tools/toolpdf.py`에 문서화된 엔드포인트로 추가하고, 이 저장소에 PDF 라이브러리를 들이지 않는다.
- **SQLite는 timezone을 저장하지 않는다**: `to_dict`에서 UTC로 붙인다. 화면 캡처에서 9시간 차이로 발견했다.
- **내장 Qdrant는 경로당 client 하나만 허용**한다. 항상 `vectorstore.client()`를 쓴다.
- **저장 위치 설정은 재시작해야 적용된다**: DB engine과 Qdrant client를 import 시점에 만든다. 설정 파일(`RAG_SETTINGS_FILE`)은 환경 변수와 `.env`보다 우선순위가 낮다. 그래서 `RAG_DATA_DIR`을 환경 변수로 주면 화면에서는 잠긴다.
- **파일 경로는 데이터 폴더 기준 상대 경로로 저장한다**(`settings.stored_path` / `settings.resolve`). 새 코드에서 `Document.path`나 `pdf_path`를 읽을 때 `Path(...)`로 바로 열지 말고 `settings.resolve()`를 거친다.
- **asyncio Semaphore는 이벤트 루프에 묶인다**: TestClient는 테스트마다 새 루프를 쓰므로 VLM semaphore를 루프별로 만든다.
- **Windows bash heredoc**: Python 코드 안의 `\n`, 바이트 이스케이프, 한글이 깨질 수 있다. 코드 수정은 편집 도구를 쓴다.
- **Windows에서 서버를 강제 종료하면 exit 255**가 보인다. 정상이다.
- **mock 분류기는 항상 `diagram`이라고 답한다**: mock VLM으로 띄운 데모 화면의 "relabel → diagram" 결정은 mock 때문이다.
- **백신의 HTTPS 검사(Norton 등)**: 컨테이너 안의 pip, npm, `ollama pull`이 `CERTIFICATE_VERIFY_FAILED`로 실패한다. 호스트는 Windows 인증서 저장소를 써서 문제가 없다. 그 루트 인증서를 `docker/certs/*.crt`로 내보내면 이미지와 Ollama가 신뢰한다(`docker/certs/README.md`).
- **Docker 스택의 Ollama 포트는 11435**다. 호스트에 네이티브 Ollama(11434)가 있어도 겹치지 않게 했다.
- **Docker에서는 이 PC의 브라우저 요청도 브리지 게이트웨이 주소(예: `172.18.0.1`)로 들어온다**: 그래서 "이 PC에서만 설정 변경" 검사에 걸려 저장 위치 설정 화면이 전부 잠겼다. compose에서 포트를 `127.0.0.1`에만 열고, 브리지 대역을 `RAG_ADMIN_HOSTS`(IP나 CIDR 목록)에 넣어 해결했다. 포트를 다른 PC에 열 때는 `RAG_ADMIN_HOSTS`를 지우고 `RAG_API_KEY`를 쓴다. 그러지 않으면 다른 PC 요청도 게이트웨이 주소로 들어와 설정을 바꿀 수 있게 된다.
- **Windows에서 `localhost`로 HTTP 요청하면 매번 약 2초가 더 걸린다**: IPv6(`::1`)를 먼저 시도하다 실패하고 IPv4로 넘어가기 때문이다. 모델 서버를 처음 재면 rerank가 2초로 나왔는데, `127.0.0.1`로 재면 0.06초였다. 호스트에서 측정할 때는 `127.0.0.1`을 쓴다. Linux 서버와 컨테이너 사이의 통신에는 해당하지 않는다.
- **BAAI/bge-m3는 가중치가 `pytorch_model.bin`이다**: safetensors가 없다. Hugging Face에서 받을 때 `*.safetensors`만 고르면 43MB 설정 파일만 받아진다.
- **Singularity는 이미지의 WORKDIR이 아니라 실행한 사람의 폴더에서 시작한다**: 그래서 앱 이미지의 시작 명령은 `uvicorn --app-dir /app/backend`로 폴더와 상관없이 동작하게 했다. 또 Singularity는 호스트 네트워크를 그대로 쓰므로 포트는 `INGESTLENS_PORT`로 정하고, 모델 서버 주소는 `127.0.0.1`이다(`models.singularity.yaml`).
- **Windows(WSL2)의 Docker 안에서는 `apptainer --nv`가 GPU를 찾지 못한다**: WSL2의 GPU는 `/dev/dxg`로 전달되고 `/dev/nvidia*` 장치가 없기 때문이다. GPU 동작은 같은 이미지를 Docker `--gpus all`로 띄워 확인한다.
- **Open WebUI는 문서 로더가 돌려준 청크를 자기 설정으로 다시 자른다**: 기본값은 1000자, 겹침 100자, Markdown 헤더 분할이다. 그대로 두면 IngestLens 청크 49개가 58개로 늘고 표가 잘렸다. `CHUNK_SIZE=8000`, `CHUNK_OVERLAP=0`, `ENABLE_MARKDOWN_HEADER_TEXT_SPLITTER=false`로 둔다.
- **Open WebUI는 출처의 `page`를 0부터로 보고 +1 해서 보여준다**(LangChain PDF 로더 규약): 그래서 `/api/openwebui/process`는 `page`를 0부터, `page_label`과 `pages`는 1부터 보낸다. 2026-10-07 전에는 1부터 보내서 쪽 번호가 1씩 크게 보였다.
- **Open WebUI 0.11 필터에서 답변에 무언가를 붙일 때**: 화면은 `content`가 아니라 `output` 항목에서 그린다(`content`만 고치면 저장은 되지만 안 보인다). 필터가 고친 `sources`는 저장되지 않으므로 출처는 `__event_emitter__`의 `source` 이벤트로 넣는다. HTML 주석과 `<img>`는 글자로 보이고, Markdown 이미지는 원래 크기로 그려지며 눌렀을 때의 미리보기도 원래 크기까지만 커진다. 그래서 쪽 썸네일은 `embeds` 이벤트(iframe, 높이는 `postMessage({type: "iframe:height"})`)로 넣었다.
- **WSL의 Docker Engine은 세션이 없으면 배포판째 꺼진다**: `wsl ... -- docker ...` 명령이 끝나고 잠시 뒤 Ubuntu가 꺼지면서 컨테이너도 정상 종료(코드 0)된다. `.wslconfig`의 `[general] instanceIdleTimeout=-1`로 막는다(3-1). Docker Desktop은 자기 VM을 계속 켜 두므로 이 문제가 없었다.
- **Docker Desktop에서 옮긴 볼륨은 Compose 표시(label)가 없으면 경고가 난다**: `volume ... already exists but was not created by Docker Compose`. 볼륨을 만들 때 `--label com.docker.compose.project=ingestlens --label com.docker.compose.volume=<이름>`을 붙인다.
- **Git Bash에서 bat을 실행하면 `timeout`이 Git Bash의 것으로 바뀐다**: `timeout /t`가 `invalid time interval`로 실패한다. `start_test.bat`은 `%SystemRoot%\System32\timeout.exe`를 직접 부른다.
- **새 Ollama 이미지는 받은 모델을 새 형식으로 다시 받는다**: 예전 사본이 `llamacpp:<id>` 이름으로 남아 6GB가 두 벌이 됐다. `ollama list`로 보고 `ollama rm`으로 지운다.
- **배포용 compose의 프로젝트 이름은 `ingestlens-server`다**: 개발용 `docker-compose.yml`(프로젝트 `ingestlens`)과 같은 이름이면 한쪽을 `up`/`down`할 때 다른 쪽 컨테이너와 네트워크를 바꾸거나 지운다. 실제로 시험 중에 개발용 앱 컨테이너가 교체됐다.
- **빌드 PC의 추가 인증서(`docker/certs/*.crt`)는 이미지에 남지 않는다**: Dockerfile이 `RUN --mount=type=bind`로 패키지를 받는 동안만 쓴다. 그래서 개발용과 배포용 이미지를 따로 빌드하지 않는다.
- **Docker에서 데이터 폴더(`RAG_DATA_DIR=/data`)는 잠겨 있는 것이 정상이다**: 컨테이너 안의 경로는 볼륨으로 정해진다. PC 쪽 폴더는 `.env`의 `INGESTLENS_DATA_DIR`로 바꾸고, 화면에는 `RAG_DATA_DIR_HINT` 문구가 나온다.
- **rerank 서버는 요청의 `model`이 `RERANK_MODEL`과 다르면 404를 준다**. 모델을 바꿀 때 `docker-compose.yml`과 `models.docker.yaml`을 함께 바꾼다.
- **임베딩 화면의 점 겹침**: 비슷한 청크(dev-hash)는 같은 좌표에 모인다. 범례의 개수로 확인한다.

---

## 10. 자주 쓰는 명령

```bash
cd backend && ../.venv/Scripts/python -m pytest -q                         # 테스트 (ToolPDF를 직접 띄움)
RAG_TOOLPDF_TRANSFER=http ../.venv/Scripts/python -m pytest -q             # HTTP 전송 방식으로
../.venv/Scripts/python -m pytest -q tests/test_pipeline.py -k end_to_end  # 테스트 하나
../ToolPDF/.venv/Scripts/python -m uvicorn --app-dir ../ToolPDF toolpdf.server:app --port 8095   # PDF 엔진
../.venv/Scripts/python -m uvicorn app.main:app --port 8000                # 서버 (ToolPDF 먼저)
cd frontend && npm run dev                                                 # UI 개발 (proxy :8000)
python scripts/mock_vllm.py --port 8001 --latency 0.3                      # mock 모델 서버
python scripts/bench_large.py --pdf <큰 PDF> --vlm-url http://127.0.0.1:8001/v1
python scripts/eval_profile.py --labels evals/synthetic/profile_labels.json --sweep --out evals/reports/p.md
python scripts/eval_retrieval.py --dataset evals/synthetic/retrieval.json --models config/models.yaml --out evals/reports/r.md
python scripts/eval_vlm.py --models config/models.docker-host.yaml --name "Ollama qwen2.5vl:7b"   # 결과는 화면 /#evals
RAG_MODELS_FILE=other.yaml RAG_DATA_DIR=/tmp/x ...                         # 설정과 데이터 분리 실행
docker compose up -d --build                                               # 실제 모델 로컬 스택 (ToolPDF + Ollama + reranker)
bash docker/release.sh                                                     # (ToolPDF 저장소에서) ToolPDF 배포 폴더
python scripts/build_offline_bundle.py [--singularity] [--no-docker]       # 오프라인 배포 묶음 (release/, ToolPDF 포함)
./singularity.sh start | ./model-server.sh start | ./install.sh            # 오프라인 서버에서 (deploy/README.md)
```

## 11. 이 문서 갱신 규칙

- 마일스톤이나 큰 기능이 끝나면 1절 표와 6절 목록을 갱신한다.
- 성능이나 품질을 측정하면 7절에 한 줄 추가한다. 조건을 반드시 적는다.
- 새로 겪은 함정은 9절에 추가한다.
- 검증 수준이 바뀌면(실제 모델 연결 등) 1절 "검증 수준" 표를 가장 먼저 고친다.
