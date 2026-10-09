# 문서 자동 분석·청킹·임베딩 Multi-Agent RAG 파이프라인

> 처음 세운 계획이다. 구현된 구조와 다른 점은 각 마일스톤의 "구현 메모"와 `docs/HANDOFF.md`에 있다. 가장 큰 차이는 PDF 처리다: 모든 PDF 작업(변환, 쪽 특징, 추출, 렌더)은 PDF 엔진이 한다. 별도 프로그램인 [ToolPDF](https://github.com/kisubkim/ToolPDF)를 HTTP로 호출하거나, 앱 안의 내장 엔진(퍼미시브 라이선스 라이브러리만)을 쓴다(`docs/ENGINE_PLAN.md`).

## Context
사용자가 웹에서 문서를 선택하면 agent가 다음을 자동으로 처리해야 한다.
- 문서 형식(PDF/Word/PPT 등)과 내용 성격(텍스트 위주, 이미지 위주, 다이어그램·차트 위주)을 판별한다.
- 판별 결과로 파싱 도구와 모델, 청킹 전략을 고르고 임베딩까지 진행한다.

웹에서 해야 하는 것:
- 진행 과정과 각 결정의 근거를 본다.
- rag-lab처럼 파싱 리포트, 청킹 결과, 임베딩 내용, 검색 결과를 단계별로 확인한다.

제약:
- 외부 API 없이 동작한다. 인터넷이 없는 환경에서도 쓸 수 있어야 한다.
- 모델은 vLLM으로 서빙한다. 현재는 VL 모델 일부만 있고, 필요하면 추가 모델을 준비한다.
- 문서 크기는 5MB~150MB다. 수백 페이지와 대용량 이미지를 전제로 한다.

## 기본 기술 선택 (별도 지정 없어 추천안 채택, 변경 가능)
| 영역 | 선택 | 이유 |
|---|---|---|
| Backend | Python 3.11 + FastAPI | SSE 실시간 이벤트, 문서 처리 라이브러리 생태계 |
| Orchestration | LangGraph | 상태 그래프, 노드별 이벤트 스트리밍, 체크포인트/재실행 |
| 작업 큐 | Redis + arq (또는 Celery) | 150MB 문서는 백그라운드 처리 필수, 페이지 배치 병렬화 |
| 메타/로그 DB | PostgreSQL (PoC는 SQLite) | 문서, run, 결정 근거, 청크 메타 저장 |
| 파일 저장 | 로컬 볼륨 또는 MinIO | 원본, 페이지 이미지, 추출 결과 |
| Vector DB | Qdrant | 오프라인 설치 쉬움, dense+sparse hybrid, payload 필터 |
| Frontend | React + Vite + TypeScript | 실시간 DAG, 근거 타임라인, 페이지 오버레이 뷰어 |
| 모델 호출 | vLLM OpenAI 호환 API (`/v1/chat/completions`, `/v1/embeddings`) | 모델 교체는 설정만으로 |

**추가 준비 필요 모델**:
- 임베딩 모델(필수): 현재 VL 모델뿐이므로 추가해야 한다. 추천은 `bge-m3`(dense+sparse, 한국어 양호) 또는 `Qwen3-Embedding`. vLLM에서 `--task embed`로 띄운다.
- reranker(선택): `bge-reranker-v2-m3`.
- 텍스트 LLM(선택): 전략 결정 보조와 검색 답변 생성용. VL 모델로 대체할 수 있다.

## Agent 구성
LangGraph Supervisor 그래프로 구성한다. 모든 노드는 공통 `emit_event()`와 `record_decision()`을 호출해 진행 상황과 근거를 남긴다.

1. **Intake Agent**: 형식 판별과 정규화
   - magic bytes(`filetype`)와 확장자를 교차 검증한다. 대상: pdf/docx/pptx/xlsx/이미지(hwp는 선택).
   - Office 문서는 LibreOffice headless로 PDF로 변환해 페이지 렌더링 기준을 통일한다. 네이티브 구조(python-docx 헤딩, python-pptx 슬라이드/노트)도 병행 추출해 구조 힌트로 쓴다.
   - 대용량 대응: 스트리밍 업로드(청크 업로드), 해시로 중복을 감지한다.

2. **Profiler Agent**: 페이지별 콘텐츠 성격 분석
   - PDF 엔진(ToolPDF `/v1/profile`)으로 페이지마다 다음 feature를 계산한다.
     - text layer 문자 수와 텍스트 영역 비율
     - 이미지 개수와 면적 비율
     - 벡터 드로잉 수: 다이어그램과 차트 신호
     - 표 후보
     - 폰트/헤딩 분포
   - 규칙으로 1차 분류한다: `text` / `scanned` / `image_heavy` / `diagram` / `chart` / `table` / `mixed`.
   - 경계 사례와 샘플 페이지만 VL 모델에 썸네일로 보내 2차 분류한다. 비용을 줄이기 위해 전 페이지를 보내지 않는다.
   - 결과는 문서 프로파일(유형별 페이지 비율)과 페이지별 라벨 + feature + 신뢰도다.

3. **Strategy (Planner) Agent**: 도구, 모델, 청킹 전략 선택
   - 페이지 유형마다 파서를 매핑한다.
     - text: PDF 텍스트 층 + 레이아웃 (ToolPDF `/v1/extract`)
     - scanned: VL OCR(또는 PaddleOCR 오프라인)
     - table: pdfplumber 또는 VL로 markdown 표 변환
     - diagram: VL 구조 설명
     - chart: VL로 설명 + 데이터 표 추출
   - 문서 프로파일로 청킹 전략을 고른다.
     - 헤딩 구조가 있으면 구조 기반(섹션 단위)
     - PPT는 슬라이드 단위(+노트)
     - 표와 그림은 atomic chunk(캡션 + VL 설명 + 주변 문맥)
     - 그 외는 recursive/semantic 분할
   - chunk size와 overlap은 임베딩 모델 max tokens와 문서 통계로 정한다.
   - 결정마다 `Decision{step, inputs(feature), rule_id, choice, alternatives, confidence, llm_reasoning?}`을 저장한다. UI는 이것을 근거로 표시한다.
   - 규칙 테이블은 `config/strategy_rules.yaml`로 외부화해 튜닝할 수 있게 한다.

4. **Parser Agents** (worker 병렬)
   - 페이지 배치 단위로 큐에 분산한다. 150MB 문서에서 메모리 폭주를 막기 위해 한 번에 한 페이지씩 렌더링한다.
   - 결과는 통일 스키마 `Element{page, bbox, type(text/title/table/figure/caption), content_md, source_tool}`로 저장한다.
   - VL 호출은 동시성 제한(semaphore)과 재시도를 건다. 실패한 페이지는 fallback 도구로 처리하고 결정 로그에 남긴다.

5. **Chunker Agent**
   - Element를 전략에 따라 chunk로 만든다. 메타데이터: doc_id, page range, bbox list, section path, element types, strategy_id.
   - 품질 지표: 토큰 분포, 너무 짧거나 긴 chunk 수, 표/그림 분할 여부.

6. **Embedding & Index Agent**
   - vLLM embeddings를 배치 호출한다. bge-m3면 sparse도 함께 만든다.
   - Qdrant에 upsert한다. collection은 모델명+dim 기준으로 나눈다.
   - 지표: 벡터 dim, norm 분포, 처리량, 실패 건수.

7. **Retrieval Agent**: 검색 확인
   - dense, sparse, hybrid(RRF)로 검색하고 선택적으로 rerank한다.
   - 각 결과의 점수를 단계별로 보여준다(dense, sparse, fused, rerank).
   - 원문 페이지에 bbox를 하이라이트한다.
   - 선택: LLM 답변 생성 + 인용.

## 관측성 / 근거 표시
- 모든 agent 이벤트를 `run_events` 테이블에 저장하고 SSE `/runs/{id}/stream`으로 push한다.
- 이벤트 종류: `step_started/finished`, `progress(page n/N)`, `decision`, `warning`, `error`.
- 결정 근거에는 사용한 feature 값, 매칭된 규칙, VL 판단 원문 요약, 대안과 미선택 사유가 들어간다.

## Web UI (rag-lab 스타일)
1. **문서 목록/업로드**: 선택 후 run을 시작하고 상태를 표시한다.
2. **Run 뷰**: agent DAG 실시간 상태, 진행률, 결정 타임라인(클릭하면 근거 상세).
3. **Parse Report**
   - 문서 프로파일 요약(유형 비율 차트)
   - 페이지 썸네일 그리드와 유형 배지
   - 페이지 클릭 시 원본과 추출 markdown을 좌우 비교하고, element bbox를 오버레이한다.
   - 사용된 도구도 표시한다.
4. **Chunk 뷰**: chunk 목록과 필터, 토큰 길이 히스토그램, chunk 경계를 원문 페이지에 오버레이, 메타데이터.
5. **Embedding 뷰**: 모델/dim/norm 통계, UMAP 2D 투영(유형·섹션별 색), chunk 간 최근접 이웃.
6. **Retrieval Playground**: 질의 입력, top-k와 hybrid 가중치 조절, 결과별 점수 breakdown, 원문 하이라이트, (선택) 답변.

## 프로젝트 구조 (초안)
```
IngestLens-v2/
  backend/app/
    api/            # FastAPI routers: documents, runs, stream(SSE), chunks, search
    agents/         # intake, profiler, strategy, parser, chunker, embedder, retriever
    graph/          # LangGraph 정의, 공통 state, emit_event/record_decision
    tools/          # toolpdf(PDF 엔진 클라이언트), vlm_client, table, embedding_client
    workers/        # arq worker, 페이지 배치 태스크
    models/         # SQLAlchemy 스키마 (Document, Run, Event, Decision, Element, Chunk)
  config/           # models.yaml(vLLM endpoint), strategy_rules.yaml
  frontend/         # React + Vite
  deploy/           # docker-compose (api, worker, redis, postgres, qdrant), 오프라인 반입 스크립트
  samples/          # 검증용 문서 세트
```

## 오프라인 환경 반입 체크리스트
- pip wheelhouse(`pip download`), npm 빌드 산출물(정적 파일로 반입)
- Docker 이미지: qdrant, redis, postgres, LibreOffice 포함 worker 이미지
- 한글 폰트(LibreOffice 변환 품질), PaddleOCR 모델 파일(사용 시)
- vLLM 모델 가중치: VL, 임베딩, (선택) reranker

## 단계별 진행 (Milestone)
1. **M1 골격**: docker-compose, FastAPI, DB 스키마, 업로드, LangGraph 뼈대, SSE 이벤트, Run 뷰. 텍스트 PDF 경로를 끝까지 연결한다(PDF 텍스트 추출 → recursive chunk → 임베딩 → Qdrant → 검색).
2. **M2 Profiler + Strategy**: 페이지 feature, 규칙 분류, VL 2차 분류, 결정 근거 저장과 UI, Parse Report 화면.
3. **M3 VL 파싱 경로** (완료): scanned OCR, 표, 다이어그램, 차트 처리, 병렬 worker, 대용량(150MB) 메모리/속도 튜닝. 구현 메모: arq/Redis 대신 서버 안 asyncio 작업과 page window 파이프라이닝을 썼다. 페이지 처리의 병렬은 ToolPDF의 프로세스(`TOOLPDF_WORKERS`)가 맡고, 앱은 여러 window를 미리 요청해 VLM 호출과 겹친다. 여러 서버 인스턴스로 확장할 때 arq로 옮긴다.
4. **M4 Office 형식** (완료): docx/pptx/xlsx 변환 + 네이티브 구조 힌트, 슬라이드 단위 청킹. 구현 메모: 변환은 ToolPDF `/v1/normalize`가 한다. LibreOffice가 없는 환경에서는 ToolPDF의 자체 렌더러를 쓴다. xlsx는 기본으로 자체 렌더링하고 헤더를 반복한다. 발표자 노트와 PPT 차트 데이터는 변환 결과의 `hints`로 받아 파싱에 쓴다.
5. **M5 Chunk/Embedding/Retrieval 뷰** (완료): 오버레이, 2D 투영, hybrid+rerank playground. 구현 메모: UMAP 대신 numpy PCA를 썼다(오프라인 반입 의존성 최소화). sparse 벡터 대신 BM25(한글 bigram)와 RRF를 썼다. LLM 답변 생성은 텍스트 LLM이 준비되면 추가한다.
6. **M6 튜닝** (도구 완료, 실제 데이터 튜닝은 남음): 샘플 세트 기준 분류 정확도와 검색 품질을 측정하고 규칙을 보정한다. 구현 메모: `scripts/eval_profile.py`(정확도, 혼동 행렬, 임계값 탐색), `scripts/eval_retrieval.py`(모드별 hit@k, MRR), 합성 평가 세트, `/tokenize` 기반 토큰 보정을 추가했다. 합성 세트 평가에서 작은 표 페이지 오분류를 발견해 `table_text_share` 규칙을 추가했다. 실제 문서 라벨링과 실제 모델 기준선 측정이 남아 있다.

## 검증
- 샘플 세트를 준비한다: 텍스트 PDF, 스캔 PDF, 다이어그램 많은 PPT, 차트 많은 보고서, 표 중심 xlsx/PDF, 150MB 대용량 PDF.
- Profiler: 수작업 라벨 대비 페이지 분류 정확도를 잰다.
- 대용량: 150MB 문서의 총 처리 시간, 최대 메모리, 실패 페이지 fallback 동작을 확인한다.
- UI: run을 실행하는 동안 SSE로 단계와 근거가 실시간 표시되는지 확인한다. 각 뷰에서 페이지와 bbox가 일치하는지 확인한다.
- 검색: 문서별 질의 10~20개로 recall@k를 측정하고 dense, hybrid, rerank를 비교한다.
- 백엔드는 pytest로 agent 단위 테스트를 한다(규칙 분류, 청킹 경계, 스키마 변환). vLLM은 mock client로 대체한다.
