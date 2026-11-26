# 전체 문서 검색 비교: 공개 문서 10종 + 합성 문서 2종 (전체 문서 검색)

질문 48개, 상위 5개. 정답 판정은 `scripts/eval_corpus.py` 맨 위 설명.

| 설정 | 시스템 | 임베딩 | 로더·청크 | 메모 |
|---|---|---|---|---|
| IngestLens 전체 문서 검색 | ingestlens | bge-m3 | IngestLens 파이프라인 | bge-m3(Ollama), VLM qwen2.5vl:7b(Ollama), ToolPDF 0.2.0, rerank 없음 |
| IngestLens 표 행 나누기 | ingestlens | bge-m3 | IngestLens 파이프라인 | 표 행 나누기(table_unstack) 적용. bge-m3(Ollama), VLM qwen2.5vl:7b(Ollama), ToolPDF 0.2.0, rerank 없음 |
| Open WebUI 기본 로더 | openwebui | bge-m3 | default, 1024/100 | Open WebUI 0.13.3 기본 로더·분할(1024자/겹침 100), bge-m3(Ollama), hybrid BM25 0.5, rerank 없음 |

| 지표 | IngestLens 전체 문서 검색 [dense] | IngestLens 전체 문서 검색 [lexical] | IngestLens 전체 문서 검색 [hybrid] | IngestLens 표 행 나누기 [dense] | IngestLens 표 행 나누기 [lexical] | IngestLens 표 행 나누기 [hybrid] | Open WebUI 기본 로더 [hybrid] |
|---|---|---|---|---|---|---|---|
| hit@1 | 73% | 62% | 75% | 73% | 62% | 75% | 88% |
| hit@5 | 92% | 92% | 90% | 92% | 92% | 90% | 100% |
| mrr | 0.81 | 0.74 | 0.81 | 0.81 | 0.73 | 0.81 | 0.93 |
| doc@1 | 90% | 92% | 85% | 90% | 90% | 85% | 94% |
| context_chars | 3,527 | 3,625 | 3,594 | 3,568 | 3,717 | 3,719 | 3,993 |
| ms_avg | 39 | 30 | 53 | 39 | 18 | 37 | 804 |

질문 종류별 hit@1 / hit@k:

| 종류 (개수) | IngestLens 전체 문서 검색 [dense] | IngestLens 전체 문서 검색 [lexical] | IngestLens 전체 문서 검색 [hybrid] | IngestLens 표 행 나누기 [dense] | IngestLens 표 행 나누기 [lexical] | IngestLens 표 행 나누기 [hybrid] | Open WebUI 기본 로더 [hybrid] |
|---|---|---|---|---|---|---|---|
| cross_doc (1) | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% |
| en_lexical (6) | 67% / 83% | 83% / 100% | 83% / 83% | 67% / 83% | 83% / 100% | 83% / 83% | 83% / 100% |
| en_paraphrase (4) | 100% / 100% | 50% / 100% | 100% / 100% | 100% / 100% | 50% / 100% | 75% / 100% | 75% / 100% |
| ko_lexical (13) | 77% / 100% | 77% / 100% | 85% / 100% | 77% / 100% | 77% / 92% | 92% / 100% | 92% / 100% |
| ko_paraphrase (15) | 80% / 100% | 60% / 100% | 80% / 100% | 80% / 100% | 60% / 100% | 80% / 100% | 93% / 100% |
| table (9) | 44% / 67% | 33% / 56% | 33% / 56% | 44% / 67% | 33% / 67% | 33% / 56% | 78% / 100% |

질문별 정답 순위(없으면 -):

| id | 질문 | IngestLens 전체 문서 검색 [dense] | IngestLens 전체 문서 검색 [lexical] | IngestLens 전체 문서 검색 [hybrid] | IngestLens 표 행 나누기 [dense] | IngestLens 표 행 나누기 [lexical] | IngestLens 표 행 나누기 [hybrid] | Open WebUI 기본 로더 [hybrid] |
|---|---|---|---|---|---|---|---|---|
| kostat-01 | 2025년 8월 출생아 수 | 2 | 1 | 1 | 2 | 1 | 1 | 1 |
| kostat-02 | 8월에 태어난 아기는 작년 같은 달보다 몇 명 늘었나 | 1 | 4 | 1 | 1 | 5 | 1 | 1 |
| kostat-03 | 2025년 8월 혼인 건수 | 2 | 1 | 1 | 2 | 1 | 1 | 1 |
| kostat-04 | 이혼이 늘어난 시도는 어디인가 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| kostat-05 | 8월 사망자가 줄어든 지역은 몇 곳인가 | 5 | 2 | 3 | 5 | 2 | 3 | 1 |
| kostat-06 | 세종시 출생아 수 1~8월 누계 | 2 | - | 5 | 2 | - | 4 | 1 |
| table-01 | 2022년 연간 사망자 수 | - | - | - | - | - | - | 2 |
| table-02 | 2020년 자연증가 인구 | 4 | 3 | 3 | 2 | 5 | 3 | 1 |
| table-03 | 2024년 2분기 혼인 건수 | - | - | - | - | 4 | - | 4 |
| table-04 | 2019년 부산 출생아 수 | - | 5 | - | - | 5 | - | 1 |
| pop-01 | 인구가 처음으로 5천만 명을 넘어선 시점 | 2 | 1 | 1 | 2 | 1 | 1 | 1 |
| pop-02 | 2024년 합계출산율 | 4 | 2 | 2 | 4 | 2 | 2 | 2 |
| pop-03 | 1989년 대한민국 인구 밀도 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| pop-04 | 1988년 서울의 인구 밀도는 1제곱킬로미터당 몇 명이었나 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| palace-01 | 경복궁은 언제 누가 처음 지었나 | 1 | 4 | 2 | 1 | 4 | 2 | 1 |
| palace-02 | 광화문 천장에 그려진 그림 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| palace-03 | 영제교의 길이와 너비 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| palace-04 | 근정전의 국보 지정 번호 | 1 | 2 | 2 | 1 | 2 | 1 | 1 |
| palace-05 | 가을을 맞이한다는 뜻을 가진 궁궐 문 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| seoul-01 | 서울특별시의 면적 | 1 | 4 | 1 | 1 | - | 1 | 1 |
| seoul-02 | 서울에서 관측된 가장 더운 날의 기온 | 2 | 2 | 1 | 2 | 2 | 1 | 1 |
| seoul-03 | 서울 연평균 강수량 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| seoul-04 | 서울 화강암은 얼마나 오래된 암석인가 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| seoul-05 | 서울 인구가 천만 명 아래로 떨어진 때 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| seoul-06 | 1970년 서울 출생아 수 | 1 | - | - | 1 | - | - | 1 |
| hangul-01 | 훈민정음 반포 시기 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| hangul-02 | 해례본이 처음 발견된 곳과 해 | 1 | 2 | 1 | 1 | 2 | 1 | 5 |
| hangul-03 | 전형필이 해례본을 사는 데 치른 값 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| hangul-04 | 상주본을 기증하는 대가로 요구한 금액 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| hangul-05 | 지금은 쓰지 않는 옛 한글 자모 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| nist-01 | What do PDP and PEP stand for? | - | 4 | - | - | 4 | - | 2 |
| nist-02 | Which real-world analogy explains the implicit trust zone? | 1 | 2 | 1 | 1 | 2 | 2 | 2 |
| nist-03 | How does a laptop reach an HR database through the local agent and gateway? | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| nist-04 | Why is a portal-based deployment exposed to attacks? | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| nist-05 | trust algorithm of the policy engine | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| docling-01 | Which OCR library does Docling use? | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| docling-02 | How long does table structure recognition take per table on a CPU? | 1 | 2 | 1 | 1 | 2 | 1 | 1 |
| docling-03 | Docling pages per second on Apple M3 Max | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| docling-04 | image resolution given to the OCR engine | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| docling-05 | What is the name of the table structure model? | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| naca-01 | report on equations, tables and charts for compressible flow by Ames | 2 | 1 | 1 | 2 | 1 | 1 | 1 |
| manual-01 | 냉각수 온도 유지 범위 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| manual-02 | 전기가 끊기면 장비가 얼마나 버티나 | 1 | 4 | 2 | 1 | 4 | 2 | 1 |
| manual-03 | E-305 알람의 의미 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| manual-04 | 배기 필터는 얼마마다 바꾸나 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| manual-05 | 2분기 가동률이 낮았던 이유 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| guide-01 | 설치하기 전에 준비할 물건 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| guide-02 | 진동 점검 주기와 기준 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |

## 해석 (2026-11-26)

표 행 나누기(`tools/tables.py`, 근거 `table_unstack`)를 넣고 같은 환경에서 IngestLens만 다시 쟀다. 통계표 문서에서 표 4개, 보도자료 문서에서 5개를 고쳤다(`|2022년|249,186|372,939|…`처럼 한 행씩, 머리 행 `인구동태건수 사망`).

- **검색 수치는 거의 그대로다**(hybrid hit@1 75% → 75%, 표 질문 순위 변화 없음). 바뀐 질문은 몇 개뿐이고 오르내림이 섞였다.
- 정답 표 청크는 dense 8~17위, BM25 4~20위에 있다. 1위는 같은 보도자료의 문장 청크("2025년 8월 사망자 수는 …")다. bge-m3 유사도: 질문과 표 청크 0.52~0.60, 1위 문장 청크 0.61~0.70. 같은 표를 Markdown 대신 평문(칸을 공백으로)으로 바꿔도 0.01~0.045만 오른다.
- 그래서 표 모양을 고치는 것만으로는 순위가 오르지 않는다. 그래도 고친 표는 LLM이 읽을 때 연도와 값이 맞게 짝지어지므로 답의 정확도에는 도움이 된다(이 세트는 검색만 잰다).
- Open WebUI 기본 로더가 표 질문을 찾는 이유: 1,024자 평문 조각에 쪽 제목, 머리말, 연도 6개만 들어 있어 짧고 초점이 좁다. IngestLens 표 청크는 약 500토큰으로 행이 더 많다.

다음 후보: ① reranker를 켜고 양쪽을 다시 잰다(운영은 bge-reranker-v2-m3를 쓴다. 숫자와 연도 맞추기는 cross-encoder가 낫다) ② 표 청크를 더 작게(행 수 제한) ③ 임베딩할 때만 표를 평문으로.
