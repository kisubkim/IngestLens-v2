# 진행 상황

최종 갱신: 2026-10-09

전체 상태, 설계 이유, 운영 절차는 `docs/HANDOFF.md`에 있다. 이 문서는 2026-10-04부터 한 작업의 진행 상황을 정리한다.
- 10-04 오전: 로컬 실제 모델 검증, VLM 평가 체계
- 10-04 오후: 테스트 실행 스크립트, 화면 기능(현황판, 상태 표시, 삭제, 파싱 통계), 임베딩 모델 조사
- 10-05: 오프라인 배포 묶음(Docker), 임베딩·rerank 단일 프로세스 모델 서버
- 10-06: Singularity/Apptainer 이미지, 오프라인 서버에서 사용자 시험(문서 삭제 버그 발견)
- 10-07: 문서 삭제 키 버그 수정, Open WebUI v0.11.3 실제 연동 검증과 가이드, 출처 쪽 번호 수정
- 10-08 밤: Docker Desktop을 지우고 WSL Ubuntu의 Docker Engine으로 이전
- 10-08: Open WebUI 답변과 출처 팝업에 쪽 이미지 보여주기, 가로 문서 시험, 화면의 Open WebUI 파일 이름 정리, 앱 sif `20261008`(실제 모델로 동작 확인)
- 10-08~09: PDF 처리를 모두 PDF 엔진 ToolPDF(별도 프로그램, HTTP API)로, 라이선스 MIT, 배포 묶음에 ToolPDF 포함
- 10-09: Windows PC 가이드(`docs/WINDOWS.md`)와 Docker 없는 실행 스크립트(`setup_local.bat`, `start_local.bat`, `stop_local.bat`)

## 1. 한눈에 보기

| 항목 | 상태 |
|---|---|
| 실제 모델로 파이프라인 전체 실행 | 완료. Docker 위의 Ollama(`qwen2.5vl:7b`, `bge-m3`)와 rerank 서버로 업로드부터 검색까지 성공 |
| VLM 품질 평가 도구와 비교 화면 | 완료. `scripts/eval_vlm.py`, 앱의 "VLM 평가 비교" 화면(`/#evals`) |
| 평가 문서 | 완료. 합성 5페이지, 실제 공개 문서 10종 50페이지 |
| 평가에서 찾은 파이프라인 문제 | 2건 수정(괄호 캡션, 답변 잘림 재시도), 나머지는 "5. 다음에 할 일" |
| 테스트 실행 스크립트 | 완료. `start_test.bat`/`stop_test.bat`, `start_test.sh`/`stop_test.sh` |
| Docker에서 저장 위치 설정이 잠기는 문제 | 수정 완료 |
| 첫 화면 현황판, 백엔드 상태 표시, 문서 삭제, 파싱 통계 | 완료 |
| 임베딩 모델 조사 | 완료. `docs/EMBEDDING_MODELS.md` |
| 오프라인 배포 묶음 | 완료. Docker + Singularity(`.sif`) 파일 하나, 약 4.2GB (2-14, 2-16) |
| 임베딩·rerank 모델 서버 | 완료. GPU 1장, 프로세스 1개로 두 모델 (2-15) |
| Open WebUI 연동 | 완료. v0.11.3으로 파일 추가 → 처리 → 지식 베이스 → LLM 답변까지 확인, `deploy/OPENWEBUI.md` (2-18) |
| Open WebUI 답변에 쪽 이미지 | 완료. 필터 함수로 답변의 썸네일 줄(누르면 펼침)과 출처 팝업 이미지, 가로·세로 문서, v0.11.3 화면에서 확인 (2-20) |
| 오프라인 서버 시험 | 진행 중. 사용자가 sif로 앱 실행, 문서 하나 삭제 실패 버그를 찾아 고침(2-17). 고친 내용과 쪽 이미지 기능은 아직 서버에 반영 전. 다음 반입은 ToolPDF를 넣은 새 묶음으로 한다 (2-20, 2-22) |
| PDF 엔진 ToolPDF | 완료. 모든 PDF 처리를 HTTP API로, 테스트 61개(두 전송 방식), Docker 스택과 배포 묶음에 포함 (2-22) |
| WSL에서 구동 | 보류(사용자 결정, 나중에) |
| 운영 대상(vLLM, 큰 VL 모델)으로 검증 | 아직 안 함. 운영 VLM은 Qwen3-VL(사용자 서버에서 운영 중) |

## 2. 완료한 것

### 2-1. 로컬 실제 모델 스택 (Docker)

- `docker compose up -d --build` 한 번으로 아래 4개 컨테이너가 뜬다. 앱 화면은 http://localhost:8000 이다.

  | 컨테이너 | 역할 |
  |---|---|
  | `app` | IngestLens |
  | `ollama` | VLM과 임베딩 모델 서빙(GPU) |
  | `ollama-pull` | 첫 실행 때 모델을 받고 종료 |
  | `reranker` | rerank 서버 |

- 모델 크기는 합쳐서 약 9.5GB이고 Docker 볼륨에 저장된다.
  - VLM: `qwen2.5vl:7b` (6.0GB)
  - 임베딩: `bge-m3` (1.2GB)
  - reranker: `BAAI/bge-reranker-v2-m3` (약 2.3GB, CPU)
- Ollama에는 rerank 기능이 없다. 그래서 rerank 서버를 따로 만들었다. 지금은 2-15의 모델 서버(`docker/model-server/`)를 rerank 전용, CPU로 띄운다. 요청 형식은 vLLM과 같다.
- 설정 파일은 두 개다.
  - 컨테이너 안에서 쓰는 주소: `config/models.docker.yaml`
  - 호스트에서 평가 스크립트를 돌릴 때 쓰는 주소: `config/models.docker-host.yaml` (Ollama 11435, reranker 8081 포트)
- 포트 세 개(8000, 11435, 8081)는 모두 이 PC(`127.0.0.1`)에서만 열린다.
- 백신이나 프록시가 HTTPS를 가로채는 PC를 위해 `docker/certs/`에 추가 인증서를 넣는 방법을 만들었다(아래 "4. 막혔던 문제").

### 2-2. 테스트 실행 스크립트

| 파일 | 용도 |
|---|---|
| `start_test.bat` | Windows. WSL 배포판(기본 `Ubuntu-24.04`)의 Docker Engine으로 컨테이너를 띄우고, 앱이 응답하면 브라우저를 연다(10-08부터, 2-21) |
| `stop_test.bat` | Windows 중지. 받아 둔 모델과 올린 문서는 남는다 |
| `start_test.sh` / `stop_test.sh` | Linux·macOS·WSL 안. Windows Git Bash에서는 `docker`가 없으면 WSL의 Docker Engine을 쓴다 |
| `.gitattributes` | bat은 CRLF, sh는 LF 줄바꿈을 유지한다. 줄바꿈이 바뀌면 스크립트가 고장 난다 |

테스트용이라 이름 뒤에 `_test`를 붙였다.

### 2-3. VLM 품질 평가 도구

- `scripts/eval_vlm.py`가 평가 세트를 파이프라인 전체로 처리하고 페이지마다 채점한 뒤, 결과를 `evals/results/vlm/<시각>_<이름>.json`에 저장한다. 채점 함수는 `backend/app/tools/vlm_checks.py`에 있다.
- 채점 항목은 다음과 같다.
  - 페이지 분류
  - OCR 문자 오류율
  - 핵심 사실 포함
  - 제목 인식
  - 본문을 1열 표로 만들지 않았는지
  - 표 셀 값, 표 열 수
  - 그림 종류(TYPE)
  - 그림 속 값과 라벨
  - 한국어로 답했는지
  - 캡션 연결
- 결과 파일에 함께 남기는 정보: 모델 설정(api_key 제외), git 커밋, prompt 해시, 평가 세트 이름과 버전, 속도, 페이지별 출력 전체
- 평가 세트 버전은 기대값과 페이지 렌더링으로 계산한다. 문서나 기대값이 바뀌면 버전도 바뀐다.
- "VLM 평가 비교" 화면(`/#evals`)
  - 평가 세트별 탭에서 결과 파일을 최대 4개까지 골라 나란히 비교한다.
  - 비교 내용: 요약 점수, 페이지별 통과·실패, 출력 원문과 정답
  - 세트 버전이나 prompt가 다른 결과를 섞어 고르면 경고한다.

### 2-4. 평가 문서

| 세트 | 위치 | 내용 |
|---|---|---|
| 합성 5페이지 | `evals/vlm/` | 직접 만든 PDF. 텍스트 대조군, 스캔 본문, 스캔 표, 막대 차트, 공정 흐름도. 정답을 정확히 알아서 OCR 문자 오류율을 잰다 |
| 실제 공개 문서 10종 | `evals/samples/` | 50페이지 중 17페이지, 43개 항목을 채점한다 |

실제 공개 문서 10종의 구성:

| 유형 | 문서 |
|---|---|
| 한국어 글자 위주 | 위키백과 「훈민정음」 |
| 사진 위주 | 위키백과 「경복궁」 |
| 벡터 차트 위주 | 위키백과 「대한민국의 인구」 |
| 차트 + 표 | 국가데이터처 「2025년 8월 인구동향」 보도자료 |
| 표 위주 | 같은 보도자료의 통계표 |
| 한국어 스캔 | 같은 보도자료를 이미지로 바꾼 것 |
| 혼합 | 위키백과 「서울특별시」 |
| 영어 실제 스캔 | 1953년 NACA 보고서 |
| 영어 본문 + 구성도 | NIST SP 800-207 |
| 영어 논문 | Docling 기술 보고서 |

- 저장소가 공개되어 있어서 재배포와 일부 발췌가 허용된 자료만 골랐다. 공공누리 제1유형, CC BY, CC BY-SA, 미국 연방정부 저작물이다.
- 문서마다 출처와 라이선스를 `evals/samples/SOURCES.md`에 적었다. `NOTICE.md`에는 이 파일들에 저장소의 라이선스가 적용되지 않는다는 예외를 넣었다.
- 커밋된 PDF가 기준이다. 기대값(`cases.json`)은 페이지 이미지를 직접 보고 적었다.

### 2-5. 파이프라인 수정

- **괄호로 시작하는 캡션 연결**: `[그림 1]`, `<표 1>`, `【그림 1】`, `(Figure 4)`도 캡션으로 인식한다(`config/strategy_rules.yaml`의 `parse.captions.pattern`).
- **잘린 VLM 답변 다시 요청**
  - 답변이 `max_tokens`(2048)에서 끊기면 `max_tokens_retry`(기본 4096)로 한 번 더 요청한다.
  - 다시 요청한 기록은 결정 기록(`vlm_truncated_retry`)에 남고, 파싱 요약에 `vlm_retried` 횟수가 나온다.
  - 늘어난 출력이 들어가도록 Docker의 Ollama 컨텍스트 길이를 8192에서 12288로 올렸다.

### 2-6. 저장 위치 설정 수정 (Docker)

- **증상:** Docker로 실행하면 저장 위치 설정 화면의 입력칸이 모두 잠겨 값을 바꿀 수 없었다.
- **원인:** 이 화면은 "서버가 돌아가는 PC에서 접속했을 때만" 바꿀 수 있다. 그런데 Docker를 거치면 같은 PC의 브라우저 요청도 Docker 내부 주소(`172.18.0.1`)에서 온 것으로 보였다.
- **해결**
  - 앱 포트를 이 PC에서만 열었다.
  - Docker 내부 주소 대역을 `RAG_ADMIN_HOSTS`에 넣어 "이 PC"로 인정한다.
  - 같은 이유로 Ollama와 reranker 포트도 이 PC에서만 열었다.
- **데이터 폴더:** Docker에서는 컨테이너 안 `/data`로 고정이라 잠긴 상태가 정상이다. PC의 어느 폴더를 쓸지는 `.env`의 `INGESTLENS_DATA_DIR`로 정하고, 화면에 그 방법을 안내한다.
- 다른 PC에서 접속하게 하려면 앱 포트를 `"8000:8000"`으로 바꾸고 `RAG_API_KEY`를 설정한다.

### 2-7. 첫 화면: 임베딩 DB 현황 (`GET /api/overview`)

- 문서를 고르지 않았을 때나 왼쪽 위 "IngestLens"를 누르면 보인다.
- 보여주는 것:
  - 문서 수, 원본 용량, 페이지 수, 형식별 개수
  - 벡터 수, 청크 수(문서별 최신 실행), 임베딩 모델(dev-hash면 경고)
  - 실행 결과별 개수
  - 데이터 폴더별 디스크 사용량, 임베딩 모델별 벡터 컬렉션
  - 최근 문서: 누르면 그 문서가 열린다

### 2-8. 백엔드 상태 표시 (`GET /api/status`)

- 왼쪽 아래에 상태가 색으로 표시되고, 15초마다 다시 확인한다.
  - 🟢 정상, 🟡 주의, 🔴 오류 또는 연결 안 됨
- 누르면 상세 화면(`/#status`)이 열린다. 확인 항목은 다음과 같다.
  - API 서버, DB, 벡터 DB
  - 임베딩, VLM, reranker: 설정한 모델이 그 서버에 실제로 있는지까지 본다
  - LibreOffice
  - 실행 대기열
- rerank 서버를 일부러 끄고 켜서 🔴 → 🟢로 바뀌는 것을 확인했다.

### 2-9. 문서 삭제

- **문서 하나:** 문서 화면 오른쪽 위 "문서 삭제"(`DELETE /api/documents/{id}`)
- **전체:** 저장 위치 설정 아래 "데이터 비우기 → 전체 삭제"(`DELETE /api/documents?confirm=all`). "전체 삭제"를 직접 입력해야 실행된다.
- 지우는 것: DB 기록(문서, 실행, 이벤트, 결정, 페이지 분석, element, 청크), Qdrant 벡터, 검색 캐시, 원본, 변환 PDF, 페이지 이미지
- 실행 중이거나 대기 중인 문서는 지울 수 없다. 저장 위치 설정과 같이 이 PC나 API 키로만 허용한다.
- Docker 환경에서 시험용 문서로 삭제를 확인했다. 사용자 문서는 건드리지 않았다.

### 2-10. 파싱 리포트 개선

- 위쪽에 요약 카드를 넣었다: 전체 element 수, 유형별 개수, 페이지당 평균, VLM으로 읽은 페이지, element가 없는 페이지
- **페이지별 element 개수 막대 차트**를 넣었다(`GET /api/runs/{id}/element-stats`). 유형별 색으로 쌓아 보여주고, 막대를 누르면 그 페이지로 이동한다.
- 배치를 요약·차트 → 썸네일 → 상세 순서로 바꿨다. 탭을 열면 1페이지가 바로 보인다.
- 페이지를 고르면 화면이 자동으로 내려가던 동작을 없앴다.

### 2-11. 임베딩 모델 조사 (`docs/EMBEDDING_MODELS.md`)

- 지금 쓰는 bge-m3: 1024차원, 8192토큰, MIT
- 후보 9개를 차원, 입력 길이, 라이선스로 비교했다: KURE-v1, BGE-m3-ko, Qwen3-Embedding, arctic-embed, gte, e5, embeddinggemma, jina-v3
- 모델을 바꾸려면 `models.yaml`만 바꾸면 된다. 다만 기존 문서를 다시 실행해야 새 모델로 검색된다.
- e5와 Qwen3-Embedding은 질의 접두어가 필요한데, 지금 코드는 지원하지 않는다.

### 2-12. 라이선스 확인

| 대상 | 라이선스 | 판단 |
|---|---|---|
| 실행 스크립트(`*_test.bat`, `*_test.sh`) | 이 저장소(MIT) | 문제없음. `docker` 명령만 부르고 남의 코드를 담지 않는다 |
| Docker Desktop | Docker 구독 약관 | 개인, 교육, 직원 250명 미만이면서 매출 1천만 달러 미만인 회사만 무료. 더 큰 회사의 업무용은 유료 |
| `qwen2.5vl:7b` | Apache-2.0 | 상업 사용 가능 |
| `qwen2.5vl:3b` | Qwen Research License | **비상업(연구·평가) 전용.** 평가에만 썼으므로 문제없음 |
| Ollama / bge-m3 / bge-reranker-v2-m3 | MIT / MIT / Apache-2.0 | 상업 사용 가능 |

### 2-13. 기타

- 검색 평가(`eval_retrieval.py`)를 실제 임베딩으로 측정해 `evals/reports/retrieval_synthetic_ollama.md`에 보고서를 남겼다.
- 테스트는 46개에서 62개로 늘었고 모두 통과한다(10-07 기준).
- 갱신한 문서: `README.md`, `docs/HANDOFF.md`, `evals/README.md`, `NOTICE.md`

### 2-14. 오프라인 배포 묶음 (10-05)

- `python scripts/build_offline_bundle.py`가 파일 하나(`release/ingestlens-<버전>-offline.tar`)를 만든다.
  - 앱 Docker 이미지, `docker-compose.yml`, `models.yaml`, `.env`, `install.sh`, 설치 안내서(`deploy/README.md`), `VERSION`, `SHA256SUMS`
  - 서버에서는 `tar xf` 후 `./install.sh`. 무결성 확인, 이미지 불러오기, 시작까지 한다.
- 버전 이름은 빌드한 날짜(`20261006` 형식)다. 커밋은 `VERSION` 파일과 이미지 정보에 남는다.
- 빌드 PC의 Norton 인증서는 패키지를 받는 동안만 쓰고 이미지에 남기지 않는다(0건 확인). 개발용과 배포용 이미지를 따로 만들지 않는다.
- 확인: 이미지를 지우고 묶음만으로 설치·실행·검색, 네트워크를 끊은(`--network none`) 컨테이너에서 문서 처리·검색, 운영 설정에서 키 없는 설정 변경·삭제는 401.
- `/api/health`와 백엔드 상태 화면에 배포 버전이 보인다.

### 2-15. 임베딩·rerank 모델 서버 (10-05)

- **배경:** 운영 서버의 남는 GPU(H100 또는 A100 80GB) 1장은 프로세스 1개만 허용하고, root 권한이 없어 모드를 바꿀 수 없다. vLLM은 프로세스 하나에 모델 하나라 임베딩과 reranker를 함께 띄울 수 없다. VLM(Qwen3-VL)은 이미 따로 운영 중이다.
- **해결:** `docker/model-server/server.py`가 bge-m3와 bge-reranker-v2-m3를 **한 프로세스**에 올린다.
  - torch, transformers, fastapi, uvicorn만 쓴다. vLLM이 설치된 Python으로 root나 Docker 없이 실행한다(`deploy/model-server.sh`).
  - vLLM과 같은 API: `/v1/embeddings`, `/v1/rerank`, `/tokenize`, `/v1/models`. 앱은 주소만 바꾸면 된다.
- **확인(이 PC의 RTX 5070 Ti):**
  - GPU 컴퓨트 프로세스 1개
  - bge-m3 벡터가 Ollama bge-m3와 같음(코사인 1.0)
  - 임베딩 210개 0.75초, rerank 15개 0.06초
  - 앱 컨테이너가 호스트의 모델 서버에 붙어 처리·`/tokenize` 측정·rerank까지 동작
- 개발용 Docker 스택의 reranker도 같은 서버로 바꿨다(rerank 전용, CPU).
- Open WebUI도 같은 모델 서버를 쓸 수 있다. 외부 reranker 요청 형식을 Open WebUI 소스와 맞춰 확인했다.

### 2-16. Singularity/Apptainer 이미지 (10-06)

- `--singularity`: GPU용 모델 서버 이미지(CUDA 12.8 torch)를 빌드하고, 앱과 모델 서버 이미지를 공식 Apptainer 컨테이너로 `.sif`로 바꿔 묶음에 넣는다. `--no-docker`는 Docker 이미지를 뺀다.
- 서버에서는 `./singularity.sh start`로 앱과 모델 서버를 root·Docker 없이 띄운다. 모델 서버 이미지에 torch가 들어 있어 vLLM 환경이 없어도 된다.
- 앱 이미지의 시작 명령을 Singularity에 맞췄다: 실행 폴더와 상관없이 동작(`--app-dir`), 포트는 `INGESTLENS_PORT`.
- 확인: Apptainer 1.4.5 안에서 두 `.sif`로 문서 처리·임베딩·검색·rerank(모델 서버 CPU). 같은 모델 서버 이미지를 Docker GPU로 확인. Singularity `--nv`(GPU)는 Windows에서 시험할 수 없었다.
- 그때 묶음: `release/ingestlens-20261006-offline.tar` (4.2GB). 저장소에는 넣지 않는다.

### 2-17. 오프라인 서버 시험에서 찾은 버그 (10-06~07)

- **문서 하나 삭제가 항상 "API 키가 맞지 않습니다"로 실패:** 문서 화면의 "문서 삭제"가 관리자 키를 보내지 않았다. 전체 삭제는 설정 화면의 키를 보내서 됐다.
  - 고침: 키가 없거나 틀리면 관리자 키를 묻고 다시 삭제한다. 맞은 키는 그 브라우저 탭에서만 기억한다.
  - RAG_API_KEY를 설정한 서버로 재현해 브라우저에서 확인했다.
- **저장 위치 설정의 저장 버튼이 안 켜짐:** 버그가 아니라 조건이다. 값을 하나 이상 바꿔야 켜진다. Docker·Singularity에서 데이터 폴더는 잠겨 있는 것이 정상이다. 이유를 화면에 보여주는 개선은 남은 일이다.

### 2-18. Open WebUI v0.11.3 연동 검증과 가이드 (10-07)

- 이 PC에서 Open WebUI v0.11.3을 개발 스택에 실제로 붙였다.
  - 파일 추가 → IngestLens 처리(약 10초) → 청크 26개 → Open WebUI 지식 베이스에 그대로 26개
  - LLM(qwen2.5vl:7b)이 지식 베이스를 검색해 정답("TableFormer, 2022년")과 정확한 출처(3쪽)를 냈다.
- 찾은 문제 두 가지:
  - **Open WebUI가 청크를 다시 자른다.** 기본 설정이면 49개가 58개가 되고 큰 표가 잘렸다. `CHUNK_SIZE=8000`, `CHUNK_OVERLAP=0`, `ENABLE_MARKDOWN_HEADER_TEXT_SPLITTER=false`로 막는다.
  - **출처 쪽 번호가 1씩 크게 보였다.** Open WebUI는 `page`를 0부터로 보고 +1 해서 보여준다. 앱이 `page`를 0부터, `page_label`·`pages`는 1부터 보내도록 고쳤다.
- 가이드: `deploy/OPENWEBUI.md`. 동작 방식, 주소 정하기, 환경 변수와 관리자 화면 설정, 사용법, 확인 순서, 시험 결과, 문제 해결을 담았다. 다음 묶음부터 함께 들어간다.
- LLM이 IngestLens 검색 API를 직접 부르는 방식은 아직 안 된다. 모든 문서를 대상으로 하는 검색 API가 없다.

### 2-20. Open WebUI 답변에 쪽 이미지 (10-08)

- `GET /api/chunks/{id}/preview.png?page=&dpi=`: 청크가 있는 쪽을 그리고 청크 영역을 주황색으로 칠한 이미지. 원본 PDF는 바꾸지 않고, 쪽 이미지 캐시(`pages/{문서}/`)에 함께 저장하므로 문서를 지우면 같이 지워진다. `highlight=false`면 칠하지 않은 쪽. 쪽 이미지 해상도 하한을 36에서 18 dpi로 낮췄다.
- `deploy/openwebui_page_images.py`: Open WebUI 필터 함수. 답변이 끝나면(outlet) 출처 메타데이터의 `document_id`, `chunk_id`, `page`로
  - 답변에 "참고한 쪽" 썸네일 줄을 임베드(iframe)로 붙이고(누르면 그 자리에서 크게 펼침, 다시 누르면 접힘),
  - 같은 문서 이름으로 `source` 이벤트를 보내 출처 팝업에 큰 이미지를 넣는다.
- v0.11.3에서 화면으로 확인했다. 확인하면서 찾은 것:
  - 0.11은 답변을 `content`가 아니라 `output` 항목에서 그리고 저장한다. 필터가 둘 다 고쳐야 화면에 나온다.
  - HTML 주석과 `<img>` 태그는 글자로 보인다.
  - 처음에는 Markdown 이미지로 썸네일을 붙였다. 그런데 Open WebUI가 이미지를 원래 크기로 그리고, 눌렀을 때의 미리보기도 원래 크기까지만 키운다. 링크로 큰 이미지를 걸면 창이 두 개 열려 두 번 닫아야 했다(사용자 지적). 그래서 임베드로 바꿨다. iframe 높이는 `postMessage({type: "iframe:height"})`로 맞춘다.
  - 가로 문서(16:9 pptx 4장)와 세로 문서(A4 PDF)로 시험했다. 썸네일은 긴 변 220px, 펼치면 답변 폭(최대 높이 900px).
  - 필터의 출처 변경(`sources`)은 저장되지 않고, `__event_emitter__`의 `source` 이벤트는 저장된다.
- 설치 방법: `deploy/OPENWEBUI.md` 10절(준비, 설치, 밸브 바꾸기, 필터 갱신, 확인 순서와 문제 해결, 주의). 이미지는 사용자 브라우저가 IngestLens에서 직접 받으므로 `INGESTLENS_URL`은 사용자 PC에서 열리는 주소다.
  - 밸브(`MAX_PAGES`, `THUMB_SIZE`, `BIG_HEIGHT`, `DPI`, `HIGHLIGHT` 등)는 Open WebUI 관리자 패널 → 함수 → 톱니바퀴에서 바꾼다. 저장하면 바로, 새 답변부터 적용된다.
  - 썸네일은 그 답변에 쓰인 출처 쪽만(기본 최대 3쪽) 보여준다. 문서 쪽수와 관계없고, 많아지면 다음 줄로 넘어간다.
- IngestLens 화면의 문서 이름: Open WebUI가 붙여 보내는 `<UUID>_`를 떼고 보여준다(`displayName`, 문서 목록·문서 제목·삭제 확인·첫 화면). DB의 이름은 그대로 두고, 마우스를 올리면 전체 이름이 보인다.
- 앱 sif 묶음: `release/app-sif-20261008.tar`(약 145MB). `ingestlens-app.sif`, 필터 파일, `OPENWEBUI.md`, `VERSION`, `SHA256SUMS`가 들어 있다. 모델 서버 sif는 바뀌지 않았다. ToolPDF가 들어가기 전의 앱이라, 서버 반입은 2-22의 새 묶음으로 한다.
  - 동작 확인: sif를 `singularity.sh start-app`과 같은 인자로 Apptainer 컨테이너에서 띄우고 개발 스택의 실제 모델(qwen2.5vl:7b, bge-m3, reranker)에 연결했다. 상태 점검 모두 정상(LibreOffice는 원래 없음). Open WebUI 로더 경로로 `<UUID>_이름` 파일을 넣어 세로 PDF 54초·청크 49개, 가로 pptx 5초·청크 6개, 틀린 키는 401. 쪽 이미지(칠함·안 칠함), hybrid+rerank 검색, 화면의 이름 정리, 키를 넣은 문서 하나 삭제까지 확인했다. sif 앱에 Open WebUI 화면을 직접 붙여 보지는 않았다(같은 코드의 Docker 앱으로 확인).

### 2-21. Docker를 WSL의 Docker Engine으로 이전 (10-08)

- 이유: Docker Desktop이 꺼져 있거나 엔진이 500을 내며 멈추는 일이 이틀 연속 있었다. WSL 메모리 한도 9GB에서 Ollama가 OOM으로 죽은 기록도 있었다.
- WSL `Ubuntu-24.04`에 Docker Engine 29.8, Compose v5.6, NVIDIA Container Toolkit 설치. 컨테이너에서 RTX 5070 Ti 확인.
- 볼륨(Ollama 모델, reranker 모델, Open WebUI 시험 데이터)을 tar로 옮겼다. Compose 표시(label)를 붙여 다시 만들었다.
- `.wslconfig`: `instanceIdleTimeout=-1`(없으면 세션이 끝날 때 배포판과 Docker가 꺼짐), `memory=24GB`, `vmIdleTimeout=-1`. Windows 시작 때 자동으로 띄우지는 않는다(사용자 결정).
- Docker Desktop은 제거했고, 디스크(79GB)와 남은 설정 폴더도 지웠다.
- 스크립트: `start_test.bat`/`stop_test.bat`은 `wsl -d <배포판> -u root --cd <저장소> -- docker compose ...`로 실행한다. `.sh`는 Git Bash에서 `docker`가 없으면 WSL을 쓴다. `build_offline_bundle.py`도 같은 방식으로 빌드하고 경로를 `/mnt/d/...`로 바꾼다. 네 스크립트로 시작·중지를 한 바퀴 돌렸고, 빌드 스크립트의 `docker save | gzip`과 sif 변환을 작은 이미지로 확인했다.
- 확인: 앱 상태 모두 정상, Ollama 100% GPU, Open WebUI에서 지식 베이스 질문 → 정답과 쪽 썸네일 줄·출처 이미지.

### 2-22. PDF 엔진 ToolPDF와 MIT 라이선스 (10-08~09)

- 모든 PDF 작업(PDF로 바꾸기, 쪽 특징, 텍스트·표·그림 추출, VLM용 잘라낸 이미지, 쪽 이미지)을 별도 프로그램 [ToolPDF](https://github.com/kisubkim/ToolPDF)의 HTTP API로 한다. 연결 지점은 `backend/app/tools/toolpdf.py` 하나이고, 규약은 ToolPDF의 README다. 이 저장소에는 PDF 라이브러리가 없다.
- 파일 전달은 두 방식이다. `http`(기본, sha256로 한 번만 올림)와 `shared`(ToolPDF가 이 앱의 데이터 폴더를 공유 폴더로 마운트). 테스트 61개가 두 방식 모두 통과한다. `tests/conftest.py`가 `../ToolPDF`의 ToolPDF를 빈 포트로 띄운다.
- 라이선스: 이 저장소는 MIT, ToolPDF는 AGPL-3.0(PyMuPDF 때문). `NOTICE.md`에 둘의 관계와 배포할 때의 조건을 적었다.
- Docker 스택(`docker-compose.yml`)은 ToolPDF 이미지를 `../ToolPDF`에서 빌드해 공유 폴더 방식으로 붙인다.
- 배포 묶음: `build_offline_bundle.py`가 ToolPDF의 배포 폴더(`docker/release.sh`가 만든 `release/toolpdf-<버전>/`: Docker 이미지, `.sif`, ToolPDF 소스, PyMuPDF 소스, 라이선스)를 `toolpdf/`로 그대로 넣는다. AGPL 소스 제공을 ToolPDF가 정한 방식 그대로 채우기 위해서다.
  - `deploy/docker-compose.yml`에 `toolpdf` 서비스(포트는 밖에 열지 않음), `install.sh`가 ToolPDF 이미지도 불러온다. `.env`에 `TOOLPDF_VERSION`.
  - `singularity.sh`에 `start-pdf`/`stop pdf`/`logs pdf`. `start`는 ToolPDF → 모델 서버 → 앱 순서. Singularity는 호스트 네트워크라 ToolPDF 포트가 열리므로 묶음의 `singularity.env`에 임의의 `TOOLPDF_API_KEY`를 넣는다.
- 확인(10-09): 묶음 376MB. WSL의 Docker Engine에서 묶음만으로 설치해 상태의 PDF 엔진 정상, PDF 6쪽과 pptx 4장 처리 성공. Singularity 묶음과 오프라인 서버는 아직.
- 문서 정리: README, HANDOFF, PLAN, evals/README, deploy 문서를 ToolPDF 구조에 맞췄다. 평가 세트는 저장소에 커밋된 파일이 기준이다.

### 2-23. Windows PC에서 Docker 없이 실행 (10-09)

- `docs/WINDOWS.md`: 일반 Windows PC용 가이드. 준비물, 받기, 설치, 실행, 확인, 중지, Windows용 Ollama로 실제 모델 연결, reranker, 다른 PC에서 접속, 설정, LibreOffice, Docker 스택, 업데이트, 문제 해결. README 맨 앞에 "시작하기" 표를 두어 Windows PC, Docker, 오프라인 서버 가이드로 나눴다.
- `setup_local.bat`: ToolPDF가 없으면 받고(git), 두 저장소의 `.venv`와 패키지, 화면 빌드. 다시 실행해도 된다.
- `start_local.bat`: 앱 포트가 비었는지 먼저 보고, ToolPDF와 앱을 창 하나씩 띄워 응답을 기다린 뒤 브라우저를 연다. 포트, 받을 주소, ToolPDF 위치를 환경 변수로 바꾼다. `stop_local.bat`: 실행 명령으로 두 서버를 찾아 창째 끈다.
- `config/models.windows.yaml`: Windows용 Ollama(127.0.0.1:11434) 템플릿. `.env`에 `RAG_MODELS_FILE=config/models.windows.yaml` 한 줄로 쓴다. 이를 위해 경로 설정의 상대 경로를 저장소 폴더 기준으로 바꿨다(`config.py`).
- 확인: 세 스크립트를 이 PC에서 실행. 설치와 화면 빌드, 시작 약 9초, 포트 충돌 검사(ToolPDF를 띄우지 않고 멈춤), 중지 후 포트 해제. Docker의 Ollama(`qwen2.5vl:7b`, `bge-m3`)와 reranker에 연결해 sample.pdf 6쪽을 VLM OCR·그림 설명까지 처리하고 hybrid+rerank 검색. Windows용 Ollama 자체로의 연결은 이 PC의 Ollama에 모델이 없어 시험하지 못했다. 테스트 61개 통과.

### 2-19. 기타 (10-05~07)

- Open WebUI의 임베딩·rerank를 모델 서버에 맡기는 설정 예시(`deploy/README.md` 8절)
- `NOTICE.md`: qwen2.5vl:3b(비상업)와 Docker Desktop 약관 조건, 배포 묶음 이미지에 들어가는 구성 요소의 라이선스
- `docs/EMBEDDING_MODELS.md`: 모델 서버로 모델을 바꿀 때의 주의점

## 3. 측정 결과

환경: RTX 5070 Ti 16GB, Docker 위의 Ollama 0.35, Q4_K_M 양자화

### VLM 품질

| 모델 | 합성 5페이지 | 실제 공개 문서 10종 |
|---|---|---|
| `qwen2.5vl:7b` | 92% (19개 중 17개) | 90% (43개 중 36개) → 수정 후 **92%** (38개) |
| `qwen2.5vl:3b` | 86% (19개 중 16개) | 51% (43개 중 18개) |

- 7b에 남은 실패:
  - 사진과 차트 설명이 영어로 나온다.
  - 보도자료의 벡터 차트를 구성도(`diagram`)로 판단한다.
  - 선 없는 표를 표로 알아보지 못한다.
- 3b는 같은 말을 반복하다가 Ollama가 응답을 끊었다. VLM 호출 47번 중 41번이 이렇게 실패했다.

### 검색 품질 (합성 세트 22문항, 1등 적중률)

| 방식 | 전체 | 바꿔 쓴 질문 |
|---|---|---|
| dense(임베딩) | 95% | 88% |
| hybrid(임베딩 + 키워드) | 82% | 50% |
| hybrid + rerank | 100% | 100% |

실제 임베딩에서는 키워드 검색(BM25)이 바꿔 쓴 질문의 순위를 끌어내려서 hybrid가 dense보다 낮다.

### 속도

- 실제 문서 10종(50페이지) 전체 처리: 7b로 약 400초. VLM 1회 평균은 약 11~13초.
- rerank 후보 15개: CPU로 1.6~2.2초.
- 모델 서버(GPU, RTX 5070 Ti): 임베딩 210개 0.75초, rerank 15개 0.06초, GPU 메모리 약 2.3GB.

### Open WebUI 청크 보존 (10-07)

| Open WebUI 청크 설정 | IngestLens 청크 | Open WebUI 저장 조각 |
|---|---|---|
| 기본값(1000자, 겹침 100, Markdown 헤더 분할) | 49개 | 58개 (큰 표 9개 잘림) |
| `CHUNK_SIZE=8000`, 겹침 0, 분할 끔 | 26개 | 26개 |

## 4. 막혔던 문제와 해결

| 문제 | 원인 | 해결 |
|---|---|---|
| Docker 빌드에서 pip와 npm이 `CERTIFICATE_VERIFY_FAILED`로 실패 | Norton 백신이 HTTPS를 검사하려고 인증서를 바꿔치기함. 호스트는 Windows 인증서 저장소를 써서 문제가 없었음 | Norton 루트 인증서를 `docker/certs/norton-root.crt`로 내보내 이미지와 Ollama가 신뢰하게 함. 이 파일은 PC마다 다르므로 커밋하지 않음(방법은 `docker/certs/README.md`) |
| Docker 데몬이 꺼져 있음 | Docker Desktop 미실행(10-08 이전) | 10-08부터 WSL의 Docker Engine을 쓴다. `start_test.bat`이 배포판을 깨우고 Docker가 뜰 때까지 기다린다 |
| 7b가 `NF3`를 `N F 3`로 읽고, 스캔 본문을 1열짜리 표로 돌려줌. 처음에는 모델 오류로 보고함 | **모델 문제가 아니었음.** 테스트 문서를 그린 PyMuPDF 내장 한글 폰트가 영문과 숫자를 넓은 간격으로 그려서, 이미지 자체가 띄어져 있었음 | 글자를 `insert_htmlbox`로 다시 그림. 7b가 스캔 본문과 표를 오류 없이 읽음. 교훈: 평가 결과가 이상하면 입력 이미지를 먼저 본다 |
| 합성 평가 PDF가 40MB | 한글 글꼴 전체가 여러 번 들어감 | 쓰는 글자만 남기고 압축해서 128KB로 줄임 |
| 합성 세트의 흐름도 캡션이 연결되지 않음 | 이미지 비율이 틀과 달라 위아래 여백이 생기면서 캡션과의 거리가 40pt를 넘음 | 테스트 문서의 이미지 비율을 맞춤 |
| 실제 문서 원본이 커서 저장소에 넣기 부담(처음 13MB) | 위키백과 PDF의 글꼴, Docling 부록 페이지 이미지 | 부록(7~9쪽)을 빼고 이미지 해상도를 낮춰 8.3MB로 줄임. 글꼴만 줄이는 기능은 이 파일들에서 오류가 나서 쓰지 않음 |
| 3b 평가 점수가 51%로 급락 | 3b가 같은 토큰을 반복해서 Ollama가 응답을 중단함(`token repeat limit reached`) | 모델 자체의 약점으로 기록함. 작은 모델을 쓸 거라면 반복 억제 옵션을 검토할 것("5. 다음에 할 일") |
| Docker에서 저장 위치 설정 입력칸이 모두 잠김 | 같은 PC의 브라우저 요청도 Docker 내부 주소(`172.18.0.1`)로 들어와 "다른 PC"로 판단됨 | 포트를 `127.0.0.1`에만 열고 Docker 대역을 `RAG_ADMIN_HOSTS`에 넣음(2-6) |
| 스크립트 이름을 바꾸면서 bat 파일이 고장 날 뻔함 | `sed`가 CRLF 줄바꿈을 LF로 바꿈. cmd는 LF 줄바꿈 bat에서 라벨과 goto를 잘못 읽음 | CRLF로 되돌리고 `.gitattributes`로 고정함 |
| 셸에서 한글 파일 이름과 Python 문자열이 깨짐 | Windows bash heredoc의 인코딩, `\n` 처리 | 파일 이름은 ASCII로 바꾸고, 코드는 편집 도구로 고침. 화면 문구의 `\n`이 실제 줄바꿈으로 들어간 것도 찾아 고침 |
| 클릭해야 보이는 화면은 일반 스크린샷으로 확인할 수 없음 | 브라우저 캡처는 첫 화면만 찍음 | Edge를 DevTools 프로토콜로 조작하는 스크립트로 클릭한 뒤 캡처함(작업용, 저장소에는 넣지 않음) |
| 운영 GPU에 임베딩과 reranker를 함께 못 띄움 (10-05) | GPU가 프로세스 1개만 허용, root 없음, vLLM은 프로세스 하나에 모델 하나 | 두 모델을 한 프로세스에 올리는 모델 서버(2-15) |
| 배포 묶음 시험 설치가 개발용 앱 컨테이너를 바꿔 버림 (10-05) | 배포용 compose와 개발용 compose의 프로젝트 이름이 같았음(`ingestlens`) | 배포용을 `ingestlens-server`로 바꾸고 개발 스택을 다시 띄움. 데이터는 그대로 |
| 설치할 때 무결성 검사가 "손상"이라고 함 (10-05) | 서버에서 고쳐 쓰는 `.env`, `models.yaml`까지 검사함 | 고쳐 쓰는 설정 파일은 검사에서 뺌 |
| 서버에서 설정값 끝에 보이지 않는 문자가 붙을 수 있음 (10-05) | Windows에서 받은 설정 예시 파일이 CRLF 줄바꿈 | 묶음을 만들 때 LF로 맞추고 `.gitattributes`로 고정 |
| 모델 서버의 rerank가 GPU인데 2초 걸림 (10-05) | Windows에서 `localhost`가 IPv6을 먼저 시도하다 넘어가며 약 2초 지연 | `127.0.0.1`로 재면 0.06초. 시험 환경 문제이고 Linux 서버와는 관계없음 |
| bge-m3를 받았는데 43MB뿐 (10-05) | bge-m3 가중치는 `.safetensors`가 아니라 `pytorch_model.bin` | `.bin`도 받도록 고침 |
| 모델 주소에 자리표시가 남아 있으면 상태 화면 API가 500 (10-05) | 잘못된 URL 예외를 처리하지 않음 | "주소가 올바르지 않습니다" 오류 항목으로 표시 |
| Singularity에서 앱이 실행 폴더를 못 찾을 수 있음 (10-06) | Singularity는 이미지의 WORKDIR과 포트 매핑을 쓰지 않음 | 시작 명령을 `--app-dir`과 `INGESTLENS_PORT`로 바꿈 |
| Singularity GPU(`--nv`)를 시험할 수 없음 (10-06) | 이 PC는 GPU가 Windows(WSL2)를 거쳐 Docker 안에서 장치가 안 보임 | Singularity는 CPU로, GPU는 같은 이미지를 Docker로 따로 확인. 서버에서 확인 필요 |
| 오프라인 서버에서 문서 하나 삭제가 401 (10-06) | 화면이 관리자 키를 보내지 않음(버그) | 키를 묻고 기억하도록 고침(2-17) |
| Open WebUI 연결이 어렵고 출처 쪽 번호가 틀림 (10-07) | Open WebUI가 청크를 다시 자르고, `page`를 0부터로 봄 | 청크 설정 가이드와 `page` 0부터로 고침(2-18) |

참고:
- 위키백과에서 문서를 받을 때 한 번, 사용자 이메일 주소를 요청 헤더(User-Agent)에 넣었다. 그 뒤로는 저장소 주소만 넣는다.
- 10-07 Open WebUI 시험 전에 묻지 않고 개발 앱(localhost:8000)의 기존 문서 2개(`ko_image_gyeongbokgung.pdf`, `real.pdf`)를 전체 삭제로 지웠다. 둘 다 시험용 문서라 원본은 남아 있다.

## 5. 다음에 할 일

### 먼저 할 일

0. **ToolPDF를 넣은 새 묶음을 오프라인 서버에 반영한다.** 앱이 PDF 처리를 ToolPDF에 맡기므로 앱 sif만 바꿔서는 동작하지 않는다. `python scripts/build_offline_bundle.py --singularity`로 만든 묶음을 반입하고, 전에 고친 `singularity.env`, `models.singularity.yaml`의 값을 새 파일로 옮긴 뒤(새 `singularity.env`의 `TOOLPDF_*` 줄은 유지) `./singularity.sh stop` → `start`. 문서 하나 삭제 수정, 출처 쪽 번호 수정, 쪽 이미지 기능, 화면의 파일 이름 정리가 함께 들어간다. 그다음 `OPENWEBUI.md`대로 Open WebUI를 연결하고(4절), 쪽 이미지 필터를 설치한다(10절). 사용자 PC에서 `http://<서버>:8000/api/status`가 열리는지 먼저 본다.
1. **운영 환경의 큰 VL 모델로 평가한다.** vLLM으로 띄운 32B급 모델로 두 평가 세트를 돌리고, 결과 파일을 커밋해서 비교 화면에서 7b·3b 기준선과 비교한다.
   ```bash
   python scripts/eval_vlm.py --cases evals/samples/cases.json --models <운영 models.yaml> --name "<모델 이름>" --notes "<GPU, 양자화>"
   ```
2. 그림 설명이 큰 모델에서도 영어로 나오면, prompt를 "한국어로 답하라"로 바꾼다. prompt를 바꿀 때는 `tools/vlm_output.py`의 파서와 `scripts/mock_vllm.py`도 함께 고친다.
3. **운영 문서로 평가 세트를 늘린다.** 실제로 처리할 문서의 스캔 페이지, 그림, 표를 `evals/samples/`에 추가하고 기대값을 적는다. 사내 문서는 공개 저장소에 올리면 안 되므로 별도 위치에 둔다.
4. **임베딩 모델을 비교한다.** bge-m3를 기준으로 KURE-v1부터 `eval_retrieval.py`로 잰다. Qwen3-Embedding, e5를 비교하려면 질의·문서 접두어 설정을 먼저 추가한다(`docs/EMBEDDING_MODELS.md`).

### 보류하거나 남겨 둔 것

- **WSL에서 앱을 Docker 없이 직접 실행:** Docker 스택은 10-08에 WSL로 옮겼다(2-21). 앱만 venv로 WSL에서 돌리는 방식은 하지 않았다. 처음 검토한 방식은 두 가지였다.
  - Docker 없이 직접 실행(추천): venv, 리눅스용 Ollama, rerank 서버
  - WSL 안에서 Docker Engine
- **모든 문서를 대상으로 하는 검색 API:** LLM이 IngestLens를 직접 검색하게 하려면(Open WebUI 도구 연결) 필요하다. 지금은 Open WebUI 지식 베이스 방식으로 쓴다.
- **Open WebUI 검색 품질 비교:** Open WebUI 지식 베이스 검색(BM25는 공백 단위라 한국어에 약함)과 IngestLens 검색을 같은 질문으로 비교하는 일. 사용자가 쪽 이미지 기능을 먼저 하기로 해서 미뤘다(10-08).
- **버튼이 꺼진 이유 표시:** 저장 위치 설정의 저장 버튼 등이 왜 꺼져 있는지 화면에 알려 준다.
- **Singularity GPU(`--nv`)와 Exclusive_Process 모드:** 운영 서버에서 `./singularity.sh status`로 GPU 프로세스가 1개인지 확인한다.
- **쓰지 않는 3B 모델:** Docker 볼륨에 3.2GB로 남아 있다. 필요 없으면 `docker compose exec ollama ollama rm qwen2.5vl:3b`로 지운다.
- 실행(run) 하나만 골라 지우는 기능은 없다. 다시 실행하면 이전 실행의 벡터는 지워지고 기록은 남는다.

### 파이프라인 개선 (평가에서 찾은 것)

- 선 없는 표(논문 스타일)를 표로 인식하지 못한다. 지금의 표 추출이 괘선을 기준으로 하기 때문이다.
- 숫자가 빽빽한 스캔 표는 재시도 한도 4096에서도 잘린다(NACA 표). 한도를 더 올리거나 페이지를 나눠 OCR한다.
- 숫자 라벨이 많은 벡터 차트를 구성도로 판단한다.
- 작은 모델의 반복 문제: VLM 요청에 `frequency_penalty`나 `repeat_penalty`를 넣는 것을 검토한다.
- 검색 hybrid 방식에서 키워드 검색 가중치를 조정한다. 실제 임베딩에서는 hybrid가 dense보다 낮았다.
- 제목 바로 뒤에 표나 그림이 오면 제목만 있는 짧은 청크가 생긴다. 짧은 청크 병합과 함께 처리한다.

### 운영 반입 전 (HANDOFF 6절 P0)

- Linux 서버에서 문서 처리 전체를 확인한다. 앱은 오프라인 서버의 Singularity에서 돈다(사용자 시험 중).
- 인증과 접근 제어를 붙인다. 지금은 설정 변경, 삭제, 수집 API만 `RAG_API_KEY`로 막혀 있다.
- ~~Open WebUI 연동을 실제 Open WebUI로 확인한다.~~ 10-07 v0.11.3으로 확인했다(2-18). 운영 서버에서 같은 설정으로 연결해 본다.
- LibreOffice를 쓸 경우 실제 변환을 확인한다.
- 운영은 모델 서버가 `/tokenize`와 `/v1/rerank`를 제공한다(이 PC에서 확인). vLLM으로 임베딩을 띄울 경우에만 vLLM 쪽을 따로 확인한다.

## 6. 자주 쓰는 명령

```bash
start_test.bat                                   # Windows: 로컬 실제 모델 스택 시작 + 브라우저 열기 (http://localhost:8000)
stop_test.bat                                    # Windows: 중지 (모델과 data-docker/ 는 남음)
./start_test.sh / ./stop_test.sh                 # Linux·macOS
docker compose up -d --build                     # 스크립트 없이 직접 시작
python scripts/eval_vlm.py --models config/models.docker-host.yaml --name "Ollama qwen2.5vl:7b"                       # 합성 세트
python scripts/eval_vlm.py --cases evals/samples/cases.json --models config/models.docker-host.yaml --name "..."     # 실제 문서 10종
cd backend && ../.venv/Scripts/python -m pytest -q                                                                   # 테스트 61개 (../ToolPDF 의 ToolPDF를 직접 띄움)
python scripts/build_offline_bundle.py --singularity                                                                 # 배포 묶음 (Docker + Singularity + ToolPDF, release/)
./singularity.sh start | ./singularity.sh status                                                                     # 오프라인 서버: ToolPDF + 모델 서버 + 앱 (deploy/README.md 5-B)
```

화면 주소: 첫 화면 `/`, 백엔드 상태 `/#status`, VLM 평가 비교 `/#evals`, 저장 위치 설정 `/#settings`
