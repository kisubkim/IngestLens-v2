# PDF 엔진 인터페이스 계획: ToolPDF와 MIT 내장 엔진

작성 2026-10-10. 상태: **1~5단계 구현됨**(2026-10-10). 결정은 8절, 구현 결과와 측정은 9절.

## 1. 목표

- 지금 IngestLens는 모든 PDF 작업을 별도 프로그램 ToolPDF(AGPL-3.0, PyMuPDF)에 HTTP로 맡긴다.
- 앞으로 **ToolPDF 없이도** 같은 기능을 쓰고 싶다. 앱 안에서 도는 내장 엔진을 MIT·BSD·Apache 같은 퍼미시브 라이선스 라이브러리로만 만든다.
- 앱은 하나로 두고 **배포 형태만 둘**로 한다(8절 결정 2): ToolPDF와 함께, 또는 ToolPDF 없이 내장 엔진만. 엔진 인터페이스는 나중에 다른 MIT 앱도 쓸 수 있게 앱과 떼어 둔다.

정리하면, "PDF 엔진"이라는 인터페이스 하나와 구현 둘을 둔다.

```
                    ┌─────────────────────────────┐
  IngestLens 앱 ──▶ │  PdfEngine 인터페이스          │ ◀── 다른 MIT 앱
  (에이전트들)        │  info text profile extract  │
                    │  render normalize health    │
                    │  capabilities options       │
                    └──────┬───────────────┬──────┘
                           │               │
              ToolPDFEngine│               │LocalEngine
          (HTTP 클라이언트, MIT)│               │(앱 안, MIT 라이브러리만)
                           ▼               ▼
                 ToolPDF 서버(AGPL,       pypdfium2, pdfplumber/pdfminer.six,
                 별도 프로세스, PyMuPDF)     Pillow, reportlab, python-docx/pptx, openpyxl
```

## 2. 왜 이렇게 하나

| 방식 | 장점 | 단점 |
|---|---|---|
| ToolPDF만 | 품질이 가장 좋다(PyMuPDF). 이미 시험됨 | 별도 프로세스·이미지가 필요하다. AGPL 프로그램을 함께 배포해야 한다(소스 제공 의무) |
| 내장 엔진만 | 설치가 단순하다(앱 하나). 배포물 전체가 퍼미시브 | 표·제목 추출 품질이 떨어질 수 있다(5절). 처리가 느리다 |
| **둘 다, 인터페이스로 고름 (제안)** | 환경에 맞게 고른다. 품질 비교가 쉽다. 두 앱이 엔진을 공유 | 계약(데이터 형식)을 지키는 시험이 필요하다 |

## 3. 인터페이스: ToolPDF API를 그대로 계약으로

새 형식을 만들지 않는다. **ToolPDF README(0.2.0)의 요청·응답 형식이 곧 인터페이스**다. 이미 앱의 에이전트들이 이 형식으로 동작하고, 테스트도 이 형식을 본다.

| 메서드 | 입력 | 출력 (ToolPDF README와 같음) |
|---|---|---|
| `health()` | | `{engine, version, libreoffice, ...}` |
| `capabilities()` | | 엔진이 하는 일과 못 하는 일(아래). ToolPDF는 `/v1/options`와 `health`에서 만든다 |
| `options_schema()` | | API별 옵션의 JSON Schema와 기본값(ToolPDF `GET /v1/options`와 같은 모양) |
| `info(src, options)` | | `{encrypted, page_count, pages}` |
| `text(src, limit, options)` | | 앞쪽 평문 |
| `profile(src, pages, options)` | | 쪽별 `features`(`text_chars`, `image_area_ratio`, `drawings`, `tables`, `table_text_share`, `size_hist` …) |
| `extract(src, pages, heading_min_size, figures…, options)` | | 쪽별 `elements`(title/text/table, bbox, content), `fallback`, `crops`(VLM용 이미지), `regions` |
| `render(src, page, dpi, fmt, clip, pad, highlight, options)` | | 이미지 바이트 |
| `normalize(src, filename, method, out, hints, xlsx…)` | | PDF 파일과 `hints`(docx 제목, 슬라이드 제목·노트·차트 데이터, 시트 행 수) |

- **옵션도 같은 이름:** `tables`(`strategy`, `snap_tolerance`, `text_tolerance`, `min_words_vertical` …), `image`(`jpeg_quality`, `colorspace`, `annots`, `crop_pad`, dpi), `document`(`password`). ToolPDF의 표 옵션 이름은 pdfplumber의 표 설정 이름과 같아서 내장 엔진에 거의 그대로 대응한다.
- **capabilities:** 엔진마다 못 하는 것이 있을 수 있다(예: 내장 엔진의 `lines_strict`, LibreOffice 없음). 앱은 계획을 세울 때 이것을 보고, 못 하는 기능은 대체하면서 **근거(`record_decision`)를 남긴다**. 지금 `engine_options_unsupported`를 남기는 것과 같은 방식이다.

```python
class PdfEngine(Protocol):
    name: str                     # "toolpdf" | "local"
    def health(self) -> dict: ...
    def capabilities(self) -> dict: ...      # {"modes": [...], "table_strategies": [...], "office": {...}, "password": bool, ...}
    def options_schema(self) -> dict: ...
    def info(self, src: Path, options: dict | None = None) -> dict: ...
    def text(self, src: Path, limit: int = 6000, options: dict | None = None) -> str: ...
    def profile(self, src: Path, pages: list[int] | None = None, options: dict | None = None) -> list[dict]: ...
    def extract(self, src: Path, pages: list[dict], heading_min_size: float | None, figures: dict, options: dict | None = None) -> dict[int, dict]: ...
    def render(self, src: Path, page: int, dpi: int, fmt: str = "png", clip=None, pad: float = 0, highlight=None, options=None) -> bytes: ...
    def normalize(self, src: Path, filename: str, method: str, out: Path, hints: bool = True, xlsx: dict | None = None) -> dict: ...
```

## 4. 어디에 두나: 이 저장소의 `backend/app/engines/` (결정)

처음 제안은 별도 저장소의 작은 MIT 패키지(가칭 `docengine`)였다. 결정(8절 1)에 따라 **당분간 이 저장소 안 `backend/app/engines/`**에 두고, 나머지 앱 코드를 import하지 않게 해서 나중에 그대로 떼어 낼 수 있게 한다(시험 `test_engine_package_imports_nothing_else_from_the_app`). 아래 표의 모듈 이름은 떼어 낼 때의 이름이고, 지금 위치는 9절에 있다.

| 모듈 | 내용 |
|---|---|
| `docengine.contract` | 요청·응답 형식(TypedDict), 옵션 모델(이름·범위·기본값), `capabilities` 형식 |
| `docengine.toolpdf` | ToolPDF HTTP 클라이언트. 지금 `backend/app/tools/toolpdf.py`를 옮기고 앱 설정 의존을 뺀다(주소, 키, 전달 방식은 생성자 인자) |
| `docengine.local` | 내장 엔진(6절). 쪽 처리는 프로세스 풀(ToolPDF의 `workers`와 같은 역할) |
| `docengine.conformance` | **어느 엔진이든 같은 시험**을 돌리는 pytest 모음과 시험 PDF. 형식은 정확히, 내용은 허용 범위로 비교 |
| `docengine.factory` | `make_engine("toolpdf" \| "local" \| "auto", ...)` |

- ToolPDF 저장소는 바뀌지 않는다. ToolPDF는 호출하는 쪽을 몰라야 한다는 규칙이 그대로 지켜진다. 이 패키지가 ToolPDF README를 따른다.
- 패키지에는 PyMuPDF 코드를 넣지 않는다. PyMuPDF는 ToolPDF 안에만 있다.

**앱 쪽 변경 (IngestLens):**
- `backend/app/tools/toolpdf.py`의 `engine()`이 `PdfEngine`을 돌려주게 한다. 에이전트 코드는 거의 그대로다(지금도 `engine().profile/extract/...`만 부른다).
- 설정 `RAG_PDF_ENGINE=toolpdf | local | auto`(auto: ToolPDF가 응답하면 ToolPDF, 아니면 내장). 고른 엔진과 이유를 근거에 남긴다.
- 상태 화면: 엔진 이름, 버전, 못 하는 기능.
- 규칙 화면의 "PDF 엔진 옵션": 엔진의 `options_schema()`로 검사하고, 그 엔진이 모르는 값은 표시만 하고 쓰지 않는다.
- 실행 근거에 엔진 이름·버전을 남긴다(같은 문서를 두 엔진으로 처리해 비교할 수 있게).

## 5. 품질 위험과 확인 방법

PyMuPDF를 퍼미시브 라이브러리로 바꾸면 다음이 다를 수 있다. 같은 문제를 이미 본 적이 있어 미리 시험으로 막는다.

| 위험 | 내용 | 막는 방법 |
|---|---|---|
| 표의 행 이름 열 손실 | 통계표 왼쪽의 행 이름("2019년 … 2024년")이 비고 숫자만 남음 | conformance에 그런 표를 넣고 칸 내용까지 비교 |
| 글자층 있는 스캔의 단어 쪼개짐 | 오래된 OCR 글자층이 단어마다 제목으로 잡혀 청크가 몇 배로 늘어남 | 제목 판정에 줄 단위 묶기, 청크 수·중앙값을 시험 지표로 |
| 그림 영역 | PyMuPDF `cluster_drawings`에 해당하는 기능이 없음 | 선·사각형·곡선을 직접 묶는 구현과 시험 |
| Office 자체 렌더링 | PyMuPDF Story(HTML→PDF) 대신 reportlab로 그림 → 레이아웃 차이 | `hints`(제목, 노트, 차트)는 원본에서 읽으므로 내용은 같게. 모양 차이는 허용 |
| 속도 | pdfminer 기반은 PyMuPDF보다 몇 배 느림 | 프로세스 풀, `bench_large.py`로 측정 |

평가: 같은 문서를 두 엔진으로 처리해 `scripts/eval_profile.py`, `eval_retrieval.py`, `eval_vlm.py` 결과와 청크 수를 나란히 본다. 내장 엔진의 기본값은 이 비교로 정한다.

## 6. 내장 엔진 구현 (라이브러리와 라이선스)

| 기능 | 라이브러리 | 라이선스 |
|---|---|---|
| 열기, 쪽 수, 암호, 렌더, 이미지 객체 | pypdfium2 (PDFium) | Apache-2.0 또는 BSD-3-Clause (PDFium BSD-3) |
| 글자·글꼴 크기·단어 위치, 선·사각형, 표 찾기(`lines`/`text`) | pdfplumber, pdfminer.six | MIT, MIT |
| 잘라내기, JPEG 품질, 흑백, 칠하기(highlight) | Pillow | MIT-CMU (HPND) |
| 이미지 → 한 쪽 PDF | Pillow(PDF 저장) | MIT-CMU |
| docx·pptx·xlsx 자체 렌더링 | python-docx, python-pptx, openpyxl + reportlab | MIT, MIT, MIT, BSD-3-Clause |
| doc·ppt·hwp | LibreOffice(설치돼 있으면 별도 프로세스) | MPL-2.0 (따로 실행, 링크 안 함) |
| 한글 글꼴(렌더링) | 나눔 글꼴 등 | SIL OFL 1.1 (함께 배포 가능, 고지 필요) |

**쓰지 않는 것:** PyMuPDF(AGPL), Ghostscript(AGPL), fpdf2·img2pdf(LGPL), pdf2image(MIT지만 GPL인 poppler 필요), camelot(Ghostscript 필요), WeasyPrint(시스템 LGPL 라이브러리). pikepdf(MPL-2.0)도 단순하게 하려고 쓰지 않는다.

**라이선스 지키기:** 패키지와 앱에 의존성 라이선스 검사(허용 목록)를 시험으로 넣는다. 새 의존성이 퍼미시브가 아니면 실패.

## 7. 단계

| 단계 | 할 일 | 끝났다는 기준 | 상태 |
|---|---|---|---|
| 0 | ToolPDF 0.2.0 옵션 연결 | 표 옵션이 쪽 분석·추출에 함께 감, 옛 엔진 대체, 시험 | 완료 |
| 1 | 인터페이스와 conformance 시험. ToolPDF 결과를 기준으로 | ToolPDF 클라이언트가 conformance를 통과 | 완료. 기준 정답 파일 대신 시험 때 띄우는 ToolPDF와 바로 비교 |
| 2 | ToolPDF 클라이언트를 엔진 패키지로 옮기고 앱이 `PdfEngine`을 쓰게 함. `RAG_PDF_ENGINE`, 상태 화면, 근거 | 앱 시험 전부 통과(두 전송 방식), 동작 변화 없음 | 완료 |
| 3 | 내장 엔진 1: `info`, `text`, `render`, `profile` | conformance의 해당 부분 통과 | 완료 |
| 4 | 내장 엔진 2: `extract`(제목·본문·표·그림 영역·잘라내기) | conformance 통과, 5절 위험 항목 시험 | 완료. 위험 1(행 이름 열)은 고침, 위험 2(OCR 글자층)는 남음(9절) |
| 5 | 내장 엔진 3: `normalize`(이미지, Office 자체 렌더링, LibreOffice) | Office 시험 통과, `hints` 같음 | 완료. 앱 시험 전체가 `RAG_PDF_ENGINE=local`로도 통과 |
| 6 | 두 엔진 비교 평가, 배포 묶음에 "ToolPDF 없는" 형태 추가 | 평가 결과를 HANDOFF 7절에, 묶음 시험 | 묶음 완료(WSL Docker에서 설치·처리 확인). 검색 평가(`eval_retrieval.py`) 비교는 남음 |
| 7 | 엔진 패키지를 별도 저장소로 떼어 다른 앱이 씀 | 그 앱에서 conformance와 앱 시험 통과 | 필요할 때 |

## 8. 결정 (2026-10-10)

1. **패키지 위치:** 당분간 이 저장소 안 `backend/app/engines/`. 앱의 다른 코드를 import하지 않게 해서 나중에 떼어 낸다.
2. **앱과 배포:** 앱은 나누지 않는다. **배포 형태만 둘**이다. ToolPDF와 함께(지금 묶음), ToolPDF 없이 내장 엔진만(`build_offline_bundle.py --pdf-engine local`, `setup_local.bat local`, `start_local.bat local`).
3. **기본 엔진:** `auto`. ToolPDF가 응답하면 ToolPDF, 아니면 내장 엔진. 실행마다 고른 엔진과 이유를 근거(`pdf_engine_auto`)로 남긴다.
4. **암호 PDF:** 지원한다. 업로드 때(`password` 폼 필드) 또는 나중에(`PUT /api/documents/{id}/password`, 실패한 실행 화면의 입력란) 받고, 두 엔진 모두 `options.document.password`로 연다.
5. **내장 엔진의 품질 목표:** 아직 숫자로 정하지 않았다. 9절의 비교로 시작한다. 실제 운영 문서로 `eval_retrieval.py`를 두 엔진으로 돌린 뒤 정한다.

## 9. 구현 결과 (2026-10-10)

**위치**

| 파일 | 내용 |
|---|---|
| `backend/app/engines/base.py` | `PdfEngine` 프로토콜, `EngineError`·`PasswordError`, 옵션 정의(`OPTION_SPEC`: 이름, 기본값, 범위)와 검사(`resolve_options`), `options_schema()`(ToolPDF `GET /v1/options`와 같은 모양) |
| `backend/app/engines/toolpdf.py` | ToolPDF HTTP 클라이언트(`ToolPDFEngine`). 403은 `PasswordError`. 0.1.x 엔진에는 예전 요청 |
| `backend/app/engines/local/` | 내장 엔진(`LocalEngine`): `pdf.py`(열기·암호·특징·표·요소·그림 영역·렌더), `office.py`(docx·pptx·xlsx 자체 렌더링과 hints), `pdfgen.py`(이미지 → PDF, 한글 글꼴) |
| `backend/app/tools/engine.py` | 앱 쪽 연결: `RAG_PDF_ENGINE` 선택(auto는 실행 시작 때 30초 간격으로 다시 확인), 규칙의 엔진 옵션, 문서 비밀번호(PDF 경로로 찾음), 파서 이름 → 추출 모드 |
| `backend/tests/test_engine_conformance.py` | 두 엔진에 같은 시험(21개): 형식, 쪽 라벨, 표 칸, 제목, 그림 영역, 렌더, 옵션 검사, 괘선 없는 표, 암호 PDF, 이미지·Office 변환 |
| `backend/tests/test_engine_select.py` | 선택(auto·toolpdf·local), 내장 엔진으로 전체 실행, API로 암호 PDF, 패키지 독립성, 의존성 라이선스 검사 |

**측정: 공개 문서 10개(`evals/samples`, 50쪽), 같은 규칙, VLM 없이**

| 항목 | ToolPDF 0.2.0 (PyMuPDF 1.28.2) | 내장 엔진 |
|---|---|---|
| 쪽 라벨(규칙 분류) | 기준 | **50쪽 모두 같음** |
| 표 수 | 20 | 20 (문서마다 같음) |
| 그림 영역 수 | 40 | 40 |
| 글자 수(요소 + 대체 텍스트) | 기준 | 대부분 ±3%. `ko_chart_kostat`은 73%(PyMuPDF가 병합 칸을 더 많이 채워 반복이 많음) |
| 제목·본문 요소 수 | 기준 | 일반 문서는 비슷(예: nist 5/50 대 7/43, docling 14/101 대 10/98). **오래된 OCR 글자층(`en_scan_naca1135`)은 제목이 588 대 149**: 단어마다 따로 블록이 된다 |
| 시간(쪽 분석 + 추출) | 문서당 0.3~3.4초 | 문서당 0.1~2.8초 (작은 문서, ToolPDF 프로세스 4개) |

맞추면서 바꾼 것:
- `drawings`(선 개수)는 PDFium의 경로 객체 수로 센다. pdfminer는 하위 경로가 여러 개인 경로를 조각마다 세서 로고가 있는 첫 쪽이 26~35개 많았고, 그 때문에 한 쪽이 `diagram`(기준 120)으로 바뀌었다. PDFium 수는 PyMuPDF와 거의 같다.
- 바깥 세로선이 없는 표: 가상 테두리를 넣는 행 높이 한도를 80pt에서 400pt로 올렸다. 행 하나에 여러 줄이 든 통계표에서 왼쪽 행 이름 열(전국, 서울 …)과 오른쪽 열을 잃었다(5절 위험 1).
- 글자 없는 격자(차트 눈금선)는 표가 아니다. 버리지 않으면 그 차트가 그림 영역에서 빠진다.
- 줄 묶기 `line_margin` 0.8(pdfminer 기본 0.5): 문단이 ToolPDF와 비슷하게 한 블록이 된다. `char_margin`은 2.0 그대로다. 3 이상이면 간격 11~17pt인 두 단이 한 줄로 붙는다.
- 같은 크기라도 떨어져 있는 제목 줄, 크기가 다른 제목 줄은 나눈다(문서 제목과 첫 절 제목).

**남은 차이와 할 일**
- 오래된 OCR 글자층의 단어 쪼개짐(5절 위험 2): 단 붙음 위험 없이 고칠 방법을 찾지 못했다. 그런 문서는 ToolPDF로 처리하거나 `vlm_ocr`로 다시 읽는다.
- 쪽 처리는 앱 프로세스의 스레드에서 돈다(PDFium 호출은 잠금으로 한 번에 하나). 큰 문서는 `bench_large.py`로 재고, 느리면 프로세스 풀을 붙인다.
- 내장 엔진의 Office 자체 렌더링은 ReportLab이라 모양이 ToolPDF(PyMuPDF Story)와 조금 다르다. hints(슬라이드 제목, 노트, 차트, 시트 행)는 같다(conformance 시험).
- `eval_vlm.py`의 데이터 세트 버전은 쪽 렌더의 해시라, 엔진이 다르면 버전도 다르다. 비교는 같은 엔진끼리 한다.
