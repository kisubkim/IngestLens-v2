# 라이선스 고지

2026-10-10 기준이다. 이 저장소의 라이선스와, 설치할 때 받아 오는 의존성과 따로 실행하는 프로그램의 라이선스를 구분한다. 버전은 `backend/requirements.txt`, `backend/requirements-dev.txt`, `frontend/package-lock.json`에 적힌 값을 따른다.

모델 가중치, `.venv`, `node_modules`, `frontend/dist`, `data/`, `.env`는 이 저장소에 포함하지 않는다.

## 1. 이 저장소

Copyright (c) 2026 김기섭

이 저장소의 소스, 문서, 설정, 합성 평가 세트, 화면 캡처는 [MIT License](https://opensource.org/license/mit)로 배포한다. 전문은 `LICENSE`에 있다. 대상은 `backend/`, `frontend/src`, `scripts/`, `config/`, `deploy/`, `docker/`, `docs/`, `evals/`, `captures/`, `README.md`다.

- 저작권 표시와 `LICENSE` 문구를 함께 두면 누구나 사용, 복사, 수정, 배포, 판매할 수 있다. 고친 소스를 공개할 의무는 없다.
- PDF 처리는 두 엔진 중 하나가 맡는다(`RAG_PDF_ENGINE`, 기본 `auto`). 별도 프로그램인 ToolPDF(2절)를 HTTP로 호출하거나, 앱 안의 내장 엔진(`backend/app/engines/local`)을 쓴다. 내장 엔진은 퍼미시브 라이선스 라이브러리만 쓴다(3절의 pypdfium2, pdfplumber 등). PyMuPDF, Ghostscript 같은 카피레프트 PDF 라이브러리는 담거나 설치하지 않는다. 시험(`backend/tests/test_engine_select.py`)이 의존성 목록과 import를 검사한다.

**예외: `evals/samples/*.pdf`**는 공개 문서에서 일부 페이지를 발췌한 평가용 자료다. 이 저장소의 저작물이 아니며 MIT License가 적용되지 않는다. 각 파일은 원본의 라이선스(공공누리 제1유형, CC BY 4.0, CC BY-SA 4.0, 미국 연방정부 저작물)를 따른다. 원본, 사용한 페이지, 변경 내용, 출처 표시는 `evals/samples/SOURCES.md`에 있다. 같은 폴더의 `cases.json`(기대값)은 이 저장소의 저작물이다.

## 2. ToolPDF (별도 프로그램)

PDF 변환, 쪽 특징 측정, 요소 추출, 렌더는 [ToolPDF](https://github.com/kisubkim/ToolPDF)가 맡는다. ToolPDF는 **GNU AGPL-3.0**(AGPL-3.0-only)이다. 핵심 의존성인 PyMuPDF(Artifex, AGPL-3.0 또는 상업 라이선스)를 AGPL 조건으로 쓰기 때문이다.

이 저장소와 ToolPDF의 관계:

- ToolPDF는 별도 프로세스(단독 실행, Docker, Singularity)로 띄운다. 이 저장소는 ToolPDF README에 문서화된 HTTP API로만 통신하고, 파일·JSON·이미지만 주고받는다. ToolPDF의 소스를 import하거나 복사하지 않으며 PyMuPDF를 설치하거나 링크하지 않는다. ToolPDF와 통신하는 곳은 `backend/app/engines/toolpdf.py` 하나다. ToolPDF 없이 내장 엔진만으로도 동작한다.
- 따라서 이 저장소에는 MIT License가 적용되고, ToolPDF에는 ToolPDF의 라이선스가 적용된다. 이 구조가 각자의 라이선스 판단에 어떤 영향을 주는지는 사용하는 쪽에서 법률 검토로 확인한다(ToolPDF README 1절).
- 설정 파일(`toolpdf.toml`)과 `TOOLPDF_*` 환경 변수로 ToolPDF 설정을 바꾸는 것은 ToolPDF를 고치는 것이 아니다(ToolPDF `NOTICE.md`의 AGPL 7조 추가 허가).
- **ToolPDF를 고쳐서 쓰면** 고친 소스를 AGPL로 공개해야 하고, 고친 ToolPDF를 네트워크로 제공하면 그 사용자가 소스를 받을 수 있게 해야 한다(AGPL 13조).
- **ToolPDF를 배포물(이미지, 묶음 파일)에 넣으면** ToolPDF의 `LICENSE`, `NOTICE.md`를 함께 넣고 ToolPDF 소스 위치(<https://github.com/kisubkim/ToolPDF>)를 알린다. 이 저장소의 배포 묶음은 ToolPDF가 만든 배포 폴더(ToolPDF 소스와 PyMuPDF 소스 포함)를 `toolpdf/`에 그대로 넣어 이 조건을 채운다(6절).
- `docker-compose.yml`(개발용)은 ToolPDF 이미지를 이 저장소 옆의 ToolPDF 소스(`TOOLPDF_DIR`, 기본 `../ToolPDF`)에서 빌드한다. ToolPDF 소스는 이 저장소에 들어 있지 않다.

## 3. Python 직접 의존성

실행에 필요하다. 모두 퍼미시브 라이선스다.

| 패키지 | 버전 | 라이선스 |
|---|---|---|
| fastapi | 0.142.1 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| sse-starlette | 3.5.0 | BSD-3-Clause |
| python-multipart | 0.0.32 | Apache-2.0 |
| pydantic-settings | 2.15.0 | MIT |
| SQLAlchemy | 2.1.1 | MIT |
| langgraph | 1.2.12 | MIT |
| qdrant-client | 1.19.1 | Apache-2.0 |
| openai | 3.22.1 | Apache-2.0 |
| filetype | 1.2.0 | MIT |
| PyYAML | 6.0.3 | MIT |
| numpy | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| httpx | 0.28.1 | BSD-3-Clause |

내장 PDF 엔진(`backend/app/engines/local`)이 쓴다.

| 패키지 | 버전 | 라이선스 | 쓰는 곳 |
|---|---|---|---|
| pypdfium2 | 5.13.0 | Apache-2.0 또는 BSD-3-Clause. 함께 든 PDFium 바이너리는 BSD-3-Clause와 아래 제3자 라이선스 | 열기, 암호 해제, 쪽 수, 렌더, 경로 개수 |
| pdfplumber | 0.11.10 | MIT | 표 찾기, 쪽 해석 |
| pdfminer.six | 20260107 | MIT | 글자, 글꼴 크기, 선, 이미지 위치 |
| Pillow | 12.3.0 | MIT-CMU | 잘라내기, JPEG, 흑백, 칠하기 |
| reportlab | 5.0.1 | BSD-3-Clause | 이미지 → PDF, Office 자체 렌더링 |
| python-docx | 1.2.0 | MIT | docx 구조 |
| python-pptx | 1.0.2 | MIT | pptx 구조, 차트 데이터 |
| openpyxl | 3.1.5 | MIT | xlsx 표 |

pdfminer.six가 받는 `cryptography`(Apache-2.0 또는 BSD-3-Clause), `cffi`(MIT-0), `charset-normalizer`(MIT)도 퍼미시브다. pypdfium2에 든 PDFium 바이너리는 FreeType(FTL 또는 GPLv2 중 **FTL**을 따른다), libjpeg-turbo(IJG, BSD-3-Clause), libpng, libtiff, zlib, OpenJPEG(BSD-2-Clause), Little CMS(MIT), ICU(Unicode), abseil(Apache-2.0), AGG 2.3 등을 담고 있다. 각 전문은 설치된 `pypdfium2-<버전>.dist-info/licenses/`에 있다. FTL이 요구하는 고지: Portions of this software are copyright © The FreeType Project (www.freetype.org). All rights reserved.

개발 전용이다.

| 패키지 | 버전 | 라이선스 |
|---|---|---|
| pytest | 9.1.1 | MIT |
| psutil | 7.2.2 | BSD-3-Clause |

같이 설치되는 라이브러리 가운데 카피레프트가 하나 있다. `langgraph-sdk`가 요구하는 `orjson`은 `MPL-2.0 AND (Apache-2.0 OR MIT)`다. MPL-2.0은 orjson 파일 자체에 적용된다. 이 저장소의 소스에는 퍼지지 않는다. 그 외 `langchain-core`(MIT), `lxml`(BSD-3-Clause), `grpcio`(Apache-2.0), `protobuf`(BSD-3-Clause) 같은 간접 의존성은 설치 환경에만 있고 소스 트리에는 없다.

## 4. 프론트엔드

`frontend/package-lock.json` 기준이다. `node_modules`와 `frontend/dist`는 저장소에 넣지 않는다.

| 패키지 | 버전 | 용도 | 라이선스 |
|---|---|---|---|
| react | 19.3.0 | 실행 | MIT |
| react-dom | 19.3.0 | 실행 | MIT |
| typescript | 5.9.3 | 개발 | Apache-2.0 |
| vite | 8.3.1 | 개발 | MIT |
| @vitejs/plugin-react | 6.1.1 | 개발 | MIT |
| @types/react | 19.3.0 | 개발 | MIT |
| @types/react-dom | 19.3.0 | 개발 | MIT |

Vite가 개발 의존성으로 받는 `lightningcss` 1.33.0은 MPL-2.0이다. 이것도 해당 패키지 파일에 한정된다. 빌드된 CSS를 이 저장소에 넣지는 않는다.

## 5. 이 저장소에 없는 모델과 도구

권장 모델은 받아서 쓰는 가중치다. 배포하거나 반입하기 전에 해당 모델 카드를 다시 확인한다.

| 모델 | 용도 | 모델 카드에 적힌 라이선스 |
|---|---|---|
| [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) | 임베딩 | MIT |
| [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) | rerank | Apache-2.0 |
| [Qwen/Qwen2.5-VL-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct) | VLM | Apache-2.0 |
| [Qwen/Qwen2.5-VL-3B-Instruct](https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct) | VLM 평가 비교에만 사용(`evals/results/vlm/`) | **Qwen Research License: 비상업(연구·평가) 전용.** 상업 서비스에 쓰려면 Alibaba Cloud의 별도 허가가 필요하다 |

LibreOffice는 선택 설치다. ToolPDF 쪽에 두거나, 내장 엔진을 쓰면 앱이 도는 PC에 둔다(`RAG_SOFFICE_PATH` 또는 PATH). doc/ppt/hwp 변환에 쓸 때만 필요하며 별도 프로세스로 실행하고 링크하지 않는다. [MPL-2.0](https://www.libreoffice.org/about-us/licenses/)이다. Ollama를 개발 PC에서 쓰는 경우에도 그 프로그램과 받아 둔 모델의 라이선스를 따로 따른다. Ollama 자체는 MIT다.

운영 VLM(예: Qwen3-VL), vLLM, Open WebUI는 이 저장소와 HTTP로만 통신하는 별도 프로그램이다. 각자의 라이선스를 따른다.

**Docker Desktop**은 Docker 구독 약관을 따른다. 개인, 교육, 비상업 오픈소스, 그리고 직원 250명 미만이면서 연매출 1천만 달러 미만인 회사에서만 무료다. 그보다 큰 조직의 업무용은 유료 구독이 필요하다. 이 저장소의 스크립트는 WSL이나 리눅스의 Docker Engine으로도 동작한다. Docker Engine과 Singularity/Apptainer는 오픈소스라 이 조건이 없다.

## 6. 배포 묶음에 들어가는 이미지

`scripts/build_offline_bundle.py`가 만드는 묶음(`release/`, 저장소에는 넣지 않음)에는 다음 이미지가 들어간다. 묶음은 두 형태다. 기본은 ToolPDF와 함께(`ingestlens-<버전>-offline.tar`), `--pdf-engine local`이면 ToolPDF 없이(`ingestlens-<버전>-local-offline.tar`, `toolpdf/` 폴더 없음, 묶음 전체가 퍼미시브 라이선스). 앱 이미지는 두 형태가 같다. 묶음을 회사 밖으로 배포하면 아래 구성 요소의 라이선스 조건도 함께 지켜야 한다.

| 이미지 | 들어 있는 것 |
|---|---|
| ToolPDF (`toolpdf/` 폴더: `toolpdf-<버전>-docker.tar.gz`, `toolpdf-<버전>.sif`, ToolPDF와 함께인 형태만) | ToolPDF(AGPL-3.0), PyMuPDF(AGPL-3.0), ToolPDF의 Python 패키지, 기반 이미지 `python:3.12-slim`. 같은 폴더에 ToolPDF 소스, PyMuPDF 소스, 패키지 목록, `LICENSE`, `NOTICE.md`, `BUNDLE.md`가 함께 있다. 자세한 조건은 `toolpdf/BUNDLE.md` |
| 앱 (`ingestlens:<버전>`, `ingestlens-app.sif`) | IngestLens(MIT), 3절의 Python 패키지(내장 PDF 엔진 포함), 빌드된 프론트엔드(4절의 실행 패키지), 나눔 글꼴(Debian `fonts-nanum`, SIL OFL 1.1: 내장 엔진이 Office 문서를 그릴 때 쓴다), 기반 이미지 `python:3.12-slim`(Debian 패키지, 각 패키지의 라이선스) |
| 모델 서버 (`ingestlens-model-server.sif`, `--singularity`일 때) | `docker/model-server/server.py`(MIT), PyTorch(BSD-3-Clause), PyTorch wheel에 포함된 NVIDIA CUDA 런타임 라이브러리(NVIDIA 라이선스, 재배포 허용 범위), transformers·tokenizers·safetensors(Apache-2.0), fastapi(MIT), uvicorn(BSD-3-Clause), 기반 이미지 `python:3.12-slim` |

- `toolpdf/` 폴더는 빼거나 이미지만 따로 넘기지 않는다. 그 폴더가 AGPL 소스 제공 의무를 채운다(2절).
- 모델 가중치는 이미지에 넣지 않는다. 5절의 모델 카드 라이선스를 따른다.
- 빌드 PC의 추가 인증서(`docker/certs/*.crt`)는 이미지에 남지 않는다.
- `.sif` 변환에 쓰는 Apptainer(BSD-3-Clause)는 빌드 도구일 뿐이고 묶음에는 들어가지 않는다.
