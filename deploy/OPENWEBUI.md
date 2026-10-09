# Open WebUI 연결 가이드

Open WebUI(0.11.x)에서 파일을 추가하면 IngestLens가 자동으로 문서를 분석·파싱·청킹하고, 그 청크가 Open WebUI 지식 베이스에 들어가게 만드는 방법이다. 그러면 다른 LLM이 답할 때 이 지식 베이스를 검색해서 답한다.

2026-10-07에 Open WebUI **v0.11.3**으로 아래 순서를 실제로 해 보고 확인했다(7절). 답변에 쓴 문서 쪽의 이미지를 채팅에 보여주는 필터 함수는 10절에 있다.

## 1. 동작 방식

```
 사용자가 Open WebUI에 파일 추가 (지식 베이스 또는 채팅 첨부)
        │  PUT {URL}/process  (파일 바이트, X-Filename, Bearer 키)
        ▼
 IngestLens 앱  ──  형식 판별 → 페이지 분석 → 파싱(VLM) → 청킹
        │  청크 목록 [{page_content, metadata}] 돌려줌
        ▼
 Open WebUI  ──  청크를 임베딩해서 자기 벡터 DB에 저장 (모델 서버의 bge-m3)
        │
 LLM이 답할 때  ──  지식 베이스 검색(벡터 + BM25) → rerank(모델 서버) → 답변과 출처 표시
```

- **파싱과 청킹은 IngestLens가 한다.** 스캔 OCR, 표, 그림 설명이 그대로 청크에 들어간다. 처리 과정과 근거는 IngestLens 화면에서 볼 수 있다.
- **임베딩, 저장, 검색은 Open WebUI가 한다.** 임베딩과 rerank는 IngestLens와 같은 모델 서버를 쓰게 하면 결과가 일치한다.
- 파일 추가 한 번으로 IngestLens 쪽에도 같은 문서가 색인된다. IngestLens 화면에서 검색 결과를 비교해 볼 수 있다.

## 2. 준비

| 무엇 | 상태 |
|---|---|
| IngestLens 앱 | 실행 중(`./singularity.sh start-app` 또는 `./install.sh`). **`RAG_API_KEY`를 정해 둔다** |
| 모델 서버 | 실행 중(`./singularity.sh start-model` 또는 `./model-server.sh start`) |
| VLM | IngestLens의 `models.yaml`(Singularity는 `models.singularity.yaml`)에 주소를 적어 둔다 |
| Open WebUI | 0.11.x. GPU가 필요 없는 일반 이미지(`:main`). `:cuda` 이미지는 쓰지 않는다 |

**IngestLens 앱 버전:** 2026-10-07 이후 버전을 쓴다. 그 전 버전은 출처의 쪽 번호가 1씩 크게 보이는 문제가 있다(8절).

## 3. 주소 정하기

Open WebUI가 IngestLens 앱(8000)과 모델 서버(8090)에 접속할 주소는 Open WebUI가 어디서 도는지에 따라 다르다.

| Open WebUI 위치 | IngestLens·모델 서버 주소 | 비고 |
|---|---|---|
| 같은 서버의 Docker 컨테이너 | `host.docker.internal` | `docker run`에 `--add-host host.docker.internal:host-gateway`를 붙인다 |
| 같은 서버의 Singularity | `127.0.0.1` | Singularity는 호스트 네트워크를 그대로 쓴다 |
| 다른 서버 | 그 서버의 IP | 방화벽에서 8000, 8090 포트를 연다 |

아래 예시는 `<IL>`(IngestLens 앱 주소)과 `<MS>`(모델 서버 주소)로 적는다.

## 4. Open WebUI 설정

### 4-1. 환경 변수로 설정할 때 (새로 설치할 때 권장)

```bash
# ① 파일 추가 → IngestLens 로 보내기 (끝에 /process 를 붙이지 않는다. Open WebUI가 붙인다)
CONTENT_EXTRACTION_ENGINE=external
EXTERNAL_DOCUMENT_LOADER_URL=http://<IL>:8000/api/openwebui
EXTERNAL_DOCUMENT_LOADER_API_KEY=<IngestLens 의 RAG_API_KEY 값>

# ② IngestLens 청크를 다시 자르거나 합치지 않기 (중요, 4-3, 4-4)
CHUNK_SIZE=8000
CHUNK_OVERLAP=0
CHUNK_MIN_SIZE_TARGET=0
ENABLE_MARKDOWN_HEADER_TEXT_SPLITTER=false

# ③ 임베딩: 모델 서버의 bge-m3
RAG_EMBEDDING_ENGINE=openai
RAG_OPENAI_API_BASE_URL=http://<MS>:8090/v1
RAG_OPENAI_API_KEY=EMPTY                   # 모델 서버에 API_KEY 를 정했다면 같은 값
RAG_EMBEDDING_MODEL=bge-m3

# ④ 검색: 벡터 + BM25(hybrid) 후 모델 서버로 rerank
ENABLE_RAG_HYBRID_SEARCH=true
RAG_RERANKING_ENGINE=external
RAG_EXTERNAL_RERANKER_URL=http://<MS>:8090/v1/rerank   # 경로까지 전부 적는다
RAG_EXTERNAL_RERANKER_API_KEY=EMPTY
RAG_RERANKING_MODEL=bge-reranker-v2-m3
RAG_TOP_K=5
RAG_TOP_K_RERANKER=5

# ⑤ 오프라인
OFFLINE_MODE=true
```

`docker run` 예:

```bash
docker run -d --name open-webui -p 3000:8080 \
  --add-host host.docker.internal:host-gateway \
  -v open-webui:/app/backend/data \
  --env-file openwebui.env \
  ghcr.io/open-webui/open-webui:v0.11.3
```

**주의: 이 환경 변수들은 Open WebUI를 처음 시작할 때만 반영된다.**
- Open WebUI는 처음 시작할 때 설정을 자기 DB에 저장하고, 그 뒤로는 DB 값을 쓴다.
- 이미 쓰던 Open WebUI라면 4-2의 관리자 화면에서 바꾼다.
- 또는 `ENABLE_PERSISTENT_CONFIG=false`를 넣어 매번 환경 변수를 읽게 한다.

### 4-2. 관리자 화면에서 설정할 때 (이미 쓰던 Open WebUI)

관리자 패널 → 설정 → 문서에서 다음을 바꾸고 저장한다.

| 화면 항목 | 값 |
|---|---|
| 콘텐츠 추출 엔진 | External |
| (External) URL | `http://<IL>:8000/api/openwebui` |
| (External) API 키 | IngestLens의 `RAG_API_KEY` |
| 텍스트 분할기 / Markdown 헤더 분할 | 끔 |
| 청크 크기 / 청크 겹침 | 8000 / 0 |
| 청크 최소 크기 목표 | 0 (합치기는 IngestLens가 한다, 4-4) |
| 임베딩 모델 엔진 | OpenAI |
| API Base URL / 키 | `http://<MS>:8090/v1` / `EMPTY` |
| 임베딩 모델 | `bge-m3` |
| 하이브리드 검색 | 켬 |
| Reranking 엔진 | External |
| Reranking URL / 모델 | `http://<MS>:8090/v1/rerank` / `bge-reranker-v2-m3` |
| Top K / Top K Reranker | 5 / 5 |

화면 문구는 Open WebUI 버전과 언어 설정에 따라 조금 다를 수 있다. 위 4-1의 환경 변수 이름이 기준이다.

### 4-3. 청크 크기 설정이 중요한 이유

- Open WebUI는 문서 로더가 돌려준 청크를 **자기 설정으로 한 번 더 자른다.** 기본값은 1000자, 겹침 100자, Markdown 헤더 분할 켬이다.
- IngestLens 청크는 표, 그림 설명, 절 단위로 만든 것이라 다시 잘리면 표가 반으로 나뉜다.
- 2026-10-07 시험 결과(국가데이터처 보도자료 5쪽):

  | 설정 | IngestLens 청크 | Open WebUI에 저장된 조각 |
  |---|---|---|
  | 기본값 | 49개 | **58개** (큰 표 9개가 잘림) |
  | 4-1 설정 | 26개 (Docling 논문) | **26개** (그대로) |

- `CHUNK_SIZE=8000`은 IngestLens 청크보다 넉넉히 큰 값이다. IngestLens 청크는 약 500토큰(1,000~1,500자)이고, 긴 표도 IngestLens가 행 단위로 나눠 보낸다.
- 이 설정은 Open WebUI의 모든 문서에 적용된다. 콘텐츠 추출 엔진이 External이면 모든 파일이 IngestLens를 거치므로 문제없다.

### 4-4. 청크 설정 권장 조합 (IngestLens + Open WebUI)

청크를 정하는 설정은 양쪽에 다 있다. **청크는 IngestLens가 만들고, Open WebUI는 받은 그대로 쓰게 한다.** IngestLens는 표, 그림, 절, 쪽 위치를 알고 청크를 만들지만, Open WebUI는 글자 수로만 자르고 합치기 때문이다.

| 할 일 | 맡는 쪽 | 설정 | 권장값 | 이유 |
|---|---|---|---|---|
| 청크 크기 | IngestLens | `config/strategy_rules.yaml` `strategy.target_tokens` | 512 | 임베딩 모델 토큰 단위. bge-m3(8192)에 넉넉하고 검색 결과 하나가 한눈에 읽힌다 |
| 앞 청크와 겹침 | IngestLens | `strategy.overlap_tokens` | 64 | 긴 본문이 크기 때문에 잘린 곳에서만 앞 청크 끝을 다음 청크 앞에 반복한다. 절·표·그림 경계에서는 겹치지 않는다 |
| 짧은 청크 합치기 | IngestLens | `strategy.min_tokens` | 128 | 같은 절 안에서 이보다 짧은 청크(제목만, 한 줄짜리 레지스터 표, 한 줄 설명)를 다음(안 되면 앞) 청크와 합친다. 최대 `target + min`. 합친 청크는 모든 쪽과 칠할 영역을 유지한다 |
| 다시 자르기 | Open WebUI | `CHUNK_SIZE` / `CHUNK_OVERLAP` | 8000 / 0 | 글자 수 단위. IngestLens 청크(최대 약 640토큰, 1,600자 안팎. 큰 표 조각도 7,000자 미만)보다 크게 둬서 다시 자르지 않게 한다. 겹침은 IngestLens가 이미 넣었다 |
| 합치기 | Open WebUI | `CHUNK_MIN_SIZE_TARGET` | 0 | Open WebUI도 짧은 청크를 합칠 수 있지만, 합칠 때 **앞 청크의 메타데이터만 남겨** 뒤 청크의 `chunk_id`·쪽이 사라진다(쪽 이미지가 일부만 가리킴). 또 Markdown 헤더 분할이 켜져 있을 때만 동작한다 |
| Markdown 헤더 분할 | Open WebUI | `ENABLE_MARKDOWN_HEADER_TEXT_SPLITTER` | false | 켜면 IngestLens 청크 안의 `#` 제목·표 머리에서 다시 쪼갠다 |
| 검색 개수 | Open WebUI | `RAG_TOP_K` / `RAG_TOP_K_RERANKER` | 5 / 5, 데이터시트·매뉴얼처럼 비슷한 표와 문단이 많은 문서는 8~10 | 아래 시험. 늘리면 정답 청크가 들어올 기회가 늘지만 rerank와 답변이 느려진다 |
| 키워드 비중 | Open WebUI | `RAG_HYBRID_BM25_WEIGHT` | 0.5 (기본) | 0.8로 올렸을 때 더 나빴다(아래 시험) |

**짧은 청크 합치기가 필요한 이유 (2026-10-09, 공개 센서 데이터시트 4종):** 데이터시트의 레지스터 설명은 "8.6 WHO_AM_I (0Fh)" 제목, 비트 값 표 한 줄, 설명 한 줄이 이어진다. 합치기 전에는 이 셋이 8·36·14토큰짜리 청크 셋으로 나뉘어 주소와 값이 한 청크에 없었다. 합친 뒤에는 한 청크다. 64토큰 미만 청크가 문서마다 120~150개였다. `min_tokens: 128`이면 2~23개로 줄고(나머지는 절 하나가 통째로 짧은 경우), 청크 수는 30~40% 준다. 64 이상이면 레지스터 제목과 값이 한 청크가 되고 128보다 키워도 차이가 작다.

**시험 결과 (2026-10-09, 로컬 Docker 스택: Ollama bge-m3, CPU reranker, 채팅 `gemma4:e4b`):**

| 시험 | min_tokens 0 (합치기 전) | min_tokens 128 |
|---|---|---|
| 합성 세트 검색 22문항, IngestLens hybrid+rerank hit@1 | 95% (바꿔 쓴 질문 88%) | **100%** (100%) |
| 같은 세트, hybrid / dense만 hit@1 | 86% / 95% | 91% / 86% |
| 합성 세트 청크 수 | 38 | 25 |
| 센서 데이터시트 4종 청크 수 | 1,314 | 869 |
| 데이터시트 질문 9개, Open WebUI `RAG_TOP_K=5` | 7개 정답 | 6개 |
| 같은 질문, `RAG_TOP_K=10` | — | 7개 (답 18~73초, CPU rerank) |
| 같은 질문 중 어려운 3개, `TOP_K=10` + `BM25_WEIGHT=0.8` | — | 0개 |

- Open WebUI가 쓰는 hybrid+rerank는 합치기로 좋아졌다. dense만 쓰는 검색은 청크가 커져 조금 떨어졌다.
- 데이터시트에서 남은 오답 두 개는 합치기로 풀리지 않는 검색 문제다. LIS3DH WHO_AM_I는 이제 제목·값·설명이 한 청크(54토큰)지만, 한국어 질문과의 임베딩 순위가 20위(BM25로는 1위)라 Open WebUI가 가져오지 못했다. MPU-6000 I2C 주소는 정답 문장이 그 절의 두 번째 청크에 있어 1위 청크(절 첫 부분)만 들어왔다. 질문을 영어나 문서의 낱말(예: "WHO_AM_I register value")로 하면 더 잘 찾는다.
- 질문 9개는 표본이 작고 답이 매번 조금씩 달라 한두 개 차이는 우연일 수 있다. 실제 문서로 평가 세트를 만들어 다시 재는 것이 좋다(`evals/README.md`).

**값을 바꿀 때:**
- `min_tokens`를 바꾸면 이미 처리한 문서는 IngestLens에서 다시 실행하고, Open WebUI 지식 베이스에도 다시 넣어야 새 청크가 쓰인다.
- 슬라이드·시트처럼 쪽 단위로 자르는 문서(`page` 전략)는 쪽을 넘어 합치지 않는다. 절이 다르면 합치지 않는다.
- 끄려면 `min_tokens: 0`. 처리마다 "근거" 탭에 `chunk_merge`(합치기 전후 청크 수)가 남는다.

## 5. 사용하기

### 5-1. 지식 베이스에 문서 넣기

1. 워크스페이스 → 지식 → 새 지식 베이스를 만든다.
2. 파일을 추가한다(여러 개 가능).
   - Open WebUI가 파일을 IngestLens로 보낸다.
   - IngestLens 화면의 문서 목록에 같은 문서가 나타나고 실행이 진행된다.
   - Open WebUI는 파일 이름 앞에 긴 ID를 붙여 보낸다(예: `3420400f-…_보고서.pdf`). IngestLens 화면은 이 ID를 떼고 `보고서.pdf`로 보여준다. 전체 이름은 마우스를 올리면 보인다(2026-10-08 이후 앱).
3. 처리가 끝나면 Open WebUI의 파일 상태가 완료로 바뀐다.
   - 처리 시간은 IngestLens에서 문서 하나를 실행하는 시간과 같다. 스캔이나 그림이 많으면 VLM 때문에 수십 초에서 수 분이 걸린다.
   - IngestLens는 문서를 **한 번에 하나씩** 처리한다. 여러 파일을 한꺼번에 올리면 차례를 기다린다.

### 5-2. LLM이 답할 때 검색하게 하기

둘 중 하나를 쓴다.

- **모델에 지식 베이스를 붙이기 (항상 검색):** 워크스페이스 → 모델 → 쓸 모델을 편집 → 지식에서 지식 베이스를 선택한다. 그 모델로 대화하면 매번 지식 베이스를 검색해서 답한다.
- **대화에서 골라 쓰기:** 채팅 입력창에서 `#`을 입력하고 지식 베이스를 고른 뒤 질문한다.

답변 아래 출처에는 다음이 표시된다.
- 파일 이름과 쪽 번호
- IngestLens 메타데이터: 절(`section`), 청크가 걸친 쪽(`pages`), 요소 종류(`element_types`)

### 5-3. 채팅에 파일을 바로 첨부할 때

- 채팅 첨부 파일도 같은 경로(IngestLens)를 거친다.
- 다만 Open WebUI가 그 대화에서만 쓰고 지식 베이스에는 넣지 않는다. 여러 번 쓸 문서는 지식 베이스에 넣는다.

## 6. 연결 확인 순서

1. **Open WebUI 서버에서 IngestLens로 직접 보내 보기**
   ```bash
   curl -X PUT -H "Authorization: Bearer <RAG_API_KEY>" -H "X-Filename: test.pdf" \
        -H "Content-Type: application/pdf" --data-binary @test.pdf \
        http://<IL>:8000/api/openwebui/process
   ```
   - JSON 배열(`[{"page_content": …, "metadata": {…}}]`)이 오면 정상이다.
   - 401이면 키가 틀린 것이고, 연결 오류면 주소나 방화벽 문제다.
   - Open WebUI가 Docker 안에 있으면 `docker exec open-webui curl …`로 컨테이너 안에서 시험한다.
2. **모델 서버 확인:** `curl http://<MS>:8090/v1/models`에 `bge-m3`, `bge-reranker-v2-m3`가 보이는지 본다.
3. **IngestLens 상태 화면:** `http://<IL>:8000/#status`에서 임베딩, reranker, VLM이 "정상"인지 본다.
4. **Open WebUI에서 작은 PDF 하나를 지식 베이스에 넣고 질문한다.** 답 아래 출처의 쪽 번호가 실제 쪽과 맞는지 본다.

## 7. 시험 결과 (2026-10-07, Open WebUI v0.11.3)

| 단계 | 결과 |
|---|---|
| 4-1 환경 변수로 Open WebUI 시작 | 설정 반영 확인(External, 청크 8000/0, Markdown 분할 끔, hybrid, External rerank) |
| 지식 베이스에 Docling 논문 PDF 추가 | IngestLens가 처리(약 10초), 청크 26개 → Open WebUI 벡터 26개 |
| Open WebUI 검색 API로 질의 | IngestLens 청크가 그대로 나오고, rerank 점수, 절, 쪽이 맞음 |
| LLM 질문(qwen2.5vl:7b, 지식 베이스 첨부) | "TableFormer, 2022년"으로 정답. 출처 3쪽(실제 3쪽) |

시험 환경은 이 저장소의 개발용 Docker 스택이다. 임베딩은 Ollama bge-m3를 썼고, reranker는 같은 모델 서버를 CPU로 돌렸다. 운영의 모델 서버(GPU)와 API 형식은 같다.

## 8. 문제 해결

| 증상 | 원인 | 조치 |
|---|---|---|
| 파일 추가가 실패하고 401 | `EXTERNAL_DOCUMENT_LOADER_API_KEY`와 IngestLens의 `RAG_API_KEY`가 다름 | 같은 값으로 맞춘다 |
| 연결 오류(Connection refused, 이름을 찾을 수 없음) | 3절의 주소가 맞지 않음 | Docker의 Open WebUI는 `--add-host host.docker.internal:host-gateway`가 있는지 본다. 6절 1번을 컨테이너 안에서 시험한다 |
| 처리가 아주 오래 걸리다 실패(504) | IngestLens가 `RAG_INGEST_WAIT_SECONDS`(기본 3600초) 안에 끝내지 못함 | 큰 문서는 그 값을 늘린다. 앞에 nginx 같은 프록시가 있으면 `proxy_read_timeout`도 늘린다 |
| 처리 실패(502) | IngestLens 실행 자체가 실패함 | IngestLens 화면에서 그 문서의 실행 오류를 본다 |
| 출처의 쪽 번호가 1씩 큼 | 2026-10-07 이전 IngestLens 앱. Open WebUI는 `page`를 0부터로 보고 +1 해서 보여준다 | 새 앱 이미지로 바꾼다. 새 앱은 `page`를 0부터, `page_label`·`pages`는 1부터 보낸다 |
| 표가 반으로 잘린 채 검색됨 | Open WebUI가 청크를 다시 자름 | 4-3의 청크 설정 |
| 환경 변수를 바꿨는데 반영이 안 됨 | Open WebUI가 처음 시작할 때 저장한 DB 설정을 씀 | 관리자 화면에서 바꾸거나 `ENABLE_PERSISTENT_CONFIG=false` |
| 같은 파일을 다른 지식 베이스에 넣으면 "중복" 오류 | Open WebUI가 내용 해시로 중복을 막음 | Open WebUI 동작이다. 기존 파일을 그 지식 베이스에 추가한다 |
| rerank가 안 되는 것 같음 | 하이브리드 검색이 꺼져 있음 | `ENABLE_RAG_HYBRID_SEARCH=true`. 모델 서버 로그(`model.log`, `model-server.log`)에 `/v1/rerank` 요청이 찍히는지 본다 |
| 임베딩 모델을 바꾼 뒤 검색이 이상함 | 이전 모델로 만든 벡터와 섞임 | Open WebUI 지식 베이스를 다시 색인한다 |
| IngestLens 문서 이름 앞에 긴 ID가 붙음 | Open WebUI가 `<ID>_<이름>`으로 보냄. 2026-10-08 전 앱은 그대로 보여준다 | 새 앱은 화면에서 ID를 뗀다. 저장된 이름은 그대로라 Open WebUI 파일과 대조할 수 있다 |

## 9. 지금 안 되는 것

**LLM이 IngestLens 검색 API를 직접 호출하는 방식**(Open WebUI 도구나 도구 서버로 연결)은 아직 지원하지 않는다.
- 지금 IngestLens 검색 API(`POST /api/search`)는 문서 하나(또는 실행 하나) 안에서만 검색한다.
- 모든 문서를 대상으로 검색하는 API와 Open WebUI 도구 연결이 필요하면 추가 개발한다.
- 이 가이드의 방식은 Open WebUI가 IngestLens의 청크를 받아 자기 지식 베이스에서 검색하는 것이다. 검색 결과는 같은 모델 서버(bge-m3, reranker)를 쓰므로 품질 차이는 크지 않다.

## 10. 답변에 쪽 이미지 보여주기 (필터 함수)

`deploy/openwebui_page_images.py`는 Open WebUI **필터 함수**다. 지식 베이스로 답한 뒤, 답변에 쓴 출처의 쪽 이미지를 두 곳에 보여준다.
- **답변 위 썸네일 줄**: "참고한 쪽" 아래에 쪽 썸네일이 가로로 놓인다. 청크 영역이 주황색으로 칠해져 있다. 썸네일을 누르면 그 자리에서 크게 펼쳐지고, 다시 누르면 접힌다. 가로 문서(슬라이드)와 세로 문서 모두 긴 변을 기준으로 맞춘다.
- **출처 팝업**: 답변의 출처(문서 이름)를 누르면 뜨는 카드에 같은 쪽의 큰 이미지가 텍스트 발췌와 함께 나온다.

두 가지 모두 대화에 저장되므로 새로 고쳐도 남는다. IngestLens 문서 로더(4절)로 넣은 문서에만 동작한다. 청크 메타데이터의 `document_id`, `chunk_id`, `page`를 쓰기 때문이다.

### 10-1. 준비

- **필터 파일**: 배포 묶음을 푼 폴더에 `openwebui_page_images.py`가 있다(저장소에서는 `deploy/openwebui_page_images.py`). 이 파일 하나만 있으면 되고, Open WebUI에 설치할 패키지는 없다.
- **IngestLens 앱 버전**: 2026-10-08 이후 앱이어야 한다. 썸네일 이미지를 주는 `/api/chunks/{id}/preview.png`가 이때 생겼다. 예전 앱이면 썸네일이 깨진 그림으로 나온다. 새 묶음으로 바꾼다(앱과 ToolPDF가 함께 들어 있다).
- **사용자 PC에서 IngestLens 주소가 열리는지**: 사용자 PC의 브라우저에서 `http://<IngestLens 서버>:8000/api/status`를 열어 본다. 열리지 않으면 방화벽에서 8000 포트를 연다(10-6).

### 10-2. 설치

1. 관리자 패널 → **함수** → **+** (새 함수)를 누르고 `openwebui_page_images.py` 내용을 그대로 붙여 넣은 뒤 저장한다.
2. 함수 목록에서 이 함수를 **켠다**. 모든 모델에 쓰려면 ⋯ 메뉴에서 **전역**으로 바꾼다. 일부 모델에만 쓰려면 모델 편집 화면의 필터에서 고른다.
3. 함수의 **밸브**(톱니바퀴)에서 `INGESTLENS_URL`을 정하고 저장한다. 나머지 밸브는 기본값으로 둬도 된다.
4. 10-5의 순서로 동작을 확인한다.

### 10-3. 설정(밸브) 바꾸기

관리자 패널 → **함수** → "IngestLens 쪽 이미지" 오른쪽 **톱니바퀴** → 값을 바꾸고 **저장**.
- 저장하면 바로 적용된다. Open WebUI를 다시 시작하지 않아도 된다.
- 새로 받는 답변부터 적용된다. 이미 저장된 답변의 이미지는 바뀌지 않는다.
- 밸브 값은 Open WebUI DB에 저장된다. 필터 파일을 고칠 필요는 없다.

| 밸브 | 기본값 | 뜻 |
|---|---|---|
| `INGESTLENS_URL` | `http://localhost:8000` | **사용자 PC의 브라우저**에서 열리는 IngestLens 주소. 3절의 주소(Open WebUI 서버에서 보는 주소)와 다를 수 있다 |
| `MAX_PAGES` | 3 | 답변 하나에 보여줄 최대 쪽 수 |
| `SELECT` | `answer` | 어떤 쪽을 보여줄지. `answer`: 답변 내용과 맞는 청크의 쪽만(0.4.0부터). `rank`: 예전 방식, 검색 순서대로 앞의 쪽 |
| `MIN_MATCH` | 0.3 | `answer`에서 보여줄 최소 일치도(0~1). 가장 잘 맞는 청크의 65%에 못 미치는 청크도 뺀다 |
| `THUMB_SIZE` | 220 | 썸네일의 긴 변(px) |
| `BIG_HEIGHT` | 900 | 눌러서 크게 볼 때의 최대 높이(px). 폭은 답변 폭까지 |
| `DPI` | 110 | 이미지 해상도. 썸네일, 크게 보기, 출처 팝업이 같은 이미지를 쓴다 |
| `HIGHLIGHT` | 켬 | 청크 영역을 칠한 이미지. 끄면 쪽 전체 이미지 |
| `SHOW_IN_CHAT` / `SHOW_IN_SOURCES` | 켬 | 썸네일 줄 / 출처 팝업에 넣을지 |

- **어떤 쪽이 썸네일이 되나:** Open WebUI는 질문과 비슷한 청크를 몇 개(`RAG_TOP_K`, 보통 5) 가져와 모델에 주고, 그 전부를 답변의 출처로 저장한다. 그 가운데에는 답에 쓰이지 않은 청크(다른 주제, 낮은 점수)도 섞인다. 0.3.0까지는 이 출처를 순서대로 앞에서 3쪽 보여줘서, 답과 상관없는 쪽이 썸네일이 되곤 했다(예: "혼인 건수" 답에 이혼 통계 쪽, 표 인식 모델 답에 논문 초록 쪽). 0.4.0부터는 답변과 각 청크에 함께 나오는 숫자, 영어 단어, 한글 두 글자 조각을 비교해 **답이 실제로 쓴 청크의 쪽만** 점수 순으로 보여준다. 출처 청크에 공통으로 다 나오는 말(연도, 주제어)은 가볍게 센다. 맞는 청크가 없으면 검색 1위 쪽 하나만 보여준다.
- 같은 쪽은 한 번만 보여준다. 문서 전체 쪽수와는 관계없다. `MAX_PAGES`를 늘려 썸네일이 많아지면 다음 줄로 넘어가고, 칸 안에 스크롤은 생기지 않는다.
- 썸네일의 칠한 영역은 그 청크의 위치다. 쪽 이미지는 IngestLens가 만든 PDF에서 그리므로, IngestLens에서 문서를 지우거나 다시 실행해 청크가 바뀌면 예전 답변의 썸네일은 깨진 그림이 된다.

### 10-4. 필터를 새 버전으로 바꾸기

관리자 패널 → **함수** → "IngestLens 쪽 이미지"를 눌러 편집 화면을 연다 → 내용을 새 `openwebui_page_images.py`로 모두 바꾸고 저장한다. 함수 ID가 같으면 켜짐·전역 상태와 밸브 값은 남는다. 단, 새 버전에서 이름이 바뀐 밸브는 기본값으로 돌아가므로 다시 확인한다.

### 10-5. 동작 확인 순서

1. 사용자 PC 브라우저에서 `<INGESTLENS_URL>/api/status`가 열리는지 본다.
2. IngestLens 문서 로더로 넣은 문서가 있는 지식 베이스를 골라(입력창에서 `#`) 문서 내용을 묻는다.
3. 답변 위에 "참고한 쪽 · 누르면 크게 보기"와 썸네일이 나오는지 본다. 썸네일을 눌러 펼쳐지고, 다시 눌러 접히는지 본다.
4. 답변의 출처(문서 이름)를 눌러, 팝업 카드에 쪽 이미지가 나오는지 본다.

| 증상 | 원인 | 조치 |
|---|---|---|
| 썸네일 줄도, 출처 팝업 이미지도 없음 | 필터가 꺼져 있거나 전역이 아니고 모델에도 연결되지 않음 | 10-2의 2번. 문서가 IngestLens 문서 로더(4절)로 들어갔는지도 본다 |
| 썸네일 자리에 깨진 그림 | 사용자 PC에서 `INGESTLENS_URL`이 안 열림, 예전 앱, 또는 문서가 IngestLens에서 지워짐 | 10-5의 1번, 10-1의 앱 버전 |
| `https` Open WebUI에서만 깨짐 | 혼합 콘텐츠 차단 | 10-6 |
| 예전 답변에 이미지가 없음 | 필터를 켜기 전의 답변 | 새로 질문하거나 다시 생성한다 |
| 썸네일이 답과 상관없는 쪽 | 필터 0.3.0 이하(검색 순서대로 보여줌) | 0.4.0으로 바꾼다(10-4). `SELECT` 밸브가 `answer`인지 본다 |

### 10-6. 주의

- **이미지는 사용자 브라우저가 IngestLens에서 직접 받는다.** 사용자 PC에서 `INGESTLENS_URL`의 8000 포트가 열려 있어야 한다. 브라우저에서 `<INGESTLENS_URL>/api/status`가 열리는지 먼저 본다.
- Open WebUI를 `https`로 쓰고 IngestLens가 `http`이면 브라우저가 이미지를 막는다(혼합 콘텐츠). 둘 다 같은 프록시 아래 `https`로 두거나 둘 다 `http`로 쓴다.
- 쪽 이미지 주소(`/api/chunks/{id}/preview.png`, `/api/documents/{id}/pages/{n}.png`)는 `RAG_API_KEY` 없이 열린다. IngestLens 화면의 쪽 이미지와 같다. 주소를 아는 사람은 그 쪽을 볼 수 있으므로, IngestLens 포트는 내부망에만 연다.
- 필터를 켜기 전에 만든 답변에는 이미지가 붙지 않는다. 새로 질문하거나 답변을 다시 생성한다.
- IngestLens에서 문서를 지우면 이미지가 404가 되어 깨진 그림으로 보인다.
- 썸네일 줄은 Open WebUI의 임베드(iframe)로 넣는다. Markdown 이미지로 넣으면 Open WebUI가 원래 크기로 그리고, 눌렀을 때의 미리보기도 원래 크기까지만 키운다. 그래서 "작은 썸네일 + 선명한 큰 이미지"를 만들 수 없고, 링크를 함께 걸면 창이 두 개 열린다.
- 임베드는 Open WebUI가 답변 글 위에 놓는다. 위치는 Open WebUI가 정한다.
- Open WebUI 0.11.3에서 확인했다. 가로 문서(16:9 pptx)와 세로 문서(A4 PDF) 모두 시험했다.
