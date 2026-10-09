# PDF 엔진 인터페이스 계획: ToolPDF와 MIT 내장 엔진

작성 2026-10-10. 상태: **계획**(아직 구현하지 않음). 결정이 필요한 것은 8절에 모았다.

## 1. 목표

- 지금 IngestLens는 모든 PDF 작업을 별도 프로그램 ToolPDF(AGPL-3.0, PyMuPDF)에 HTTP로 맡긴다.
- 앞으로 **ToolPDF 없이도** 같은 기능을 쓰고 싶다. 앱 안에서 도는 내장 엔진을 MIT·BSD·Apache 같은 퍼미시브 라이선스 라이브러리로만 만든다.
- 곧 MIT 라이선스로 같은 기능의 앱을 하나 더 만들 예정이다. 그 앱과 이 앱이 **같은 엔진 인터페이스**를 쓰게 해서 엔진을 한 번만 만든다.

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

## 4. 어디에 두나: 별도 MIT 패키지 (제안)

두 앱이 함께 쓰므로 앱 저장소 밖의 **작은 MIT 패키지**(가칭 `docengine`, 별도 저장소)로 만든다.

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

| 단계 | 할 일 | 끝났다는 기준 |
|---|---|---|
| 0 | 이번 작업: ToolPDF 0.2.0 옵션 연결(완료, 2026-10-10) | 표 옵션이 쪽 분석·추출에 함께 감, 옛 엔진 대체, 시험 |
| 1 | 인터페이스와 conformance 시험. 지금 ToolPDF 결과를 기준 정답으로 저장 | ToolPDF 클라이언트가 conformance를 통과 |
| 2 | `docengine` 패키지로 ToolPDF 클라이언트를 옮기고 앱이 `PdfEngine`을 쓰게 함. `RAG_PDF_ENGINE`, 상태 화면, 근거 | 앱 시험 전부 통과(두 전송 방식), 동작 변화 없음 |
| 3 | 내장 엔진 1: `info`, `text`, `render`, `profile` | conformance의 해당 부분 통과 |
| 4 | 내장 엔진 2: `extract`(제목·본문·표·그림 영역·잘라내기) | conformance 통과, 5절 위험 항목 시험 통과 |
| 5 | 내장 엔진 3: `normalize`(이미지, Office 자체 렌더링, LibreOffice) | Office 시험 통과, `hints` 같음 |
| 6 | 두 엔진 비교 평가와 기본값 결정, 배포 묶음에 "ToolPDF 없는" 형태 추가 | 평가 결과를 HANDOFF 7절에, 묶음 시험 |
| 7 | 다른 MIT 앱이 `docengine`을 씀 | 그 앱에서 conformance와 앱 시험 통과 |

## 8. 정할 것

1. **패키지 이름과 저장소:** 가칭 `docengine`, 별도 저장소(MIT). 아니면 당분간 이 저장소 안 `backend/app/engines/`에 두고 나중에 떼어 낼지.
2. **두 앱의 관계:** 내장 엔진이 생기면 이 앱(IngestLens-v2)을 `RAG_PDF_ENGINE=local`로 띄우는 것만으로 ToolPDF 없는 MIT 배포가 된다. 그러면 MIT 앱을 따로 만들지 않고 **코드 하나에 배포 형태만 둘**로 할 수도 있다. 앱을 따로 둘 이유(화면, 기능 차이)가 있는지 정한다.
3. **기본 엔진:** `auto`(ToolPDF가 있으면 ToolPDF)로 할지, 명시하게 할지.
4. **내장 엔진의 품질 목표:** ToolPDF와 같은 평가 세트에서 몇 % 이내면 받아들일지.
5. **암호 PDF:** 문서마다 비밀번호를 받을 화면·API(업로드 때 입력, 실행 때 전달)를 만들지. 두 엔진 모두 지원할 수 있다.
