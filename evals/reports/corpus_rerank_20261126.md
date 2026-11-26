# 전체 문서 검색 비교: 공개 문서 10종 + 합성 문서 2종 (전체 문서 검색)

질문 48개, 상위 5개. 정답 판정은 `scripts/eval_corpus.py` 맨 위 설명.

| 설정 | 시스템 | 임베딩 | 로더·청크 | 메모 |
|---|---|---|---|---|
| IngestLens rerank | ingestlens | bge-m3 | IngestLens 파이프라인 | 표 행 나누기 포함. bge-m3(Ollama), VLM qwen2.5vl:7b, ToolPDF 0.2.0, rerank bge-reranker-v2-m3(모델 서버 GPU), 후보 15 |
| IngestLens rerank 후보 40 | ingestlens | bge-m3 | IngestLens 파이프라인 | 위와 같음, reranker.candidates 40 |
| Open WebUI 기본 로더 | openwebui | bge-m3 | default, 1024/100 | Open WebUI 0.13.3 기본 로더·분할(1024자/겹침 100), bge-m3(Ollama), hybrid BM25 0.5, rerank 없음 |
| Open WebUI 기본 rerank | openwebui | bge-m3 | default, 1024/100 | Open WebUI 0.13.3 기본 로더·분할(1024자/겹침 100), bge-m3(Ollama), hybrid BM25 0.5, rerank bge-reranker-v2-m3(같은 모델 서버), 후보 15 |

| 지표 | IngestLens rerank [dense] | IngestLens rerank [hybrid] | IngestLens rerank [rerank] | IngestLens rerank 후보 40 [rerank] | Open WebUI 기본 로더 [hybrid] | Open WebUI 기본 rerank [hybrid+rerank] |
|---|---|---|---|---|---|---|
| hit@1 | 73% | 75% | 88% | 88% | 88% | 94% |
| hit@5 | 92% | 90% | 94% | 94% | 100% | 100% |
| mrr | 0.81 | 0.81 | 0.90 | 0.90 | 0.93 | 0.96 |
| doc@1 | 90% | 85% | 90% | 90% | 94% | 96% |
| context_chars | 3,568 | 3,736 | 4,113 | 4,259 | 3,993 | 4,231 |
| ms_avg | 46 | 41 | 165 | 376 | 804 | 754 |

질문 종류별 hit@1 / hit@k:

| 종류 (개수) | IngestLens rerank [dense] | IngestLens rerank [hybrid] | IngestLens rerank [rerank] | IngestLens rerank 후보 40 [rerank] | Open WebUI 기본 로더 [hybrid] | Open WebUI 기본 rerank [hybrid+rerank] |
|---|---|---|---|---|---|---|
| cross_doc (1) | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% |
| en_lexical (6) | 67% / 83% | 83% / 83% | 83% / 100% | 83% / 100% | 83% / 100% | 100% / 100% |
| en_paraphrase (4) | 100% / 100% | 75% / 100% | 100% / 100% | 100% / 100% | 75% / 100% | 100% / 100% |
| ko_lexical (13) | 77% / 100% | 92% / 100% | 100% / 100% | 100% / 100% | 92% / 100% | 100% / 100% |
| ko_paraphrase (15) | 80% / 100% | 80% / 100% | 100% / 100% | 100% / 100% | 93% / 100% | 100% / 100% |
| table (9) | 44% / 67% | 33% / 56% | 44% / 67% | 44% / 67% | 78% / 100% | 67% / 100% |

질문별 정답 순위(없으면 -):

| id | 질문 | IngestLens rerank [dense] | IngestLens rerank [hybrid] | IngestLens rerank [rerank] | IngestLens rerank 후보 40 [rerank] | Open WebUI 기본 로더 [hybrid] | Open WebUI 기본 rerank [hybrid+rerank] |
|---|---|---|---|---|---|---|---|
| kostat-01 | 2025년 8월 출생아 수 | 2 | 1 | 1 | 1 | 1 | 1 |
| kostat-02 | 8월에 태어난 아기는 작년 같은 달보다 몇 명 늘었나 | 1 | 1 | 1 | 1 | 1 | 1 |
| kostat-03 | 2025년 8월 혼인 건수 | 2 | 1 | 1 | 1 | 1 | 1 |
| kostat-04 | 이혼이 늘어난 시도는 어디인가 | 1 | 1 | 1 | 1 | 1 | 1 |
| kostat-05 | 8월 사망자가 줄어든 지역은 몇 곳인가 | 5 | 3 | 1 | 1 | 1 | 1 |
| kostat-06 | 세종시 출생아 수 1~8월 누계 | 2 | 4 | 1 | 1 | 1 | 1 |
| table-01 | 2022년 연간 사망자 수 | - | - | - | - | 2 | 4 |
| table-02 | 2020년 자연증가 인구 | 2 | 3 | 4 | 5 | 1 | 1 |
| table-03 | 2024년 2분기 혼인 건수 | - | - | - | - | 4 | 3 |
| table-04 | 2019년 부산 출생아 수 | - | - | - | - | 1 | 2 |
| pop-01 | 인구가 처음으로 5천만 명을 넘어선 시점 | 2 | 1 | 1 | 1 | 1 | 1 |
| pop-02 | 2024년 합계출산율 | 4 | 2 | 1 | 1 | 2 | 1 |
| pop-03 | 1989년 대한민국 인구 밀도 | 1 | 1 | 1 | 1 | 1 | 1 |
| pop-04 | 1988년 서울의 인구 밀도는 1제곱킬로미터당 몇 명이었나 | 1 | 1 | 1 | 1 | 1 | 1 |
| palace-01 | 경복궁은 언제 누가 처음 지었나 | 1 | 2 | 1 | 1 | 1 | 1 |
| palace-02 | 광화문 천장에 그려진 그림 | 1 | 1 | 1 | 1 | 1 | 1 |
| palace-03 | 영제교의 길이와 너비 | 1 | 1 | 1 | 1 | 1 | 1 |
| palace-04 | 근정전의 국보 지정 번호 | 1 | 1 | 1 | 1 | 1 | 1 |
| palace-05 | 가을을 맞이한다는 뜻을 가진 궁궐 문 | 1 | 1 | 1 | 1 | 1 | 1 |
| seoul-01 | 서울특별시의 면적 | 1 | 1 | 1 | 1 | 1 | 1 |
| seoul-02 | 서울에서 관측된 가장 더운 날의 기온 | 2 | 1 | 1 | 1 | 1 | 1 |
| seoul-03 | 서울 연평균 강수량 | 1 | 1 | 1 | 1 | 1 | 1 |
| seoul-04 | 서울 화강암은 얼마나 오래된 암석인가 | 1 | 1 | 1 | 1 | 1 | 1 |
| seoul-05 | 서울 인구가 천만 명 아래로 떨어진 때 | 1 | 1 | 1 | 1 | 1 | 1 |
| seoul-06 | 1970년 서울 출생아 수 | 1 | - | 2 | 2 | 1 | 1 |
| hangul-01 | 훈민정음 반포 시기 | 1 | 1 | 1 | 1 | 1 | 1 |
| hangul-02 | 해례본이 처음 발견된 곳과 해 | 1 | 1 | 1 | 1 | 5 | 1 |
| hangul-03 | 전형필이 해례본을 사는 데 치른 값 | 1 | 1 | 1 | 1 | 1 | 1 |
| hangul-04 | 상주본을 기증하는 대가로 요구한 금액 | 1 | 1 | 1 | 1 | 1 | 1 |
| hangul-05 | 지금은 쓰지 않는 옛 한글 자모 | 1 | 1 | 1 | 1 | 1 | 1 |
| nist-01 | What do PDP and PEP stand for? | - | - | 3 | 3 | 2 | 1 |
| nist-02 | Which real-world analogy explains the implicit trust zone? | 1 | 2 | 1 | 1 | 2 | 1 |
| nist-03 | How does a laptop reach an HR database through the local agent and gateway? | 1 | 1 | 1 | 1 | 1 | 1 |
| nist-04 | Why is a portal-based deployment exposed to attacks? | 1 | 1 | 1 | 1 | 1 | 1 |
| nist-05 | trust algorithm of the policy engine | 1 | 1 | 1 | 1 | 1 | 1 |
| docling-01 | Which OCR library does Docling use? | 1 | 1 | 1 | 1 | 1 | 1 |
| docling-02 | How long does table structure recognition take per table on a CPU? | 1 | 1 | 1 | 1 | 1 | 1 |
| docling-03 | Docling pages per second on Apple M3 Max | 1 | 1 | 1 | 1 | 1 | 1 |
| docling-04 | image resolution given to the OCR engine | 1 | 1 | 1 | 1 | 1 | 1 |
| docling-05 | What is the name of the table structure model? | 1 | 1 | 1 | 1 | 1 | 1 |
| naca-01 | report on equations, tables and charts for compressible flow by Ames | 2 | 1 | 1 | 1 | 1 | 1 |
| manual-01 | 냉각수 온도 유지 범위 | 1 | 1 | 1 | 1 | 1 | 1 |
| manual-02 | 전기가 끊기면 장비가 얼마나 버티나 | 1 | 2 | 1 | 1 | 1 | 1 |
| manual-03 | E-305 알람의 의미 | 1 | 1 | 1 | 1 | 1 | 1 |
| manual-04 | 배기 필터는 얼마마다 바꾸나 | 1 | 1 | 1 | 1 | 1 | 1 |
| manual-05 | 2분기 가동률이 낮았던 이유 | 1 | 1 | 1 | 1 | 1 | 1 |
| guide-01 | 설치하기 전에 준비할 물건 | 1 | 1 | 1 | 1 | 1 | 1 |
| guide-02 | 진동 점검 주기와 기준 | 1 | 1 | 1 | 1 | 1 | 1 |

## 해석 (2026-11-26)

같은 환경(IngestLens는 표 행 나누기 포함)에 운영과 같은 reranker `bge-reranker-v2-m3`(운영 모델 서버 이미지, GPU)를 붙이고 양쪽을 다시 쟀다. IngestLens는 hybrid 후보 상위 15개(기본: 상위 k의 3배)를, Open WebUI는 `RAG_TOP_K=15` 후보에서 `RAG_TOP_K_RERANKER=5`를 rerank했다.

- **rerank가 가장 큰 개선이다**: IngestLens hit@1 75% → **88%**, MRR 0.81 → 0.90. Open WebUI 기본도 88% → 94%.
- IngestLens는 rerank를 켜면 **표가 아닌 질문 39개 중 38개를 1위**로 찾는다(한국어 그대로·바꿔 쓴 질문, 영어 바꿔 쓴 질문 100%). 1위를 놓친 것은 표 질문 5개와 NIST 1개다.
- 표 질문: 정답 표 청크가 후보에 들어도 reranker가 문장 청크보다 낮게 본다. 후보를 40개로 늘려도(`reranker.candidates: 40`) 수치는 같고 시간만 165ms → 376ms가 됐다. IngestLens 표 청크는 약 500토큰에 행이 많아 물은 해의 행이 묻힌다. Open WebUI 기본은 1,024자 조각이라 해가 몇 개만 들어 있다.
- NIST(`PDP`, `PEP`): 쪽 옆 여백의 세로 글자가 청크마다 붙어 있다.
- 속도: IngestLens rerank 165ms, Open WebUI rerank 754ms(질의당).

다음 후보: ① 표 청크를 작게(행 수 제한, 머리 행 반복은 그대로) ② 쪽마다 반복되는 머리글·옆 여백 글자 빼기 ③ 운영 문서로 만든 세트로 다시 재기.
