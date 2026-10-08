# 평가와 튜닝 (M6)

규칙과 모델 설정을 바꾸기 전과 후에 같은 데이터로 측정해서 비교하기 위한 도구다.
합성 세트(`synthetic/`)는 바로 실행할 수 있는 예시다. 튜닝은 **실제로 처리할 문서에 직접 라벨을 붙인 세트**로 해야 의미가 있다.
모든 평가 스크립트는 저장소 루트에서 실행하고, PDF 엔진 ToolPDF가 떠 있어야 한다(`RAG_TOOLPDF_URL`, 기본 `http://127.0.0.1:8095`).

## 1. 페이지 분류 평가: `scripts/eval_profile.py`

```bash
.venv/Scripts/python scripts/eval_profile.py --labels evals/synthetic/profile_labels.json --sweep --out evals/reports/profile_<이름>.md
```

라벨 파일 형식은 아래와 같다. 페이지 번호는 1부터 센다. `file`은 라벨 파일 기준 상대 경로다.

```json
{"documents": [{"file": "manual.pdf", "pages": {"1": "text", "9": "table", "11": "scanned"}}]}
```

- 라벨 값은 `text`, `scanned`, `table`, `diagram`, `chart`, `image_heavy`, `mixed` 중 하나다.
- 평가 대상은 규칙(`config/strategy_rules.yaml`의 `profiler`)뿐이다. VLM 2차 판단은 제외한다.
- 결과: 정확도, 혼동 행렬, 틀린 페이지와 그 feature 값.
- `--sweep`: 규칙의 모든 임계값을 좌표 하강법으로 바꿔 보며 정확도가 오르는 변경을 **제안만** 한다. 설정 파일은 고치지 않는다.
  - 라벨이 적으면 과적합된다. 제안을 그대로 쓰기보다, 틀린 페이지의 feature를 보고 규칙이나 feature를 새로 만드는 편이 낫다.
  - 예: M6에서 추가한 `table_text_share` 규칙.

## 2. 검색 품질 평가: `scripts/eval_retrieval.py`

```bash
.venv/Scripts/python scripts/eval_retrieval.py --dataset evals/synthetic/retrieval.json --models config/models.yaml --out evals/reports/retrieval_<이름>.md
```

데이터셋 형식은 아래와 같다.

```json
{"documents": [{"file": "manual.pdf", "queries": [
  {"q": "냉각수 온도 유지 범위", "pages": [1], "kind": "lexical"},
  {"q": "설치 전에 준비할 것", "text": "전원 케이블", "kind": "paraphrase"}]}]}
```

- 정답 판정: 검색 결과가 `pages`(1부터 셈) 중 하나를 포함하거나, 본문에 `text`가 들어 있으면 정답이다.
- `kind`: 질의의 성격이다. 결과를 이 값별로 나눠 보여준다.
  - `lexical`: 문서의 단어를 그대로 쓴 질의
  - `paraphrase`: 다른 말로 바꿔 쓴 질의
  - 다른 값을 써도 된다.
- 동작: 문서마다 파이프라인 전체를 임시 data dir에서 실행한다. 그다음 dense, lexical, hybrid 방식으로 검색하고, reranker가 설정되어 있으면 hybrid+rerank도 실행한다.
- 지표: hit@1, hit@k, MRR@k.
- `--models`로 다른 `models.yaml`을 지정하면 모델끼리 비교할 수 있다.

## 3. VLM 품질 평가: `scripts/eval_vlm.py`

VL 모델을 바꿀 때 같은 문서로 OCR, 표, 그림 설명 품질을 재고 결과를 파일로 남긴다. 앱의 **"VLM 평가 비교"** 화면(`/#evals`)이 이 파일들을 나란히 보여준다.

```bash
.venv/Scripts/python scripts/eval_vlm.py --models <models.yaml> --name "Qwen2.5-VL-32B vLLM" --notes "A100 80GB, bf16, max_num_seqs 8"
```

- 결과는 `evals/results/vlm/<시각>_<이름>.json`에 저장된다. **git에 커밋한다.** 다른 PC나 오프라인 서버에서 잰 결과를 가져와 같은 화면에서 비교할 수 있다.
- 파일에는 다음이 들어간다.
  - 모델 설정(api_key 제외), git commit, prompt 해시, 평가 세트 버전
  - 항목별 점수, 페이지별 출력 전체
- 평가 세트 버전이나 prompt가 다른 결과를 고르면 화면에 경고가 뜬다.
- 시간 수치에는 모델을 처음 올리는 시간이 들어갈 수 있다. 속도를 비교하려면 같은 모델로 두 번 돌려 두 번째 값을 본다.

평가 세트 `evals/vlm/cases.json`의 형식은 아래와 같다. 페이지는 1부터 센다. `expect`의 항목은 모두 선택이다.

```json
{"name": "합성 5페이지", "documents": [{"file": "vlm_doc.pdf", "cases": [
  {"page": 2, "id": "scan_text", "title": "스캔 본문", "expect": {"label": "scanned", "ocr_text": "...", "facts": ["NF3"], "title": "비상 대응 절차", "no_single_column_table": true}}]}]}
```

| expect 키 | 확인 내용 | 점수 |
|---|---|---|
| `label` | 페이지 분류(VLM 2차 판단 후) | 일치 여부 |
| `ocr_text` | 페이지 전체 출력과 정답의 문자 오류율(CER). 공백과 Markdown 기호는 뺀다 | 1 − CER, 0.95 이상이면 통과 |
| `facts` | 출력에 들어 있어야 하는 문자열 (공백 하나까지 비교) | 포함 비율 |
| `title` | 이 문자열을 포함한 title element가 있는지 | 일치 여부 |
| `no_single_column_table` | 본문을 1열짜리 표로 만들지 않았는지 | 일치 여부 |
| `table_cells`, `table_columns` | 표 element 안의 셀 값, 열 수 | 포함 비율, 일치 여부 |
| `figure_type` | 그림 답 첫 줄의 `TYPE:` | 일치 여부 |
| `figure_facts` | 그림 설명에 들어 있어야 하는 값과 라벨 | 포함 비율 |
| `language: "ko"` | 그림 설명의 한글 비율. 표 안의 값은 뺀다 | 50% 이상이면 통과 |
| `caption` | 그림이나 표에 연결된 캡션 | 일치 여부 |

평가 세트는 두 가지다. `--cases`로 고른다. 화면에서는 세트별로 나눠서 비교한다.

| 세트 | 위치 | 내용 |
|---|---|---|
| 합성 5페이지 (기본) | `evals/vlm/` | 커밋된 합성 PDF 1개(`vlm_doc.pdf`). 텍스트 대조군, 스캔 본문, 스캔 표, 막대 차트, 공정 흐름도. 정답을 정확히 알고 있어 OCR 문자 오류율을 잰다 |
| 실제 공개 문서 10종 | `evals/samples/` | 공개 문서 10개(50페이지)에서 17개 페이지를 채점한다. 아래 표 |

```bash
.venv/Scripts/python scripts/eval_vlm.py --cases evals/samples/cases.json --models <models.yaml> --name "<이름>"
```

실제 공개 문서 10종(`evals/samples/`, 출처와 라이선스는 `SOURCES.md`):

| 파일 | 유형 | 채점 페이지에서 보는 것 |
|---|---|---|
| `ko_text_hunminjeongeum` | 한국어 글자 위주 (위키백과) | 본문 분류, 사실 포함 (VLM 없이 텍스트층) |
| `ko_image_gyeongbokgung` | 사진 위주 (위키백과) | 사진 TYPE, 한국어 설명 |
| `ko_chart_population` | 벡터 차트 위주 (위키백과) | 차트 분류, 축과 제목 읽기 |
| `ko_chart_kostat` | 벡터 차트 + 표 (국가데이터처 보도자료) | 차트 안의 수치 라벨, `[그림 1]` 캡션, 표 셀 |
| `ko_table_kostat` | 표 위주 (같은 보도자료) | 복잡한 통계표의 셀 (텍스트층) |
| `ko_scan_kostat` | 한국어 스캔 모사 (같은 보도자료의 이미지 변환) | 스캔 OCR의 사실·표 셀. `ko_table_kostat`와 같은 표를 OCR로 읽어 비교 |
| `ko_mixed_seoul` | 혼합 (위키백과) | 기후 표 셀 |
| `en_scan_naca1135` | 영어 실제 스캔 (1953년 NACA 보고서) | 오래된 OCR 텍스트층의 오류(`1_28`)를 그대로 믿는지, 90도 회전된 차트 |
| `en_mixed_nist` | 영어 혼합 (NIST SP 800-207) | 다이어그램 이미지 안의 라벨 |
| `en_paper_docling` | 영어 논문 (arXiv, CC BY) | 아이콘 파이프라인 그림, 선 없는 표 |

- 모델과 상관없이 실패하는 항목도 있다. 예: 선 없는 표(Docling Table 1)는 지금의 표 추출이 잡지 못한다. 이런 항목은 모델 비교가 아니라 파이프라인 개선 과제로 본다(`docs/HANDOFF.md` 6절).
- 문서를 추가하려면 재배포 가능한 라이선스의 원본에서 페이지를 발췌한 PDF를 `evals/samples/`에 넣고, `SOURCES.md`에 원본, 사용한 페이지, 변경 내용, 출처 표시를 적은 뒤, `cases.json`에 기대값을 손으로 적는다. 기대값은 페이지 이미지를 직접 보고 적는다.
- 결과 파일의 `dataset_version`은 기대값과 ToolPDF가 그린 40dpi 페이지 이미지로 계산한다. 문서나 기대값이 바뀌면 값이 달라지고, 화면은 버전이 다른 결과를 섞어 고를 때 경고한다.

## 4. 튜닝 순서

1. 실제 문서 5~20개를 고른다. 형식과 유형이 골고루 섞이게 한다.
2. 페이지 라벨 파일과 질의 20~50개를 만든다. 질의에는 문서 단어를 그대로 쓴 것과 바꿔 쓴 것을 섞는다.
3. 기준선을 측정한다. 두 스크립트를 실행하고 보고서를 `evals/reports/`에 저장한다.
4. 규칙, 모델, 청킹 파라미터 중 **하나만** 바꾼다.
5. 다시 측정하고 기준선과 비교한다. 좋아졌으면 유지하고, 결과를 `docs/HANDOFF.md`의 측정 기록 표에 추가한다.

## 현재 기준선 (합성 세트)

| 날짜 | 설정 | 페이지 분류 정확도 | hybrid hit@1 (전체 / 바꿔 쓴 질의) | hybrid+rerank hit@1 |
|---|---|---|---|---|
| 2026-09-30 | dev-hash 임베딩, VLM 없음 | 100% (12페이지) | 82% / 62% | — |
| 2026-10-04 | Ollama `bge-m3` + `qwen2.5vl:7b`, reranker `bge-reranker-v2-m3` | — | 82% / 50% (dense만 95% / 88%) | 100% |

| 날짜 | VLM (평가 세트 `a86b25c26f53`) | 종합 | 통과 | 실패 항목 |
|---|---|---|---|---|
| 2026-10-04 | Ollama `qwen2.5vl:7b` (Q4_K_M) | 92% | 17/19 | 그림 설명이 영어 |
| 2026-10-04 | Ollama `qwen2.5vl:3b` (Q4_K_M) | 86% | 16/19 | 스캔 제목 미인식, 차트를 diagram으로 분류, 흐름도 설명이 영어 |

| 날짜 | VLM (실제 공개 문서 10종 `c8e06ba6495f`) | 종합 | 통과 | 실패 항목 |
|---|---|---|---|---|
| 2026-10-04 | Ollama `qwen2.5vl:7b` (Q4_K_M) | 90% | 36/43 | 사진·차트 설명이 영어, 보도자료 차트를 diagram으로 분류, `[그림 1]` 캡션, 스캔 통계표 마지막 행, 선 없는 표 |
| 2026-10-04 | 위와 같음, 대괄호 캡션 규칙과 잘림 재시도 적용 후 | 92% | 38/43 | 사진·차트 설명이 영어, 보도자료 차트를 diagram으로 분류, 선 없는 표 |
| 2026-10-04 | Ollama `qwen2.5vl:3b` (Q4_K_M) | 51% | 18/43 | VLM 호출 47회 중 41회가 반복 중단(`token repeat limit reached`) |

- 보고서: `reports/profile_synthetic.md`, `reports/retrieval_synthetic_devhash.md`, `reports/retrieval_synthetic_mockhttp.md`, `reports/retrieval_synthetic_ollama.md`, `results/vlm/*.json`
- 합성 세트는 규칙을 만든 사람이 만든 데이터라서 점수가 높게 나온다. 실제 문서 기준선을 새로 만들어야 한다.
- 바꿔 쓴 질의가 약한 것은 dev-hash가 의미를 모르기 때문이다. 실제 임베딩 모델(bge-m3 등)을 연결하면 가장 먼저 이 수치를 확인한다.
