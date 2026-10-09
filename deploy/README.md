# IngestLens 오프라인 설치

인터넷이 없는 리눅스 서버에 IngestLens를 설치하는 순서다.

## 0. 구성

| 구성 요소 | 어디서 | 실행 방법 | GPU |
|---|---|---|---|
| IngestLens 앱 (화면 + 파이프라인) | 앱 서버 | Docker 컨테이너(`./install.sh`) 또는 Singularity(`./singularity.sh`, 5-B절) | 쓰지 않음 |
| PDF 엔진 ToolPDF (PDF 변환, 쪽 분석, 추출, 렌더) | 앱 서버 (앱과 같은 서버) | 앱과 함께 시작된다. 묶음의 `toolpdf/` 폴더 | 쓰지 않음 |
| 임베딩(bge-m3) + reranker(bge-reranker-v2-m3) | GPU 서버 | **모델 서버 프로세스 1개** (`./model-server.sh start`), root·Docker 불필요 | GPU 1장, 프로세스 1개 |
| VLM (예: Qwen3-VL) | 이미 운영 중인 vLLM | 그대로 사용 | 별도 |

- **모델 서버를 따로 두는 이유**
  - vLLM은 프로세스 하나에 모델 하나만 서빙한다. 그래서 임베딩과 reranker를 vLLM으로 띄우면 GPU 프로세스가 2개 필요하다.
  - 그런데 GPU가 Exclusive_Process 모드(프로세스 1개만 허용)이고, root 권한이 없어 모드를 바꿀 수 없다.
  - 모델 서버는 두 모델을 **한 프로세스**에 올리므로, GPU에는 CUDA 컨텍스트가 하나만 생긴다.
- **API:** 모델 서버는 vLLM과 같은 형식을 제공한다(`/v1/embeddings`, `/v1/rerank`, `/tokenize`, `/v1/models`). 앱 쪽은 주소만 적으면 된다.
- **메모리:** 두 모델을 float16으로 올리면 GPU 메모리를 약 2.3GB 쓴다. 80GB GPU면 배치를 크게 잡아도 여유가 있다.
- **PDF 엔진:** 묶음은 두 형태다. 기본 묶음(`ingestlens-<버전>-offline.tar`)은 ToolPDF(AGPL, PyMuPDF)를 함께 넣고, 앱이 ToolPDF의 HTTP API로 문서를 PDF로 바꾸고 읽고 그린다. 앱과 같은 데이터 폴더를 함께 마운트해서 파일을 복사하지 않고 경로로 주고받는다(공유 폴더 방식). **ToolPDF 없는 묶음**(`ingestlens-<버전>-local-offline.tar`, `build_offline_bundle.py --pdf-engine local`)은 앱 안의 내장 엔진(pypdfium2, pdfplumber 등 퍼미시브 라이선스만)으로 처리한다. 앱 이미지는 같고, `.env`의 `RAG_PDF_ENGINE`과 compose 파일만 다르다(아래 "ToolPDF 없는 묶음").

반입할 것:

| 반입할 것 | 만드는 곳 | 크기(대략) |
|---|---|---|
| 배포 묶음 `ingestlens-<버전>-offline.tar` | 인터넷 되는 PC에서 `python scripts/build_offline_bundle.py` | 약 380MB (앱 이미지 105MB + ToolPDF 폴더 270MB) |
| 모델 폴더 `models/bge-m3`, `models/bge-reranker-v2-m3` | 인터넷 되는 PC에서 Hugging Face로 받기(3절). 이미 있으면 그 폴더를 쓴다 | 각 약 2.3GB |

## 1. 서버 준비

- **앱 서버:** Linux x86_64, Docker Engine 24 이상과 `docker compose` 플러그인. 리눅스용 Docker Engine은 무료다.
  - Docker를 쓸 수 없으면 `docs/HANDOFF.md` 3-2의 Python wheel 설치를 쓴다.
- **GPU 서버(모델 서버):** vLLM이 설치된 Python 환경이 있으면 추가로 설치할 것이 없다. 모델 서버는 torch, transformers, fastapi, uvicorn만 쓰는데, 모두 vLLM과 함께 설치되어 있다.
  - vLLM 환경이 없으면 위 네 패키지가 있는 Python 환경이 필요하다. 오프라인이면 wheel을 미리 받아 반입한다.

## 2. 배포 묶음 만들기 (인터넷 되는 PC)

먼저 ToolPDF 배포 폴더를 만든다. [ToolPDF](https://github.com/kisubkim/ToolPDF) 저장소(기본 위치는 이 저장소 옆 `../ToolPDF`)에서 실행한다. 이미 만들어 둔 같은 버전이 있으면 건너뛴다.

```bash
bash docker/release.sh       # ToolPDF 저장소에서. release/toolpdf-<버전>/ (Docker 이미지, .sif, 소스, 라이선스)
```

그다음 이 저장소에서 묶음을 만든다.

```bash
python scripts/build_offline_bundle.py                 # Docker용 (앱 이미지)
python scripts/build_offline_bundle.py --singularity   # + Singularity/Apptainer용 이미지 2개(.sif)
python scripts/build_offline_bundle.py --singularity --no-docker   # Singularity 이미지만 (앱 Docker 이미지 제외)
```

결과는 `release/ingestlens-<버전>-offline.tar`다. 버전은 기본으로 빌드한 날짜(`20261005` 형식)이고, `--version`으로 바꿀 수 있다. 어느 커밋으로 만들었는지는 묶음 안의 `VERSION` 파일에 적힌다. 같은 날 다시 만들면 같은 버전 이름을 덮어쓴다. ToolPDF는 `TOOLPDF_DIR`(기본 `../ToolPDF`)의 `release/`에서 가장 최근 폴더를 쓰고, `--toolpdf-release <폴더>`로 고를 수 있다. 묶음에 들어가는 것:

| 파일 | 내용 |
|---|---|
| `images/` | 앱 docker 이미지(gzip) |
| `toolpdf/` | ToolPDF 배포 폴더 그대로: Docker 이미지, `.sif`, ToolPDF 소스, PyMuPDF 소스, `LICENSE`, `NOTICE.md`, `BUNDLE.md`, `SHA256SUMS` |
| `docker-compose.yml`, `.env`, `models.yaml` | 앱과 ToolPDF 설정. `.env`에는 두 버전이 채워져 있음 |
| `install.sh` | 앱과 ToolPDF 설치·시작 |
| `model-server/server.py`, `model-server.sh`, `model-server.env.example` | 모델 서버 |
| `LICENSE`, `NOTICE.md`, `VERSION`, `SHA256SUMS` | 라이선스, 버전, 무결성 확인 |
| `sif/ingestlens-app.sif`, `sif/ingestlens-model-server.sif` | `--singularity`일 때만. Singularity/Apptainer 이미지(5-B절) |
| `singularity.sh`, `singularity.env`, `models.singularity.yaml` | Singularity로 실행할 때 쓰는 스크립트와 설정. `singularity.env`에는 ToolPDF 이미지 이름과 임의의 ToolPDF 키가 채워져 있음 |

- `toolpdf/` 폴더는 ToolPDF와 PyMuPDF(둘 다 AGPL-3.0)의 소스를 함께 담고 있다. 묶음을 다른 곳에 넘길 때 이 폴더를 빼지 않는다(`NOTICE.md` 2절, `toolpdf/BUNDLE.md`).
- `--singularity`는 GPU용 모델 서버 이미지(CUDA 포함 torch)를 빌드하므로 묶음이 수 GB로 커진다.
- `--no-docker`는 앱 Docker 이미지(`images/`)를 빼고 Singularity 이미지만 넣는다. 그 묶음으로는 `install.sh`(Docker)를 쓸 수 없다. 앱 Docker 이미지는 약 150MB라 크기 차이는 크지 않다. `toolpdf/` 폴더는 소스 제공 묶음이라 항상 통째로 넣는다.
### 2-1. ToolPDF 없는 묶음

```bash
python scripts/build_offline_bundle.py --pdf-engine local                 # Docker용
python scripts/build_offline_bundle.py --pdf-engine local --singularity   # + .sif
```

- 결과는 `release/ingestlens-<버전>-local-offline.tar`다. ToolPDF 배포 폴더가 필요 없고 `toolpdf/` 폴더가 들어가지 않는다. 묶음 전체가 MIT 등 퍼미시브 라이선스다(`NOTICE.md` 6절).
- 앱 이미지는 기본 묶음과 같다. 다른 것은 `docker-compose.yml`(앱만, 원본 `deploy/docker-compose.local-engine.yml`), `.env`와 `singularity.env`의 `RAG_PDF_ENGINE=local`이다. 설치와 실행은 5절, 5-B절과 같고, `./singularity.sh start`는 PDF 엔진을 건너뛴다.
- 처리 품질: 공개 문서 50쪽에서 쪽 분류, 표, 그림 영역이 ToolPDF와 같았다. 오래된 스캔 문서의 OCR 글자층은 ToolPDF보다 제목 조각이 많이 생긴다(`docs/ENGINE_PLAN.md` 9절). `.doc`, `.ppt`, `.hwp`는 LibreOffice가 없어 처리하지 않는다(docx, pptx, xlsx, PDF, 이미지는 처리).
- 기본 묶음에서도 `.env`의 `RAG_PDF_ENGINE`을 `local`로 바꾸면 ToolPDF를 쓰지 않는다. 기본값 `auto`는 ToolPDF가 응답하지 않을 때 내장 엔진으로 처리한다(상태 화면의 PDF 엔진이 "주의").

- 빌드 PC에서는 공식 Apptainer 컨테이너(`ghcr.io/apptainer/apptainer`)로 `.sif`를 만든다. 빌드 PC에 Singularity를 설치할 필요는 없다.
- torch는 CUDA 12.8용(`cu128`)으로 넣는다. A100, H100을 지원한다. 서버의 NVIDIA 드라이버가 오래되어 모델 서버가 GPU를 못 잡으면 `--torch-cuda cu126`으로 다시 만든다.

## 3. 모델 받기 (인터넷 되는 PC, 없을 때만)

```bash
pip install -U huggingface_hub
hf download BAAI/bge-m3             --local-dir models/bge-m3
hf download BAAI/bge-reranker-v2-m3 --local-dir models/bge-reranker-v2-m3
```

- 이전 버전의 huggingface_hub이면 `huggingface-cli download`를 쓴다.
- vLLM용으로 받아 둔 bge-m3 폴더가 있으면 그대로 쓴다. 같은 Hugging Face 형식이다.
- 라이선스: bge-m3는 MIT, bge-reranker-v2-m3는 Apache-2.0이다. 둘 다 상업 사용이 가능하다.

## 4. 모델 서버 시작 (GPU 서버, root 불필요)

```bash
tar xf ingestlens-<버전>-offline.tar && cd ingestlens-<버전>
cp model-server.env.example model-server.env
vi model-server.env
./model-server.sh start
./model-server.sh status
```

`model-server.env`에서 고칠 것:

| 항목 | 내용 |
|---|---|
| `PYTHON` | vLLM이 설치된 Python 경로. 예: `~/venvs/vllm/bin/python` |
| `CUDA_VISIBLE_DEVICES` | 남는 GPU 번호(`nvidia-smi`의 번호) |
| `EMBED_MODEL`, `RERANK_MODEL` | 3절의 모델 폴더 경로 |
| `PORT` | 기본 8090 |
| `MAX_BATCH_TOKENS` | 80GB GPU면 65536처럼 크게 잡아도 된다 |

`status`로 확인할 것:
- `/health` 응답에 두 모델이 보이는지
- `nvidia-smi` 목록에 **이 서버의 PID 하나만** GPU를 잡고 있는지

나머지 명령:
- 중지: `./model-server.sh stop`
- 로그: `./model-server.sh logs`
- 문제를 앞에서 직접 보려면: `./model-server.sh run`

서버가 재부팅되면 다시 `start`해야 한다. 자동으로 시작하려면 다음 중 하나를 쓴다(root 불필요).
- `crontab -e`에 `@reboot cd <폴더> && ./model-server.sh start`
- `systemctl --user` 서비스

## 5. 앱 설치와 시작 (앱 서버)

```bash
cd ingestlens-<버전>
vi .env            # RAG_API_KEY, 데이터 폴더, 포트
vi models.yaml     # 모델 서버 주소, VLM 주소와 모델 이름
./install.sh
```

**`.env`**
- `RAG_API_KEY`: 다른 PC의 사용자는 이 키가 있어야 설정 변경, 문서 삭제, 수집 API를 쓸 수 있다. 기본값 그대로 두지 않는다.
- `INGESTLENS_DATA_DIR`: 올린 문서, DB, 벡터가 쌓이는 곳. 백업 대상이다.

**`models.yaml`**
- `embedding`, `reranker`의 `base_url`
  - 모델 서버가 같은 서버에서 돌면: `http://host.docker.internal:8090/v1`
  - 다른 서버면: `http://<GPU 서버 IP>:8090/v1`
- `model` 이름은 `model-server.env`의 `EMBED_NAME`, `RERANK_NAME`과 같아야 한다.
- `vlm.base_url`, `vlm.model`: 운영 중인 vLLM의 주소와 `--served-model-name`. 이름은 `curl http://<VLM 서버>/v1/models`로 확인한다.
- **Qwen3-VL은 Instruct 버전을 쓴다.** Thinking 버전은 답 앞에 생각 과정을 출력하므로, OCR, 그림 `TYPE:`, 분류 JSON 형식을 기대하는 파서가 잘못 읽을 수 있다.

`install.sh`가 하는 일:
1. `SHA256SUMS`로 파일 무결성을 확인한다.
2. 앱 이미지(`images/`)와 ToolPDF 이미지(`toolpdf/*-docker.tar.gz`)를 `docker load`로 불러온다.
3. `docker compose up -d`로 ToolPDF와 앱을 시작한다. 앱은 ToolPDF가 정상 응답한 뒤에 시작한다.

ToolPDF는 compose 네트워크 안에서만 열리고 서버 밖으로는 포트를 내지 않는다. 처리 프로세스 수는 `.env`의 `TOOLPDF_WORKERS`(기본 4)로 정한다.

## 5-B. Singularity/Apptainer로 실행 (Docker 대신)

Docker 없이, root 권한 없이 `.sif` 이미지 세 개로 ToolPDF, 모델 서버, 앱을 모두 띄운다. 모델 서버는 이미지 안에 torch(CUDA)가 들어 있으므로 vLLM 환경이 없어도 된다.

```bash
tar xf ingestlens-<버전>-offline.tar && cd ingestlens-<버전>
vi singularity.env          # RAG_API_KEY, CUDA_VISIBLE_DEVICES, MODELS_DIR(3절의 모델 폴더), 포트
vi models.singularity.yaml  # VLM 주소와 모델 이름 (임베딩·reranker는 이미 127.0.0.1:8090)
./singularity.sh start      # ToolPDF + 모델 서버 + 앱
./singularity.sh status     # 응답과, GPU를 잡은 프로세스가 1개인지
```

나머지 명령:
- 하나만 시작: `./singularity.sh start-pdf`, `./singularity.sh start-model`, `./singularity.sh start-app`
- 중지: `./singularity.sh stop`(모두), `./singularity.sh stop model`
- 로그: `./singularity.sh logs pdf`, `./singularity.sh logs model`, `./singularity.sh logs app`

동작 방식:
- **네트워크:** Singularity는 호스트 네트워크를 그대로 쓴다. 그래서 `models.singularity.yaml`의 모델 서버 주소는 `127.0.0.1:8090`이고, 앱은 `INGESTLENS_PORT`로, ToolPDF는 `TOOLPDF_PORT`(기본 8095)로 바로 열린다. ToolPDF 포트도 서버 밖에서 보이므로 묶음의 `singularity.env`에는 임의의 `TOOLPDF_API_KEY`가 들어 있고, 앱이 같은 키로 접속한다.
- **데이터:** 이미지 안은 읽기 전용이다. 데이터는 `INGESTLENS_DATA_DIR` 폴더를 `/data`로, 모델 폴더를 `/models`로 연결해서 쓴다. ToolPDF도 같은 데이터 폴더를 `/data`로 연결하고(공유 폴더 방식), 캐시는 `TOOLPDF_CACHE_DIR`(기본 `./toolpdf-cache`)에 둔다.
- **GPU:** `--nv`로 호스트 드라이버를 연결한다. GPU를 쓰는 것은 모델 서버 안의 Python 하나뿐이라 "프로세스 1개" 조건에 맞는다.
- **명령어:** `apptainer`와 `singularity` 중 있는 것을 쓴다. `SINGULARITY`에 경로를 직접 적어도 된다.

이미 운영 중인 vLLM 환경에서 모델 서버를 띄우고 싶으면 4절의 `model-server.sh`를 쓰고, ToolPDF와 앱만 `./singularity.sh start-pdf`, `./singularity.sh start-app`으로 띄우면 된다. ToolPDF 없는 묶음(`RAG_PDF_ENGINE=local`)은 `start-pdf`가 아무것도 하지 않는다.

## 6. 확인

```bash
curl http://localhost:8000/api/health        # {"ok": true, "version": "<버전>"}
docker compose ps
docker compose logs -f app
```

- 브라우저로 `http://<서버 주소>:8000/#status`를 연다. PDF 엔진, 임베딩, reranker, VLM이 모두 "정상"인지 본다. PDF 엔진이 "오류"면 `docker compose logs toolpdf`(Singularity는 `./singularity.sh logs pdf`)를 본다. "PDF 엔진 (내장)"이 "주의"면 `auto`에서 ToolPDF가 응답하지 않아 내장 엔진으로 처리하고 있다는 뜻이다. 실행의 "근거" 탭 `PDF engine`에도 어느 엔진으로 처리했는지 남는다.
  - "주의": 서버는 응답하지만 `models.yaml`의 모델 이름이 그 서버의 이름과 다르다는 뜻이다.
  - "오류": 연결하지 못한다는 뜻이다. 방화벽, 주소, 포트를 확인한다.
- 문서 하나를 올려 실행해 본다. 실행의 "근거" 탭에서 다음을 확인한다.
  - `embedding model`이 `bge-m3`인지(`dev-hash`가 아닌지)
  - `token estimate`가 측정값(`tokenizer_calibrated`)인지. 모델 서버의 `/tokenize`를 쓴다.
- VLM 품질은 인터넷 되는 PC나 개발 PC에서 같은 VLM 주소로 `scripts/eval_vlm.py`를 돌려 기존 결과(Qwen2.5-VL 7B 92%)와 비교한다.

## 7. 업데이트, 되돌리기, 백업

- **업데이트:** 새 묶음을 풀고 `./install.sh`를 실행한다.
  - 데이터 폴더는 그대로 쓰인다.
  - 전에 고친 `.env`, `models.yaml`, `model-server.env`는 새 폴더로 옮긴다. `.env`의 `INGESTLENS_VERSION`과 `TOOLPDF_VERSION`은 새 묶음의 값으로 둔다.
  - 모델 서버가 바뀌었으면 `./model-server.sh stop && ./model-server.sh start`로 다시 띄운다.
- **되돌리기:** `.env`의 `INGESTLENS_VERSION`(필요하면 `TOOLPDF_VERSION`도)을 이전 버전으로 바꾸고 `docker compose up -d`를 실행한다. 이전 이미지는 `docker images ingestlens`, `docker images toolpdf`에 남아 있다.
- **백업:** `docker compose stop app toolpdf` 후 `INGESTLENS_DATA_DIR` 폴더를 통째로 복사한다.
- **중지:** `docker compose down`. 데이터는 남는다.

## 8. Open WebUI와 모델 서버 함께 쓰기 (선택)

> 파일 추가 → IngestLens 처리 → 지식 베이스 → LLM 답변까지 연결하는 전체 순서, 실제 시험 결과, 문제 해결은 **`OPENWEBUI.md`**에 있다. 이 절은 모델 서버 공유 설정만 요약한다.

Open WebUI도 임베딩과 reranker를 4절의 모델 서버에 맡기면 다음과 같이 된다.
- GPU 프로세스는 모델 서버 1개로 유지된다.
- Open WebUI는 GPU가 필요 없는 일반 이미지로 돈다.
- IngestLens와 Open WebUI가 같은 bge-m3로 임베딩하므로 결과가 일치한다.

```
GPU 1장 ── 모델 서버 (프로세스 1개: bge-m3 + bge-reranker-v2-m3, 포트 8090)
              ▲                                   ▲
   IngestLens (models.yaml)            Open WebUI (아래 환경 변수, GPU 없는 이미지)
```

### 8-1. Open WebUI 환경 변수

`<모델 서버>`는 4절의 서버 주소다. Open WebUI가 같은 서버의 Docker에서 돌면 `host.docker.internal`이다(이때 `extra_hosts: host.docker.internal:host-gateway`가 필요하다).

```bash
# 임베딩: 모델 서버의 /v1/embeddings (OpenAI 형식)
RAG_EMBEDDING_ENGINE=openai
RAG_OPENAI_API_BASE_URL=http://<모델 서버>:8090/v1
RAG_OPENAI_API_KEY=EMPTY                    # model-server.env 에 API_KEY 를 정했다면 같은 값
RAG_EMBEDDING_MODEL=bge-m3                  # model-server.env 의 EMBED_NAME

# rerank: 모델 서버의 /v1/rerank. rerank는 hybrid 검색일 때만 쓰인다
ENABLE_RAG_HYBRID_SEARCH=true
RAG_RERANKING_ENGINE=external
RAG_EXTERNAL_RERANKER_URL=http://<모델 서버>:8090/v1/rerank   # 경로까지 전부 적는다(Open WebUI가 붙이지 않는다)
RAG_EXTERNAL_RERANKER_API_KEY=EMPTY
RAG_RERANKING_MODEL=bge-reranker-v2-m3      # model-server.env 의 RERANK_NAME

# 문서 파싱을 IngestLens에 맡길 때 (선택, 5절의 앱 서버 주소와 .env 의 RAG_API_KEY)
CONTENT_EXTRACTION_ENGINE=external
EXTERNAL_DOCUMENT_LOADER_URL=http://<IngestLens 서버>:8000/api/openwebui
EXTERNAL_DOCUMENT_LOADER_API_KEY=<RAG_API_KEY 값>

# 오프라인: 모델 다운로드와 버전 확인을 끈다
OFFLINE_MODE=true
```

docker로 띄우는 예:

```bash
docker run -d --name open-webui -p 3000:8080 \
  --add-host host.docker.internal:host-gateway \
  -v open-webui:/app/backend/data \
  --env-file openwebui.env \
  ghcr.io/open-webui/open-webui:main          # :cuda 가 아닌 일반 이미지. GPU를 쓰지 않는다
```

오프라인 서버라면 이 이미지도 `docker save`/`docker load`로 반입한다.

### 8-2. 관리자 화면에서 설정할 때

관리자 설정 → 문서에서 같은 값을 넣는다.

| 항목 | 값 |
|---|---|
| 임베딩 모델 엔진 | OpenAI |
| API Base URL | `http://<모델 서버>:8090/v1` |
| 임베딩 모델 | `bge-m3` |
| 하이브리드 검색 | 켬 |
| Reranking 엔진 | External |
| Reranking URL | `http://<모델 서버>:8090/v1/rerank` |
| Reranking 모델 | `bge-reranker-v2-m3` |
| 콘텐츠 추출 엔진 (선택) | External, `http://<IngestLens 서버>:8000/api/openwebui` |

### 8-3. 주의할 점

- **환경 변수는 처음 시작할 때만 반영된다.**
  - Open WebUI는 이 설정들을 처음 시작할 때 자기 DB에 저장하고, 그 뒤로는 DB 값을 쓴다.
  - 이미 운영 중인 Open WebUI라면 관리자 화면에서 바꾼다.
  - 또는 `ENABLE_PERSISTENT_CONFIG=false`로 매번 환경 변수를 읽게 한다.
- **임베딩 모델을 바꾸면 기존 지식 베이스를 다시 색인해야 한다.** 이전 모델로 만든 벡터와 섞이면 검색이 맞지 않는다.
- **`:cuda` 이미지와 `USE_CUDA_DOCKER=true`를 쓰지 않는다.** Open WebUI가 GPU를 잡으면 모델 서버와 함께 "프로세스 1개" 조건을 넘는다.
- **모델 서버는 요청을 하나씩 처리한다.** IngestLens와 Open WebUI가 동시에 많이 요청하면 순서를 기다린다. 이 PC 기준 임베딩 210개가 0.75초, rerank 15개가 0.06초라 보통 사용량에서는 문제가 없다.
- **확인 범위:**
  - 요청과 응답 형식은 Open WebUI 소스(`retrieval/models/external.py`의 `{model, query, documents, top_n}` → `results[].index`, `relevance_score`)와 맞춰 확인했다.
  - 실제 Open WebUI를 모델 서버에 붙여 검색해 보지는 않았다. 처음 붙일 때 Open WebUI의 지식 베이스에 문서 하나를 넣고 질문해서 확인한다. 모델 서버 로그(`./model-server.sh logs`)에 `/v1/embeddings`, `/v1/rerank` 요청이 찍히는지 본다.

## 9. 라이선스

- IngestLens는 MIT License다(`LICENSE`, `NOTICE.md`). 저작권 표시와 라이선스 문구만 남기면 고쳐 쓰거나 배포하는 데 제약이 없다.
- PDF 엔진 ToolPDF는 AGPL-3.0인 별도 프로그램이다. 고치지 않고 쓰면 되고, 고쳐서 네트워크로 제공하면 고친 소스를 제공해야 한다. ToolPDF를 묶음에 넣을 때는 ToolPDF의 `LICENSE`, `NOTICE.md`를 함께 넣는다(`NOTICE.md` 2절).
- ToolPDF 없는 묶음(2-1절)에는 AGPL 구성 요소가 없다. 내장 엔진의 라이브러리(pypdfium2와 PDFium에 든 라이브러리, pdfplumber 등)와 나눔 글꼴(SIL OFL)의 라이선스는 `NOTICE.md` 3절, 6절에 있다.
- 이미지 안의 Python 패키지 라이선스는 `NOTICE.md`에 있다.
