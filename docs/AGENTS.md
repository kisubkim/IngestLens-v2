# 에이전트 구성과 판단 기준

IngestLens는 문서 하나를 여러 에이전트가 차례로 처리한다. 이 문서는 어떤 에이전트가 있고, 각자 무엇을 하며, 어떤 기준으로 무엇을 정하는지 정리한다. 기준값은 모두 `config/strategy_rules.yaml`과 `config/models.yaml`에 있고, 아래 표의 값은 2026-10-09 기본값이다. 규칙 값은 웹 화면 **"에이전트 규칙"**에서 바로 바꿀 수 있다(11절).

## 1. 한눈에 보기

```
업로드 ─▶ ① intake ─▶ ② profile ─▶ ③ strategy ─▶ ④ parse ─▶ ⑤ chunk ─▶ ⑥ embed ─▶ Qdrant
          형식 판별     쪽 성격 분석   파서·청킹 결정   내용 추출     청크 나누기    임베딩
                                                                              │
                                    검색 화면 / 검색 API ◀── ⑦ retriever ◀─────┘
```

| # | 에이전트 | 코드 | 하는 일 | 정하는 것 |
|---|---|---|---|---|
| ① | intake | `backend/app/agents/intake.py` | 진짜 형식을 판별하고 모든 문서를 PDF로 바꾼다 | 변환 방법(그대로, 이미지 감싸기, LibreOffice, 자체 렌더링) |
| ② | profile | `agents/profiler.py` | 쪽마다 특징을 재서 성격(텍스트, 스캔, 표, 다이어그램, 차트, 이미지, 혼합)을 붙인다 | 쪽 라벨, 애매한 쪽은 VLM에 다시 묻기, 문서 성격 |
| ③ | strategy | `agents/strategy.py` | 쪽 라벨에 맞는 파서와 문서에 맞는 청킹 방식을 고른다 | 쪽별 파서, 청킹 전략, 청크 크기·겹침·최소 크기, 토큰 환산 비율 |
| ④ | parse | `agents/parser.py` | 계획대로 쪽 내용을 꺼낸다. 스캔 OCR, 그림 설명, 표 재추출에 VLM을 쓴다 | VLM 결과를 쓸지 원문 텍스트로 대체할지, 표 재추출, 캡션 연결, 차트로 다시 분류 |
| ⑤ | chunk | `agents/chunker.py` | 꺼낸 요소를 검색 단위(청크)로 묶는다 | 청크 경계, 짧은 청크 합치기 |
| ⑥ | embed | `agents/embedder.py` | 청크를 임베딩해 Qdrant에 넣는다 | 임베딩 모델(설정이 없으면 시험용 대체) |
| ⑦ | retriever | `agents/retriever.py` | 처리된 문서를 검색한다(파이프라인 밖, 검색 화면과 API) | 후보 합치기(RRF), rerank |

### "에이전트"의 뜻

여기서 에이전트는 **판단을 맡은 처리 단계**다. LLM이 스스로 계획을 세우고 도구를 고르는 자율 에이전트가 아니다.
- 각 단계는 **규칙(데이터)으로 먼저 판단**한다. 규칙은 `config/strategy_rules.yaml`에 있어 코드를 고치지 않고 조정한다.
- 규칙만으로 애매하거나(쪽 분류의 신뢰도가 낮을 때) 사람처럼 읽어야 할 때(스캔 OCR, 그림 설명, 깨진 표)만 **VLM에 묻는다.**
- 이렇게 한 이유는 속도와 부하(VLM 호출을 꼭 필요한 곳에만), 그리고 **판단 근거를 설명할 수 있게** 하려는 것이다.

이 순서는 LangGraph 그래프 하나로 묶여 있다(`backend/app/graph/pipeline.py`).

### 모든 에이전트가 따르는 약속

- **판단마다 근거를 남긴다.** 자동으로 무언가를 정할 때마다 `record_decision`으로 규칙 이름(`rule_id`), 입력값, 고르지 않은 대안과 그 이유, 신뢰도, 설명을 DB에 저장한다. 화면의 실행 → **"근거"** 탭에 그대로 보인다. 대체 동작(VLM 없음, VLM 실패 등)도 판단이므로 같이 남긴다.
- **진행 상황은 이벤트로 알린다**(`emit_event`). 화면이 실시간으로 받는다(SSE).
- **상태는 DB에 둔다.** 앞 에이전트가 쪽 분석, 요소, 청크를 DB에 쓰고 다음 에이전트가 읽는다. 단계 사이에 넘기는 것은 ID, 경로, 요약, 계획뿐이다.
- **실패해도 멈추지 않는 곳은 대체한다.** VLM 오류는 쪽 단위로 원문 텍스트로 대체하고 실행은 계속한다. 모델 주소가 비어 있으면 그 기능만 끄고 진행한다.
- **문서는 하나씩 처리한다.** 여러 문서를 넣으면 들어온 순서대로 대기열에 선다.
- **PDF 작업은 모두 ToolPDF가 한다.** 에이전트는 ToolPDF HTTP API로 특징, 추출 결과, 쪽 이미지를 받아 판단만 한다.

## 2. ① intake: 형식 판별과 PDF 변환

**하는 일.** 파일의 실제 형식을 확장자와 파일 내용(magic bytes)으로 함께 판별하고, 모든 문서를 PDF 쪽으로 통일한다. 이후 단계가 형식과 상관없이 같은 방식(쪽 분석, 위치 표시, 화면)으로 동작하게 하기 위해서다.

| 형식 | 판단 | 근거 `rule_id` |
|---|---|---|
| PDF | 그대로 쓴다 | `magic_pdf` |
| 이미지(png, jpg, tif 등) | 한 쪽짜리 PDF로 감싼다 | `image_wrap` |
| docx, pptx, xlsx | 아래 규칙으로 LibreOffice 또는 ToolPDF 자체 렌더링 | `office_convert` / `office_native` |
| doc, ppt, hwp 등 | LibreOffice가 있어야 한다. 없으면 실패 | — |
| 그 밖 | 지원하지 않는 형식으로 실패 | — |

**Office 변환 방법을 고르는 기준** (`strategy_rules.yaml` `office`):
- 자체 렌더링을 쓰는 경우: `prefer: native`이거나, ToolPDF에 LibreOffice가 없거나, xlsx이면서 `xlsx: native`(기본)일 때. 넓은 시트를 LibreOffice는 쪽마다 잘라 표가 깨지기 때문이다. 시트는 24행씩 한 쪽(`xlsx_rows_per_page`)으로 나누고 머리 행을 반복한다.
- 그 밖에는 LibreOffice(원본 레이아웃에 가장 가깝다).
- 어느 쪽이든 PDF에 남지 않는 구조를 **힌트**로 함께 받는다: docx 제목 스타일, 슬라이드 제목, 발표자 노트, pptx 차트 데이터. ④ parse가 쓴다.

**그 밖의 판단:**
- 확장자와 내용이 다르면 경고하고 근거의 신뢰도를 0.7로 낮춘다(내용을 따른다).
- 암호가 걸린 PDF는 처리하지 않는다.

## 3. ② profile: 쪽 성격 분석

**하는 일.** ToolPDF가 쪽마다 특징을 재면(20쪽씩), 규칙으로 쪽에 라벨을 붙인다. 이 라벨이 ③에서 파서를 고르는 기준이 된다.

**재는 특징:** 글자 수(`text_chars`), 텍스트 면적 비율, 이미지 수와 면적 비율(`image_area_ratio`), 벡터 도형 수(`drawings`), 표 수와 면적 비율(`table_area_ratio`), 표 안 글자 비율(`table_text_share`), 글꼴 크기 분포(`size_hist`).

**규칙** (`profiler.rules`, 위에서부터 차례로 보고 **처음 맞는 규칙**을 쓴다):

| 순서 | 규칙 `id` | 라벨 | 조건 | 뜻 |
|---|---|---|---|---|
| 1 | `scanned` | scanned | 글자 ≤ 50, 이미지 면적 ≥ 0.5 | 글자층이 없고 쪽이 이미지 → 스캔 |
| 2 | `table_dominant` | table | 표 ≥ 1, 표 면적 ≥ 0.3 | 표가 쪽의 큰 부분 |
| 3 | `table_text_share` | table | 표 ≥ 1, 표 안 글자 비율 ≥ 0.5 | 작은 표지만 쪽 글자 대부분이 표 안 |
| 4 | `vector_drawings` | diagram | 벡터 도형 ≥ 120 | 선과 도형이 많음 → 구성도·회로도·차트 |
| 5 | `image_area` | image_heavy | 이미지 면적 ≥ 0.4 | 사진·그림 위주 |
| 6 | `text_rich` | text | 글자 ≥ 200 | 본문 위주 |
| — | `fallback_mixed` | mixed | 어느 규칙에도 안 맞음 | 신뢰도 0.4 |

**신뢰도:** 맞은 규칙의 조건 가운데 기준값에서 가장 덜 벗어난 것을 기준으로 `0.5 + 0.5 × 여유`(최대 1.0)다. 기준값을 겨우 넘으면 0.5 근처, 넉넉히 넘으면 1.0이다. 조건별 실제값과 기준값이 쪽마다 근거로 저장된다.

**VLM 2차 판단:** 신뢰도가 0.6(`vlm_review_below`) 미만인 쪽을 신뢰도 낮은 순으로 최대 10쪽(`vlm_review_max_pages`)까지 골라, 쪽 이미지(100 dpi)를 VLM에 보여 주고 라벨을 JSON으로 묻는다.
- VLM이 다른 유효한 라벨을 말하면 그 라벨로 바꾸고 신뢰도 0.7(`vlm_review`, "relabel").
- 같은 라벨이거나 엉뚱한 답이면 규칙 라벨을 유지(`vlm_review`, "keep").
- VLM이 설정되지 않았으면 묻지 않고 규칙 라벨을 유지(`vlm_not_configured`).
- `chart` 라벨은 규칙으로는 붙지 않고 VLM 판단(여기 또는 ④의 그림 분석)으로만 붙는다.

**문서 성격:** 가장 많은 라벨이 전체 쪽의 60%(`strategy.dominant_ratio`) 이상이면 `<라벨>-dominant`(예: `text-dominant`), 아니면 `mixed`(`dominant_ratio`).

## 4. ③ strategy: 파서와 청킹 방식 결정

### 4-1. 쪽별 파서 (`label_to_parser`)

| 쪽 라벨 | 파서 | 하는 일 |
|---|---|---|
| text, mixed | `pymupdf_text` | 글자층에서 제목·본문 추출 |
| table | `pymupdf_tables` | 글자 + 괘선 표를 Markdown 표로 |
| scanned | `vlm_ocr` | 쪽 전체 이미지를 VLM이 Markdown으로 받아쓰기 |
| diagram, chart, image_heavy | `vlm_figures` | 글자 + 그림 영역마다 VLM 설명 |

(`pymupdf_*`는 ToolPDF의 `text` 모드를 가리키는 이름일 뿐, 이 저장소가 PDF 라이브러리를 쓰는 것은 아니다.)

- VLM이 설정되지 않았으면 VLM 파서는 `pymupdf_text`로 바꾸고, 바뀐 라벨들을 대안으로 남기며 신뢰도를 0.6으로 낮춘다.

### 4-2. 청킹 전략 (`chunking`)

위에서부터 처음 맞는 것을 고른다.

| 조건 | 전략 | 근거 `rule_id` | 이유 |
|---|---|---|---|
| 슬라이드(ppt, pptx, odp) | `page` | `slides` | 슬라이드 한 장이 한 단위 |
| 시트(xls, xlsx, ods) | `page` | `sheets` | 쪽마다 머리 행이 있는 표 덩어리 |
| docx에 제목 스타일이 있음 | `section` | `docx_headings` | 작성자가 정한 제목으로 나눔 |
| 제목 크기 글자가 있는 쪽이 15% 이상 | `section` | `heading_structure` | 문서에 절 구조가 있음 |
| 그 밖 | `recursive` | `no_structure` | 크기 기준으로 나눔 |

**제목 판별:** 문서 전체에서 글자 수가 가장 많은 글꼴 크기를 본문 크기로 보고, 그 1.15배(`heading_size_ratio`) 이상을 제목 크기로 본다. 이 값(`heading_min_size`)은 ④에서 ToolPDF가 제목 줄을 나눌 때도 쓴다.

**크기 (토큰 단위):**

| 값 | 설정 | 기본 | 제한 |
|---|---|---|---|
| 청크 크기 | `target_tokens` | 512 | 임베딩 모델 `max_tokens - 16` 이하 |
| 겹침 | `overlap_tokens` | 64 | 청크 크기의 1/4 이하 |
| 최소 크기(짧은 청크 합치기) | `min_tokens` | 128 | 청크 크기의 1/2 이하 |

**토큰 환산 비율:** 청킹은 글자 수로 재므로, 문서 앞 6,000자를 임베딩 서버의 `/tokenize`로 세어 "글자/토큰" 비율을 문서마다 잰다(`tokenizer_calibrated`, 0.8~6.0으로 제한). 잴 수 없으면 기본 2.5(`tokenizer_default`). Ollama는 `/tokenize`가 없어 기본값을 쓴다.

## 5. ④ parse: 내용 추출

**하는 일.** 10쪽(`window_pages`)씩 묶어 ToolPDF에 추출을 요청하고(동시에 6묶음, `windows_in_flight`), 그 묶음의 VLM 호출을 처리하는 동안 다음 묶음을 준비한다. 결과는 쪽마다 요소(title, text, table, figure)로 저장한다.

| 상황 | 판단 | 근거 `rule_id` |
|---|---|---|
| 스캔 쪽(`vlm_ocr`) | VLM의 Markdown 답을 제목·본문·표 요소로 나눠 쓴다. 답이 비었거나 오류면 글자층으로 대체 | (실패 시) `vlm_error` |
| 그림 영역 | 이미지·도형 덩어리가 쪽의 4% 이상(`figures.min_area_ratio`)이면 그림으로 보고 쪽당 최대 4개(`max_per_page`)를 VLM에 설명시킨다. 텍스트·표 쪽의 그림도 설명한다(`enrich_native_pages`). 영역을 못 찾은 그림 쪽은 쪽 전체를 그림으로 본다 | `figure_regions` (VLM 없으면 `vlm_not_configured`) |
| 그림 종류 | VLM 답의 첫 줄 `TYPE: <종류>`를 읽는다(chart, diagram, photo, table, text 중 하나). 없거나 모르는 값이면 diagram | — |
| 다이어그램·이미지 쪽에 큰 차트 | 쪽 면적 30% 이상(`relabel_chart_min_area`)을 차트가 차지하면 쪽 라벨을 chart로 바꾼다 | `vlm_figure_type` |
| 빈 칸이 많은 표 | 빈 칸 비율이 0.5(`tables.max_empty_cell_ratio`)를 넘으면(병합 셀, 선 없는 칸) 그 표를 잘라 VLM으로 다시 읽는다. 실패하면 원래 표 유지 | `table_empty_cells` |
| VLM 답이 잘림 | 답이 `max_tokens`(2048)에서 끊기면 한 번 더 `max_tokens_retry`(4096)로 요청한다 | `vlm_truncated_retry` |
| 캡션 | "그림 1", "[표 2]", "Figure 3" 같은 줄(`captions.pattern`)이 그림·표 위아래 40pt(`max_gap`) 안에 있으면 그 요소 안으로 옮긴다 | — |
| Office 힌트 | 제목 스타일·슬라이드 제목과 같은 줄은 제목으로, 발표자 노트는 본문으로 붙이고, LibreOffice 변환 시 pptx 차트 데이터는 표로 더한다 | — |

**읽는 순서:** 요소는 위→아래, 왼쪽→오른쪽 순으로 정렬한다. 쪽 전체를 그림으로 본 경우 그 그림은 쪽의 글자 뒤에 둔다(그래야 그림 청크가 그 쪽의 절에 들어간다).

**VLM 부하:** 모든 실행이 공유하는 동시 호출 상한(`models.yaml` `vlm.max_concurrency`)이 있다. VLM 호출이 실패해도 그 쪽만 대체하고 실행은 계속한다.

## 6. ⑤ chunk: 청크 나누기

**하는 일.** ④가 만든 요소를 ③이 정한 전략과 크기로 묶는다(`backend/app/tools/chunking.py`).

- **제목**이 나오면 절이 바뀐다(`section` 전략에서는 청크도 끊는다). 제목 첫 줄이 번호뿐이면("8.6") 다음 줄까지 절 이름으로 쓴다("8.6 WHO_AM_I (0Fh)"). 청크 본문 앞에 절 이름을 붙여, 청크만 봐도 어느 절인지 알게 한다.
- **표와 그림은 쪼개지 않는다.** 표가 청크 크기보다 길면 행 단위로 나누고 머리 행을 반복한다.
- **`page` 전략**(슬라이드, 시트)은 쪽이 바뀌면 끊는다.
- 본문이 크기를 넘어 끊길 때만 앞 청크 끝 64토큰을 다음 청크 앞에 반복한다(겹침). 절·표·그림 경계에서는 겹치지 않는다.
- **짧은 청크 합치기** (`chunk_merge`): 128토큰(`min_tokens`) 미만 청크를 같은 절의 다음 청크(안 되면 앞 청크)와 합친다. 최대 `청크 크기 + 최소 크기`. 절이 다르거나 `page` 전략에서 쪽이 다르면 합치지 않는다. 합친 청크는 모든 쪽과 위치를 유지하고, 겹침으로 반복된 부분은 다시 넣지 않는다. 근거에 합치기 전후 청크 수가 남는다.
- **경고:** 청크의 20% 넘게 너무 짧거나(크기의 0.2배 미만) 너무 길면(1.5배 초과) 경고 이벤트를 남긴다.

각 청크는 본문, 토큰 수, 쪽 목록, 쪽별 위치(bbox), 절, 요소 종류를 갖는다. 위치는 화면의 겹쳐 보기와 Open WebUI 쪽 이미지 썸네일(칠한 영역)에 쓰인다.

## 7. ⑥ embed: 임베딩

- `models.yaml` `embedding.base_url`이 있으면 그 모델로 임베딩한다(`configured_endpoint`).
- 없으면 시험용 `dev-hash`(글자 3개 묶음 해시)로 대체한다(`embedding_not_configured`, 신뢰도 0.2). 키워드가 겹치는 정도만 반영하므로 의미 검색은 되지 않는다.
- Qdrant 컬렉션은 모델 이름과 차원별로 따로 둔다. 같은 문서를 다시 실행하면 그 문서의 이전 벡터를 지우고 새로 넣는다(검색은 문서당 최신 실행 하나).

## 8. ⑦ retriever: 검색 (파이프라인 밖)

검색 화면과 `POST /api/search`가 쓴다. Open WebUI는 IngestLens 청크를 받아 **자기 검색**을 하므로 이 에이전트를 거치지 않는다(`deploy/OPENWEBUI.md`).

| 방식 | 판단 |
|---|---|
| `dense` | 질문 임베딩과 가까운 청크(해당 실행만) |
| `lexical` | BM25. 한글은 두 글자 조각(bigram)으로 색인해 형태소 분석기가 필요 없다 |
| `hybrid` | 두 순위를 RRF(k=60)로 합친다: `가중치 / (60 + 순위)`의 합. dense·BM25 가중치를 바꿀 수 있다 |
| rerank (선택) | 합친 후보 상위 `top_k × 3`개를 reranker로 다시 매긴다 |

- 후보는 방식마다 `max(top_k × 4, 20)`개까지 모은다.
- 결과마다 단계별 점수와 순위(dense, BM25, 합친 점수, rerank)를 함께 돌려줘 왜 그 순위인지 보인다.

## 9. VLM을 쓰는 곳과 없을 때

| 쓰는 곳 | 에이전트 | VLM이 없으면 |
|---|---|---|
| 신뢰도 낮은 쪽의 라벨 2차 판단 | ② profile | 규칙 라벨 유지 |
| 스캔 쪽 받아쓰기(OCR) | ④ parse | 글자층으로 대체(스캔이면 거의 비어 있음) |
| 그림 설명과 종류(TYPE) | ④ parse | 그림 내용이 색인에 빠짐 |
| 빈 칸 많은 표 다시 읽기 | ④ parse | 원래 표 유지 |

VLM에 보내는 질문 형식(프롬프트)과 그 답을 읽는 규칙은 `backend/app/tools/vlm.py`의 `PROMPTS`와 `tools/vlm_output.py`가 짝을 이룬다. 시험용 가짜 서버 `scripts/mock_vllm.py`도 같은 형식을 흉내 낸다. 프롬프트를 바꾸면 셋을 함께 고친다.

## 10. 근거(`rule_id`) 목록

| `rule_id` | 에이전트 | 뜻 |
|---|---|---|
| `magic_pdf`, `image_wrap`, `office_convert`, `office_native` | intake | 변환 방법 |
| 규칙 `id`(`scanned` 등), `fallback_mixed` | profile | 쪽 라벨(쪽 분석 화면에 쪽마다) |
| `vlm_review` | profile | VLM 2차 판단(유지 또는 변경) |
| `vlm_not_configured` | profile, parse | VLM이 없어 건너뜀 |
| `dominant_ratio` | profile | 문서 성격 |
| `label_to_parser` | strategy | 쪽별 파서 |
| `slides`, `sheets`, `docx_headings`, `heading_structure`, `no_structure` | strategy | 청킹 전략 |
| `tokenizer_calibrated`, `tokenizer_default` | strategy | 토큰 환산 비율 |
| `vlm_error` | parse | VLM 실패 또는 빈 답 → 글자층 대체 |
| `vlm_truncated_retry` | parse | 잘린 답 다시 요청 |
| `table_empty_cells` | parse | 표를 VLM으로 다시 읽음 |
| `vlm_figure_type` | parse | 큰 차트로 쪽을 chart로 다시 분류 |
| `figure_regions` | parse | 그림 설명 결과 요약 |
| `chunk_merge` | chunk | 짧은 청크 합치기 |
| `configured_endpoint`, `embedding_not_configured` | embed | 임베딩 모델 |

## 11. 기준을 바꾸려면

### 11-1. 화면에서 바꾸기: "에이전트 규칙" (`/#rules`)

이 문서의 값은 웹 화면에서 바꾸고 **바로 적용**할 수 있다(서버 재시작 없음).

- **들어가는 길:**
  - 왼쪽 아래 **"에이전트 규칙"** 버튼
  - 실행 화면 위쪽의 **단계 상자**(형식 판별, 콘텐츠 분석, 전략 결정, 파싱, 청킹, 임베딩)를 누르면 그 단계의 탭이 열린다
  - 근거 상세의 **"이 단계 규칙 보기·바꾸기"**
  - 주소로 바로: `/#rules/profile`, `/#rules/parse`, `/#rules/chunk` 등
- **화면:** 에이전트별 탭에 그 단계가 쓰는 값이 설명, 기본값, 허용 범위와 함께 나온다. 기본값과 다른 값에는 "바꿈" 표시가, 탭에는 점이 붙는다. 쪽 분류 규칙은 표에서 조건을 고치고, 규칙을 추가·삭제·순서 변경한다(위에서부터 처음 맞는 규칙이 쓰이므로 순서가 중요하다).
- **저장하고 적용:** 서버가 값을 검사한다(종류, 범위, 선택지, 정규식, 겹침 ≤ 청크 크기의 1/4, 최소 크기 ≤ 1/2, 깨진 글자). 문제가 있으면 무엇을 고칠지 보여 주고 저장하지 않는다. 저장하면 다음에 시작하는 실행부터 새 값으로 판단한다. 문서를 열어 둔 채 들어왔으면 저장 뒤 그 문서를 **바로 다시 실행**하는 버튼이 나온다.
- **되돌리기:** 항목별 "기본값으로", 탭별 "이 단계 값 모두 기본값으로", 전체 "모두 기본값으로".
- **저장 위치:** 저장소의 `config/strategy_rules.yaml`(기본값)은 고치지 않는다. 바꾼 항목만 데이터 폴더의 `strategy_rules.override.yaml`에 저장한다. 데이터 폴더와 함께 백업되고, 새 버전의 기본값이 바뀌어도 바꾸지 않은 항목은 새 기본값을 따른다. 쪽 분류 규칙 목록은 통째로 저장한다.
- **어떤 값으로 처리했는지:** 실행마다 규칙 버전(유효 규칙의 해시)과 화면에서 바꾼 값을 썼는지가 "전략 결정 → chunking" 근거와 실행 요약(`plan.rules_version`)에 남는다. 값을 바꾼 전후 실행을 비교할 때 본다.
- **권한:** 저장 위치 설정과 같다. 서버에 `RAG_API_KEY`가 있으면 그 키가 필요하고, 없으면 서버 PC에서 접속했을 때만 바꿀 수 있다. 보기는 누구나 된다.
- **주의:**
  - 실행 중인 문서는 아직 시작하지 않은 단계부터 새 값을 쓴다(화면이 알려 준다).
  - 바꾼 규칙 파일을 손으로 잘못 고쳤거나 파일이 깨졌으면, 앱은 멈추지 않고 기본 규칙으로 처리하며 화면 맨 위에 이유를 보여 준다.
  - 모델 주소(VLM, 임베딩, reranker)는 이 화면이 아니라 `config/models.yaml`에서 정한다.

### 11-2. 파일로 바꾸고 효과 재기

1. 기본값 자체를 바꾸려면 `config/strategy_rules.yaml`을 고친다. 앱을 다시 시작하면 새 실행부터 적용된다(화면에서 바꾼 값이 있으면 그 값이 우선한다).
2. 문서를 다시 실행해 "근거" 탭과 쪽 분석·파싱 리포트·청크 화면에서 결과를 본다.
3. 효과는 평가 스크립트로 잰다(`evals/README.md`): 쪽 분류는 `scripts/eval_profile.py`(임계값 탐색 `--sweep` 포함), 검색은 `scripts/eval_retrieval.py`, VLM 품질은 `scripts/eval_vlm.py`.
4. 규칙을 바꾸면 회귀 테스트(`backend/tests/test_profiler.py`, `test_chunking.py`)에 남기고, 측정은 `docs/HANDOFF.md` 7절에 적는다.
