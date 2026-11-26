# 전체 문서 검색 비교: 공개 문서 10종 + 합성 문서 2종 (전체 문서 검색)

질문 48개, 상위 5개. 정답 판정은 `scripts/eval_corpus.py` 맨 위 설명.

| 설정 | 시스템 | 임베딩 | 로더·청크 | 메모 |
|---|---|---|---|---|
| IngestLens 전체 문서 검색 | ingestlens | bge-m3 | IngestLens 파이프라인 | bge-m3(Ollama), VLM qwen2.5vl:7b(Ollama), ToolPDF 0.2.0, rerank 없음 |
| Open WebUI + IngestLens 로더 | openwebui | bge-m3 | external, 1024/100 | Open WebUI 0.13.3 패치, 문서는 IngestLens가 처리(청크 그대로), bge-m3(Ollama), hybrid BM25 0.5, rerank 없음 |
| Open WebUI 기본 로더 | openwebui | bge-m3 | default, 1024/100 | Open WebUI 0.13.3 기본 로더·분할(1024자/겹침 100), bge-m3(Ollama), hybrid BM25 0.5, rerank 없음 |
| Open WebUI 기본 로더 벡터만 | openwebui | bge-m3 | default, 1024/100 | 위와 같은 지식 베이스, hybrid 끔 |

| 지표 | IngestLens 전체 문서 검색 [dense] | IngestLens 전체 문서 검색 [lexical] | IngestLens 전체 문서 검색 [hybrid] | Open WebUI + IngestLens 로더 [hybrid] | Open WebUI 기본 로더 [hybrid] | Open WebUI 기본 로더 벡터만 [dense] |
|---|---|---|---|---|---|---|
| hit@1 | 73% | 62% | 75% | 73% | 88% | 88% |
| hit@5 | 92% | 92% | 90% | 92% | 100% | 100% |
| mrr | 0.81 | 0.74 | 0.81 | 0.81 | 0.93 | 0.93 |
| doc@1 | 90% | 92% | 85% | 90% | 94% | 94% |
| context_chars | 3,527 | 3,625 | 3,594 | 3,527 | 3,993 | 3,993 |
| ms_avg | 39 | 30 | 53 | 166 | 804 | 429 |

질문 종류별 hit@1 / hit@k:

| 종류 (개수) | IngestLens 전체 문서 검색 [dense] | IngestLens 전체 문서 검색 [lexical] | IngestLens 전체 문서 검색 [hybrid] | Open WebUI + IngestLens 로더 [hybrid] | Open WebUI 기본 로더 [hybrid] | Open WebUI 기본 로더 벡터만 [dense] |
|---|---|---|---|---|---|---|
| cross_doc (1) | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% | 100% / 100% |
| en_lexical (6) | 67% / 83% | 83% / 100% | 83% / 83% | 67% / 83% | 83% / 100% | 83% / 100% |
| en_paraphrase (4) | 100% / 100% | 50% / 100% | 100% / 100% | 100% / 100% | 75% / 100% | 75% / 100% |
| ko_lexical (13) | 77% / 100% | 77% / 100% | 85% / 100% | 77% / 100% | 92% / 100% | 92% / 100% |
| ko_paraphrase (15) | 80% / 100% | 60% / 100% | 80% / 100% | 80% / 100% | 93% / 100% | 93% / 100% |
| table (9) | 44% / 67% | 33% / 56% | 33% / 56% | 44% / 67% | 78% / 100% | 78% / 100% |

질문별 정답 순위(없으면 -):

| id | 질문 | IngestLens 전체 문서 검색 [dense] | IngestLens 전체 문서 검색 [lexical] | IngestLens 전체 문서 검색 [hybrid] | Open WebUI + IngestLens 로더 [hybrid] | Open WebUI 기본 로더 [hybrid] | Open WebUI 기본 로더 벡터만 [dense] |
|---|---|---|---|---|---|---|---|
| kostat-01 | 2025년 8월 출생아 수 | 2 | 1 | 1 | 2 | 1 | 1 |
| kostat-02 | 8월에 태어난 아기는 작년 같은 달보다 몇 명 늘었나 | 1 | 4 | 1 | 1 | 1 | 1 |
| kostat-03 | 2025년 8월 혼인 건수 | 2 | 1 | 1 | 2 | 1 | 1 |
| kostat-04 | 이혼이 늘어난 시도는 어디인가 | 1 | 1 | 1 | 1 | 1 | 1 |
| kostat-05 | 8월 사망자가 줄어든 지역은 몇 곳인가 | 5 | 2 | 3 | 5 | 1 | 1 |
| kostat-06 | 세종시 출생아 수 1~8월 누계 | 2 | - | 5 | 2 | 1 | 1 |
| table-01 | 2022년 연간 사망자 수 | - | - | - | - | 2 | 2 |
| table-02 | 2020년 자연증가 인구 | 4 | 3 | 3 | 4 | 1 | 1 |
| table-03 | 2024년 2분기 혼인 건수 | - | - | - | - | 4 | 4 |
| table-04 | 2019년 부산 출생아 수 | - | 5 | - | - | 1 | 1 |
| pop-01 | 인구가 처음으로 5천만 명을 넘어선 시점 | 2 | 1 | 1 | 2 | 1 | 1 |
| pop-02 | 2024년 합계출산율 | 4 | 2 | 2 | 4 | 2 | 2 |
| pop-03 | 1989년 대한민국 인구 밀도 | 1 | 1 | 1 | 1 | 1 | 1 |
| pop-04 | 1988년 서울의 인구 밀도는 1제곱킬로미터당 몇 명이었나 | 1 | 1 | 1 | 1 | 1 | 1 |
| palace-01 | 경복궁은 언제 누가 처음 지었나 | 1 | 4 | 2 | 1 | 1 | 1 |
| palace-02 | 광화문 천장에 그려진 그림 | 1 | 1 | 1 | 1 | 1 | 1 |
| palace-03 | 영제교의 길이와 너비 | 1 | 1 | 1 | 1 | 1 | 1 |
| palace-04 | 근정전의 국보 지정 번호 | 1 | 2 | 2 | 1 | 1 | 1 |
| palace-05 | 가을을 맞이한다는 뜻을 가진 궁궐 문 | 1 | 1 | 1 | 1 | 1 | 1 |
| seoul-01 | 서울특별시의 면적 | 1 | 4 | 1 | 1 | 1 | 1 |
| seoul-02 | 서울에서 관측된 가장 더운 날의 기온 | 2 | 2 | 1 | 2 | 1 | 1 |
| seoul-03 | 서울 연평균 강수량 | 1 | 1 | 1 | 1 | 1 | 1 |
| seoul-04 | 서울 화강암은 얼마나 오래된 암석인가 | 1 | 1 | 1 | 1 | 1 | 1 |
| seoul-05 | 서울 인구가 천만 명 아래로 떨어진 때 | 1 | 1 | 1 | 1 | 1 | 1 |
| seoul-06 | 1970년 서울 출생아 수 | 1 | - | - | 1 | 1 | 1 |
| hangul-01 | 훈민정음 반포 시기 | 1 | 1 | 1 | 1 | 1 | 1 |
| hangul-02 | 해례본이 처음 발견된 곳과 해 | 1 | 2 | 1 | 1 | 5 | 5 |
| hangul-03 | 전형필이 해례본을 사는 데 치른 값 | 1 | 1 | 1 | 1 | 1 | 1 |
| hangul-04 | 상주본을 기증하는 대가로 요구한 금액 | 1 | 1 | 1 | 1 | 1 | 1 |
| hangul-05 | 지금은 쓰지 않는 옛 한글 자모 | 1 | 1 | 1 | 1 | 1 | 1 |
| nist-01 | What do PDP and PEP stand for? | - | 4 | - | - | 2 | 2 |
| nist-02 | Which real-world analogy explains the implicit trust zone? | 1 | 2 | 1 | 1 | 2 | 2 |
| nist-03 | How does a laptop reach an HR database through the local agent and gateway? | 1 | 1 | 1 | 1 | 1 | 1 |
| nist-04 | Why is a portal-based deployment exposed to attacks? | 1 | 1 | 1 | 1 | 1 | 1 |
| nist-05 | trust algorithm of the policy engine | 1 | 1 | 1 | 1 | 1 | 1 |
| docling-01 | Which OCR library does Docling use? | 1 | 1 | 1 | 1 | 1 | 1 |
| docling-02 | How long does table structure recognition take per table on a CPU? | 1 | 2 | 1 | 1 | 1 | 1 |
| docling-03 | Docling pages per second on Apple M3 Max | 1 | 1 | 1 | 1 | 1 | 1 |
| docling-04 | image resolution given to the OCR engine | 1 | 1 | 1 | 1 | 1 | 1 |
| docling-05 | What is the name of the table structure model? | 1 | 1 | 1 | 1 | 1 | 1 |
| naca-01 | report on equations, tables and charts for compressible flow by Ames | 2 | 1 | 1 | 2 | 1 | 1 |
| manual-01 | 냉각수 온도 유지 범위 | 1 | 1 | 1 | 1 | 1 | 1 |
| manual-02 | 전기가 끊기면 장비가 얼마나 버티나 | 1 | 4 | 2 | 1 | 1 | 1 |
| manual-03 | E-305 알람의 의미 | 1 | 1 | 1 | 1 | 1 | 1 |
| manual-04 | 배기 필터는 얼마마다 바꾸나 | 1 | 1 | 1 | 1 | 1 | 1 |
| manual-05 | 2분기 가동률이 낮았던 이유 | 1 | 1 | 1 | 1 | 1 | 1 |
| guide-01 | 설치하기 전에 준비할 물건 | 1 | 1 | 1 | 1 | 1 | 1 |
| guide-02 | 진동 점검 주기와 기준 | 1 | 1 | 1 | 1 | 1 | 1 |

## 해석 (2026-11-26)

환경: 이 PC의 WSL Docker. IngestLens(이 저장소 코드, ToolPDF 0.2.0, VLM `qwen2.5vl:7b`)와 Open WebUI 0.13.3 두 개(기본 로더 / IngestLens 로더 + 패치)가 같은 Ollama `bge-m3`를 쓴다. rerank는 모두 없음. 질문은 사람이 원문을 보고 만든 48개라 수가 적다(1문항 = 2%p).

- **Open WebUI 기본 로더가 더 잘 찾았다**(hit@1 88% / hit@5 100% 대 IngestLens hybrid 75% / 90%). 정답 문구는 IngestLens 청크에도 모두 들어 있었다(빠뜨린 것 0개). 차이는 처리에서 잃어서가 아니라 **청크 모양 때문에 순위가 밀린 것**이다.
- 가장 큰 차이는 **표 질문**(9개: 33% 대 78%). 통계표(국가데이터처 통계표)는 행 사이에 선이 없어, 표 추출이 한 칸에 여러 해의 값을 `<br>`로 쌓는다(`|2019년<br>2020년<br>…|302,676<br>272,337<br>…|`). 연도와 값의 짝이 깨지고 머리 행은 `Col1|Col3…`이 된다. Open WebUI 기본 로더는 글자층을 줄 그대로 읽어 `2022년 249,186 372,939 …`가 한 줄로 남는다.
- NIST 문서는 옆 여백의 세로 글자(`C O M P U T E R S E C U R I T Y`, `This publication is available free of charge from …`)가 청크마다 앞에 붙는다. 쪽마다 반복되는 머리글·여백 글자를 빼지 않는다.
- 낡은 스캔(NACA 1135)의 OCR 글자층이 1~3글자짜리 청크 156개로 쪼개져 다른 문서 검색에 잡음이 된다(알려진 함정, HANDOFF 6절).
- IngestLens의 hybrid(RRF)는 BM25가 dense 1위를 2위로 내리는 경우가 있었다(경복궁 2건, 매뉴얼 1건). Open WebUI 0.13.3의 hybrid는 reranker가 없으면 hybrid로 뽑은 상위 k개를 다시 **임베딩 유사도로 정렬**해서, 이 세트에서는 벡터만과 결과가 같았다.
- Open WebUI에 IngestLens 로더를 붙이면 IngestLens dense와 거의 같다(73% / 92%). 청크가 같고 검색 방식이 비슷하기 때문이다.
- 속도: IngestLens 검색 30~53ms, Open WebUI 430~800ms(질의당, 같은 PC).
- IngestLens가 앞선 곳: 스캔 문서(Open WebUI 기본 로더는 `ko_scan_kostat.pdf`의 글자를 못 읽어 처리 실패), 영어 바꿔 쓴 질문(100% 대 75%).

개선 후보(다시 재서 비교한다): ① 선 없는 표에서 쌓인 칸을 행으로 나누기 ② 쪽마다 반복되는 머리글·여백 글자 빼기 ③ 아주 짧은 OCR 조각 합치거나 버리기 ④ hybrid 가중치(dense 쪽)나 rerank.
