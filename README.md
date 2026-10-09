# IngestLens

Explainable RAG document ingestion: parse, chunk, embed — with the evidence behind every decision.

웹에서 문서를 선택하면 여러 agent가 다음 순서로 처리한다: 형식 판별 → 콘텐츠 분석 → 전략 결정 → 파싱 → 청킹 → 임베딩.
각 단계의 진행 상황과 결정 근거를 웹에서 실시간으로 볼 수 있다. 외부 API 없이 직접 띄운 vLLM(OpenAI 호환) endpoint만 사용하므로, 인터넷이 없는 환경에서도 동작한다.

PDF 처리(문서를 PDF로 바꾸기, 쪽 분석, 텍스트·표·그림 추출, 쪽 이미지)는 별도 프로그램인 PDF 엔진 **[ToolPDF](https://github.com/kisubkim/ToolPDF)**가 HTTP API로 맡는다. 이 저장소에는 PDF 라이브러리가 없다. 앱을 실행하거나 테스트하려면 ToolPDF가 필요하다.

현재 상태: M1–M6 구현 완료. 로컬 GPU의 실제 모델(Ollama `qwen2.5vl:7b`, `bge-m3`, reranker 모델 서버)과 Open WebUI 연동까지 검증했다. 운영 vLLM과 큰 모델로는 아직 검증하지 않았다(`docs/HANDOFF.md` 1절).

## 시작하기

| 어디서 | 가이드 | 요약 |
|---|---|---|
| **Windows PC** | **`docs/WINDOWS.md`** | `setup_local.bat`(처음 한 번) → `start_local.bat` → http://localhost:8000. 실제 모델은 Windows용 Ollama로 연결 |
| Windows PC, 모델까지 Docker로 | `docs/WINDOWS.md` 7절 | WSL2의 Docker Engine으로 `start_test.bat` |
| 인터넷 없는 리눅스 서버 | **`deploy/README.md`** | 배포 묶음 파일 하나로 `./install.sh`(Docker) 또는 `./singularity.sh start` |
| Linux·macOS 개발 PC | 아래 "실행 (개발)" | 두 저장소를 받아 venv로 실행 |
| Windows PC에서 Open WebUI까지 시험 | `docs/WINDOWS.md` 7-1절 | `start_webui_test.bat`: IngestLens 스택 + Open WebUI, 이미 떠 있으면 건너뜀 |
| Open WebUI 연동 | `deploy/OPENWEBUI.md` | 문서 로더, 쪽 이미지 필터 |

## 문서

- 계획: `docs/PLAN.md`
- 이어서 작업할 때 필요한 내용(상태, 반입 절차, 백로그, 함정): **`docs/HANDOFF.md`**
- 에이전트 구성과 판단 기준(각 단계가 무엇을 어떤 규칙으로 정하는지): **`docs/AGENTS.md`**
- PDF 엔진 인터페이스와 MIT 내장 엔진 계획(ToolPDF 없이 쓰기): `docs/ENGINE_PLAN.md`
- 평가와 튜닝: `evals/README.md`
- 라이선스: MIT (`LICENSE`). PDF 엔진 ToolPDF(AGPL-3.0, 별도 프로그램), 의존성, 모델의 라이선스는 `NOTICE.md`

## 실행 (개발)

Windows에서는 `setup_local.bat`, `start_local.bat`, `stop_local.bat`이 아래 과정을 대신한다(`docs/WINDOWS.md`). 직접 하려면 Python 3.12와 Node.js로 다음처럼 한다. 경로는 Linux·macOS 기준이고, Windows에서는 `.venv/bin/`을 `.venv/Scripts/`로 바꾼다.

ToolPDF를 이 저장소 옆(`../ToolPDF`)에 받아 두고 먼저 띄운다. 설치와 실행은 ToolPDF의 README를 따른다.

```bash
git clone https://github.com/kisubkim/ToolPDF ../ToolPDF
cd ../ToolPDF && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn toolpdf.server:app --port 8095        # 다른 터미널에서 계속 띄워 둔다
```

그다음 이 저장소에서 실행한다.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
cd frontend && npm ci && npm run build && cd ..

cd backend
../.venv/bin/python -m uvicorn app.main:app --port 8000   # http://localhost:8000 (UI 포함)
```

UI 개발: `cd frontend && npm run dev`. `/api`는 `127.0.0.1:8000`으로 proxy된다.

ToolPDF를 다른 주소에 띄웠으면 `RAG_TOOLPDF_URL`을 정한다. 기본은 파일을 HTTP로 올리는 방식이라 두 프로그램이 폴더를 공유하지 않아도 된다.

## 첫 화면 (임베딩 DB 현황)

문서를 고르지 않았을 때나 왼쪽 위 "IngestLens"를 누르면 보인다. 문서 수와 원본 용량, 페이지 수, 벡터와 청크 수(문서별 최신 실행), 임베딩 모델, 실행 결과, 데이터 폴더별 디스크 사용량, 최근 문서를 보여준다. 최근 문서를 누르면 그 문서가 열린다. API: `GET /api/overview`

## 문서 삭제

- **문서 하나:** 문서를 연 뒤 오른쪽 위 "문서 삭제". 올린 원본, 변환 PDF, 페이지 이미지, 모든 실행 기록, 파싱·청크 결과, 임베딩 벡터를 함께 지운다.
- **전체:** 저장 위치 설정 화면 아래 "데이터 비우기 → 전체 삭제". 확인을 위해 "전체 삭제"를 입력해야 한다.
- 실행 중이거나 대기 중인 문서는 지울 수 없다. 먼저 실행을 취소한다.
- 저장 위치 설정과 같이 서버가 돌아가는 PC에서만 지울 수 있다(`RAG_API_KEY`를 설정하면 그 키로 어디서나).
- API: `DELETE /api/documents/{id}`, `DELETE /api/documents?confirm=all`

## 에이전트 규칙 바꾸기 (`/#rules`)

각 단계(에이전트)가 판단에 쓰는 값(쪽 분류 규칙, 파서 선택, 그림·표 기준, 청크 크기·겹침·최소 크기, Office 변환 방법)을 화면에서 바꾸고 **서버 재시작 없이 바로 적용**한다. 왼쪽 아래 "에이전트 규칙" 버튼, 실행 화면의 단계 상자, 근거 상세의 "이 단계 규칙 보기·바꾸기"로 들어간다. 값은 저장할 때 검사하고, 바꾼 항목만 데이터 폴더의 `strategy_rules.override.yaml`에 저장한다(기본값 `config/strategy_rules.yaml`은 그대로). 실행마다 어떤 규칙 버전으로 처리했는지 근거에 남는다. 변경 권한은 저장 위치 설정과 같다. 자세한 설명: `docs/AGENTS.md` 11절. API: `GET/PUT/DELETE /api/rules`

## 백엔드 상태 확인

화면 왼쪽 아래에 백엔드 상태가 색으로 표시된다(초록 정상, 노랑 주의, 빨강 오류나 연결 안 됨). 15초마다 다시 확인하며, 누르면 `/#status`에서 항목별로 볼 수 있다.

- 확인 항목: API 서버, DB, 벡터 DB, PDF 엔진(ToolPDF), 임베딩, VLM, reranker, LibreOffice(ToolPDF 쪽), 실행 대기열
- 모델 서버는 `GET {base_url}/models`로 응답과 설정한 모델이 있는지 본다. models.yaml에 주소를 비운 항목은 "꺼짐"으로 표시하며, 파이프라인은 대체 방식으로 계속 동작한다.
- API: `GET /api/status` (결과는 5초 동안 재사용, `?refresh=true`면 바로 다시 확인)

## 설정

- `config/models.yaml`: vLLM endpoint를 설정한다. `base_url`이 비어 있으면 다음처럼 동작한다.
  - VLM: native 파서로 fallback한다.
  - 임베딩: dev-hash embedder를 쓴다. 검색 품질은 의미가 없다.
  - reranker(선택): 검색 화면의 rerank 옵션이 비활성화된다. vLLM `/v1/rerank`를 사용한다.
- `config/strategy_rules.yaml`: 페이지 분류 규칙, 파서 매핑, 청킹 파라미터, 파싱 단위와 병렬도(`parse.window_pages`, `parse.windows_in_flight`), 그림/캡션/표 재추출 기준, Office 변환 방식(`office`).
- 환경 변수(`RAG_` prefix, 저장소 폴더의 `.env` 파일도 가능). 경로 설정(`RAG_DATA_DIR`, `RAG_MODELS_FILE`)에 상대 경로를 쓰면 저장소 폴더 기준이다. 서버를 어느 폴더에서 띄웠는지와 상관없다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `RAG_DATA_DIR` | 저장소의 `data/` | 업로드, 변환 결과, 페이지 이미지, SQLite, 내장 Qdrant 저장 위치 |
| `RAG_DB_URL` | SQLite | 예: `postgresql+psycopg://...` |
| `RAG_QDRANT_URL` | 내장 모드 | 예: `http://qdrant:6333` |
| `RAG_TOOLPDF_URL` | `http://127.0.0.1:8095` | PDF 엔진 ToolPDF 주소 |
| `RAG_TOOLPDF_API_KEY` | 없음 | ToolPDF에 `TOOLPDF_API_KEY`를 정했으면 같은 값 |
| `RAG_TOOLPDF_TRANSFER` | `http` | 파일을 넘기는 방식. `http`: 파일을 올린다(sha256로 한 번만). `shared`: ToolPDF가 이 앱의 데이터 폴더를 `TOOLPDF_SHARED_ROOT`로 마운트하고 상대 경로로 주고받는다(Docker 스택과 배포 묶음). 데이터 폴더 밖의 파일은 어느 방식이든 올린다 |
| `RAG_TOOLPDF_TIMEOUT_S` | `600` | ToolPDF 요청 한 건의 제한 시간(초) |
| `RAG_MODELS_FILE` | `config/models.yaml` | 다른 모델 설정 파일을 쓸 때. 예: `config/models.windows.yaml`(Windows용 Ollama), mock 서버용 사본 |
| `RAG_API_KEY` | 없음 | 수집 API(`/api/ingest`, `/api/openwebui/process`)와 저장 위치 변경의 Bearer 키. 비어 있으면 수집 API는 인증하지 않고, 저장 위치 변경은 서버 PC에서 접속했을 때만 허용한다. 그 밖의 화면용 API에는 적용하지 않는다 |
| `RAG_SETTINGS_FILE` | `config/settings.local.yaml` | 저장 위치 설정 화면이 쓰는 파일. git에 올라가지 않는다 |
| `RAG_INGEST_WAIT_SECONDS` | `3600` | Open WebUI 로더가 실행 완료를 기다리는 최대 시간. 넘으면 504를 돌려준다 |

### 저장 위치

모든 데이터는 데이터 폴더(`RAG_DATA_DIR`) 아래에 저장된다.

| 경로 | 내용 |
|---|---|
| `uploads/{문서id}/` | 올린 원본 파일 |
| `converted/{문서id}/` | Office·이미지를 변환한 PDF |
| `pages/{문서id}/{페이지}_{dpi}.png` | 페이지 이미지 캐시. 화면에서 처음 볼 때 만든다 |
| `rag.db` | SQLite DB(문서, 실행, 결정 근거, 요소, 청크). `RAG_DB_URL`을 설정하면 그 DB를 쓴다 |
| `qdrant/` | 내장 Qdrant(임베딩 벡터). `RAG_QDRANT_URL`을 설정하면 그 서버를 쓴다 |

화면 왼쪽 아래 **저장 위치 설정**에서 항목별 위치와 용량을 보고, 데이터 폴더, DB 주소, Qdrant 주소를 바꿀 수 있다.
- 바꾼 값은 `RAG_SETTINGS_FILE`에 저장되고 **서버를 재시작해야 적용된다.** 같은 항목을 환경 변수나 `.env`로 설정했다면 그쪽이 우선하며, 화면에서는 바꿀 수 없다.
- 기존 데이터는 자동으로 옮기지 않는다. DB에는 파일 경로가 데이터 폴더 기준 상대 경로로 저장되므로, 서버를 멈춘 뒤 데이터 폴더를 통째로 새 위치에 복사하면 그대로 이어서 쓸 수 있다. 이전 버전이 저장한 절대 경로는 서버가 시작할 때 상대 경로로 바뀐다.

## 테스트

```bash
cd backend && ../.venv/Scripts/python -m pytest -q                              # 공유 폴더 방식
cd backend && RAG_TOOLPDF_TRANSFER=http ../.venv/Scripts/python -m pytest -q     # HTTP 업로드 방식
```

테스트는 ToolPDF를 직접 띄운다. `TOOLPDF_HOME`(기본: 이 저장소 옆 `ToolPDF` 폴더, 그 안의 `.venv`)에서 빈 포트로 시작하고 끝나면 내린다. 이미 떠 있는 ToolPDF를 쓰려면 `RAG_TOOLPDF_URL`을 정한다.

## 지원 형식

PDF가 아닌 문서는 ToolPDF가 PDF로 바꾼다(`/v1/normalize`).

| 형식 | 처리 |
|---|---|
| PDF | 그대로 처리 |
| 이미지 (png/jpg/tif) | 1페이지 PDF로 감싸서 처리 |
| docx / pptx | ToolPDF에 LibreOffice가 있으면 LibreOffice로 PDF 변환하고, 없으면 ToolPDF의 자체 렌더링을 쓴다. 두 경우 모두 원본에서 헤딩, 슬라이드 제목, 발표자 노트, PPT 차트 데이터를 추가로 받아 파싱에 쓴다 |
| xlsx | 기본은 자체 렌더링. 시트를 24행 단위 표로 나누고 헤더를 반복한다 (`office.xlsx`) |
| doc / ppt / hwp 등 | ToolPDF에 LibreOffice 필요(ToolPDF 이미지를 `WITH_LIBREOFFICE=1`로 빌드) |

## 검색 방식

검색 화면(`POST /api/search`)은 한 run의 청크를 대상으로 세 가지 방식을 지원한다.

- `dense`: Qdrant cosine 검색
- `lexical`: BM25. 한글은 음절 bigram으로 색인하므로 형태소 분석기가 필요 없다.
- `hybrid`: RRF(k=60) 융합. dense와 BM25 가중치를 조절할 수 있다.

reranker가 설정되어 있으면 후보를 다시 정렬한다. 결과마다 단계별 점수와 순위를 함께 반환한다.

## HTTP 수집 API (다른 시스템 연동)

화면 버튼 없이 HTTP로 파일을 보내면 바로 파이프라인이 실행된다. 실행은 화면에서 시작한 것과 같은 줄에 서서 들어온 순서대로 하나씩 진행된다. `RAG_API_KEY`를 설정했으면 `Authorization: Bearer <키>` 헤더가 필요하다.

- `POST /api/ingest`: multipart `files`(여러 개 가능). 저장 후 실행을 등록하고 바로 응답한다. 진행 상황은 `GET /api/runs/{run.id}`로 확인한다. 같은 파일(sha256)이 이미 있고 마지막 실행이 성공이나 진행 중이면 다시 실행하지 않고 그 실행을 돌려준다.

  ```bash
  curl -H "Authorization: Bearer $KEY" -F files=@a.pdf -F files=@b.docx http://localhost:8000/api/ingest
  ```

- `PUT /api/openwebui/process`: Open WebUI의 External 문서 로더 규약. 본문은 파일 바이트, 파일 이름은 `X-Filename` 헤더(URL 인코딩)로 받는다. 실행이 끝날 때까지 기다렸다가 청크를 `[{page_content, metadata}]`로 돌려준다. metadata에는 `source`, `document_id`, `run_id`, `chunk_id`, `page`(0부터, LangChain PDF 로더와 같아서 Open WebUI가 +1 해서 보여준다), `page_label`(1부터), `pages`(1부터, 쉼표 구분), `section`, `element_types`가 들어간다. 실행이 실패하면 502, 기다리는 시간이 `RAG_INGEST_WAIT_SECONDS`를 넘으면 504를 돌려준다.

### Open WebUI 설정

관리자 설정 → 문서 → 콘텐츠 추출 엔진을 `External`로 바꾸고, URL에 `http://<이 서버>:8000/api/openwebui`, API 키에 `RAG_API_KEY` 값을 넣는다. 환경 변수로는 `CONTENT_EXTRACTION_ENGINE=external`, `EXTERNAL_DOCUMENT_LOADER_URL`, `EXTERNAL_DOCUMENT_LOADER_API_KEY`다. 그러면 Open WebUI에 파일을 추가할 때마다 이 서버가 파일을 받아 파이프라인을 실행하고, Open WebUI는 돌려받은 청크를 자기 지식 베이스에 넣는다. 처리 과정과 결정 근거는 이 서버 화면에서 볼 수 있다.

Open WebUI의 임베딩과 rerank도 IngestLens와 같은 모델 서버(bge-m3, bge-reranker-v2-m3)에 맡길 수 있다. 그러면 GPU 프로세스 1개를 두 시스템이 함께 쓰고, 임베딩도 일치한다. 환경 변수와 관리자 화면 설정은 `deploy/README.md` 8절에 있다. Open WebUI 0.11.x에서 파일 추가부터 LLM 답변까지 연결하는 전체 가이드는 `deploy/OPENWEBUI.md`에 있다.

## 오프라인 서버에 배포 (Docker 묶음 파일 하나)

```bash
bash docker/release.sh                      # ToolPDF 저장소에서 먼저: ToolPDF 배포 폴더 (이미지, 소스, 라이선스)
python scripts/build_offline_bundle.py      # release/ingestlens-<버전>-offline.tar (앱 + ToolPDF, 약 380MB)
python scripts/build_offline_bundle.py --singularity   # + Singularity/Apptainer용 .sif (약 4.4GB, Docker·root 없이 실행)
# 서버에서: tar xf ingestlens-<버전>-offline.tar && cd ingestlens-<버전> && ./install.sh   (Singularity: ./singularity.sh start)
```

인터넷 없는 리눅스 서버에 이 파일 하나와 모델 폴더만 가져가면 된다.

- ToolPDF는 묶음의 `toolpdf/` 폴더(ToolPDF가 만든 배포 폴더 그대로, ToolPDF와 PyMuPDF 소스 포함)에 들어 있고 앱과 함께 시작된다.
- VLM은 이미 운영 중인 vLLM을 쓴다.
- 임베딩과 reranker는 묶음에 든 **모델 서버**(`./model-server.sh start`)로 띄운다. GPU 1장에 프로세스 하나로 두 모델을 함께 올리며, root나 Docker 없이 vLLM의 Python 환경에서 실행한다.
- 모델 받기, `.env`와 `models.yaml` 설정, 확인, 업데이트, 백업 순서는 `deploy/README.md`에 있다.

## 로컬 PC에서 실제 모델로 실행 (Docker)

NVIDIA GPU가 있는 PC에서 앱, ToolPDF, Ollama(VLM `qwen2.5vl:7b`, 임베딩 `bge-m3`), reranker(`BAAI/bge-reranker-v2-m3`, CPU)를 한 번에 띄운다. 모델은 약 9.5GB이고 첫 실행 때 받는다. ToolPDF 이미지는 이 저장소 옆의 ToolPDF 소스(`../ToolPDF`, 다른 위치면 `.env`에 `TOOLPDF_DIR=경로`)로 빌드한다.

- Windows: `start_test.bat`(시작, 브라우저 열기), `stop_test.bat`(중지). Docker Desktop 없이 **WSL 배포판(기본 `Ubuntu-24.04`) 안의 Docker Engine**을 쓴다. 준비 방법은 `docs/HANDOFF.md` 3-1. 배포판 이름이 다르면 `INGESTLENS_WSL_DISTRO`를 정한다.
- Linux, macOS, WSL 안: `./start_test.sh`, `./stop_test.sh`. Windows Git Bash에서 실행해도 `docker`가 없으면 WSL의 Docker Engine을 쓴다.

```bash
docker compose up -d --build     # http://localhost:8000   (Windows에서는 wsl -d Ubuntu-24.04 -u root -- docker compose ...)
docker compose logs -f app
docker compose down              # 모델(볼륨)과 data-docker/ 는 남는다
```

- 앱은 `config/models.docker.yaml`을 쓰고 데이터는 `./data-docker`에 저장한다.
- 호스트에서 직접 접근할 때 Ollama는 `11435`, reranker는 `8081`, ToolPDF는 `8095` 포트를 쓴다. 모든 포트는 이 PC(`127.0.0.1`)에서만 열린다.
- 앱과 ToolPDF는 같은 데이터 폴더를 `/data`로 마운트하고 공유 폴더 방식으로 파일을 주고받는다.
- 저장 위치 설정 화면에서 DB 주소와 Qdrant 주소를 바꿀 수 있다. 데이터 폴더는 컨테이너 안에서 `/data`로 고정이다. PC의 어느 폴더를 쓸지는 저장소 루트 `.env`에 `INGESTLENS_DATA_DIR=D:/경로`를 적고 다시 시작해서 정한다(기본 `./data-docker`).
- 다른 PC에서 접속하게 하려면 `docker-compose.yml`의 앱 포트를 `"8000:8000"`으로 바꾸고 `RAG_API_KEY`를 설정한다.
- 모델을 바꾸려면 `docker-compose.yml`의 환경 변수와 `config/models.docker.yaml`의 `model`을 함께 바꾼다. GPU 메모리가 적으면 `qwen2.5vl:3b`를 쓴다.
- Ollama에는 `/tokenize`가 없어서 토큰 비율은 기본값 2.5를 쓴다. 이 폴백은 결정 기록에 남는다.
- 백신이나 사내 프록시가 HTTPS를 가로채면 빌드할 때 인증서 오류가 난다. 그 경우 `docker/certs/README.md`를 따른다.
- 실제 배포 대상은 vLLM이다. 이 구성은 로컬 검증용이다.

## GPU 없이 VLM 경로 확인 (mock vLLM)

```bash
.venv/Scripts/python scripts/mock_vllm.py --port 8001 --latency 0.3
```

`models.yaml`의 `vlm.base_url`을 `http://127.0.0.1:8001/v1`로 설정한다. 원본을 건드리지 않으려면 복사본을 만들고 `RAG_MODELS_FILE`로 지정한다.
mock 서버는 prompt 규약(OCR, 그림 `TYPE:` 첫 줄, 표, 분류)에 맞는 고정 답을 돌려준다. `/v1/embeddings`, `/v1/rerank`, `/tokenize`도 제공한다.

## 대용량 벤치마크

```bash
.venv/Scripts/python scripts/bench_large.py --pdf <큰 PDF> --vlm-url http://127.0.0.1:8001/v1
```

수백 쪽(예: 150MB, 텍스트·그림·스캔 쪽이 섞인) PDF를 아무거나 넣는다. 출력은 단계별 시간, VLM 호출 통계, 이 앱 프로세스의 최대 메모리다. ToolPDF의 메모리는 따로 잰다. 쪽 분석과 추출의 병렬도는 ToolPDF의 `TOOLPDF_WORKERS`가 정한다.

실제 VLM에서는 호출 1회의 latency가 전체 시간을 결정한다. 대략 `호출 수 × latency / max_concurrency`다.

## 평가 (M6)

```bash
.venv/Scripts/python scripts/eval_profile.py --labels evals/synthetic/profile_labels.json --sweep
.venv/Scripts/python scripts/eval_retrieval.py --dataset evals/synthetic/retrieval.json
.venv/Scripts/python scripts/eval_vlm.py --models <models.yaml> --name "<모델 이름>"   # VLM 품질, 결과는 evals/results/vlm/
.venv/Scripts/python scripts/eval_vlm.py --cases evals/samples/cases.json --models <models.yaml> --name "<모델 이름>"   # 실제 공개 문서 10종
```

평가 세트(`evals/synthetic`, `evals/vlm`, `evals/samples`)는 저장소에 들어 있다. ToolPDF가 떠 있어야 한다. VL 모델끼리의 결과는 앱 왼쪽 아래 **"VLM 평가 비교"**(`/#evals`)에서 나란히 비교한다. 라벨 형식, 평가 항목, 튜닝 순서, 현재 기준선은 `evals/README.md`에 있다.
