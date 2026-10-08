# Retrieval evaluation (2026-10-04)

- models: `config/models.docker.yaml` 를 호스트 포트(Ollama 11435, reranker 8081)로 바꾼 사본. VLM `qwen2.5vl:7b`, 임베딩 `bge-m3` (Ollama 0.35, RTX 5070 Ti), reranker `BAAI/bge-reranker-v2-m3` (CPU)
- k = 5

## Documents

| file | chunks | embedding | chars/token | ingest s |
|---|---|---|---|---|
| manual.pdf | 17 | bge-m3 | 2.5 | 32.3 |
| deck.pptx | 5 | bge-m3 | 2.5 | 4.4 |
| guide.docx | 6 | bge-m3 | 2.5 | 0.6 |
| sheet.xlsx | 8 | bge-m3 | 2.5 | 7.1 |

## Metrics

| mode | query kind | n | hit@1 | hit@5 | MRR |
|---|---|---|---|---|---|
| dense | all | 22 | 95% | 100% | 0.98 |
| dense | lexical | 14 | 100% | 100% | 1.00 |
| dense | paraphrase | 8 | 88% | 100% | 0.94 |
| lexical | all | 22 | 82% | 91% | 0.86 |
| lexical | lexical | 14 | 100% | 100% | 1.00 |
| lexical | paraphrase | 8 | 50% | 75% | 0.60 |
| hybrid | all | 22 | 82% | 95% | 0.89 |
| hybrid | lexical | 14 | 100% | 100% | 1.00 |
| hybrid | paraphrase | 8 | 50% | 88% | 0.69 |
| hybrid+rerank | all | 22 | 100% | 100% | 1.00 |
| hybrid+rerank | lexical | 14 | 100% | 100% | 1.00 |
| hybrid+rerank | paraphrase | 8 | 100% | 100% | 1.00 |

## Per query (rank of first relevant hit, — = not in top k)

| doc | query | kind | dense | lexical | hybrid | hybrid+rerank |
|---|---|---|---|---|---|---|
| manual.pdf | 냉각수 온도 유지 범위 | lexical | 1 | 1 | 1 | 1 |
| manual.pdf | 쿨링 워터를 몇 도로 관리해야 하나 | paraphrase | 1 | — | — | 1 |
| manual.pdf | UPS 정전 유지 시간 | lexical | 1 | 1 | 1 | 1 |
| manual.pdf | 전기가 끊겼을 때 장비가 버티는 시간 | paraphrase | 1 | 3 | 2 | 1 |
| manual.pdf | 리크 테스트 주기 | lexical | 1 | 1 | 1 | 1 |
| manual.pdf | 누설 검사는 언제 하나 | paraphrase | 2 | — | 2 | 1 |
| manual.pdf | N2 가스 순도 기준 | lexical | 1 | 1 | 1 | 1 |
| manual.pdf | 비상 정지 버튼 위치 | lexical | 1 | 1 | 1 | 1 |
| manual.pdf | 작업자가 입어야 하는 보호 장비 | paraphrase | 1 | 1 | 1 | 1 |
| manual.pdf | E-305 알람 의미 | lexical | 1 | 1 | 1 | 1 |
| manual.pdf | 배기 필터 교체 주기 | lexical | 1 | 1 | 1 | 1 |
| manual.pdf | 센서 데이터 수집 간격 | lexical | 1 | 1 | 1 | 1 |
| manual.pdf | 측정값은 어디에 저장되나 | paraphrase | 1 | 1 | 1 | 1 |
| manual.pdf | 2분기 가동률 | lexical | 1 | 1 | 1 | 1 |
| manual.pdf | 가동률이 가장 낮은 분기와 이유 | paraphrase | 1 | 1 | 1 | 1 |
| manual.pdf | 냉각 계통도 그림 | lexical | 1 | 1 | 1 | 1 |
| deck.pptx | 3월 생산량 | lexical | 1 | 1 | 1 | 1 |
| deck.pptx | 발표에서 배경을 설명하는 슬라이드 | paraphrase | 1 | 1 | 1 | 1 |
| deck.pptx | 압력 점검 결과 | lexical | 1 | 1 | 1 | 1 |
| guide.docx | 온도 점검 주기와 기준 | lexical | 1 | 1 | 1 | 1 |
| guide.docx | 설치 전에 준비할 것 | paraphrase | 1 | 2 | 2 | 1 |
| sheet.xlsx | 장비별 평균 온도 요약 | lexical | 1 | 1 | 1 | 1 |
