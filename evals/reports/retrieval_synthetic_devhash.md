# Retrieval evaluation (2026-09-30)

- models: `models.yaml`
- k = 5

## Documents

| file | chunks | embedding | chars/token | ingest s |
|---|---|---|---|---|
| manual.pdf | 12 | dev-hash | 2.5 | 1.8 |
| deck.pptx | 5 | dev-hash | 2.5 | 0.2 |
| guide.docx | 6 | dev-hash | 2.5 | 0.2 |
| sheet.xlsx | 8 | dev-hash | 2.5 | 0.5 |

## Metrics

| mode | query kind | n | hit@1 | hit@5 | MRR |
|---|---|---|---|---|---|
| dense | all | 22 | 68% | 91% | 0.75 |
| dense | lexical | 14 | 86% | 100% | 0.91 |
| dense | paraphrase | 8 | 38% | 75% | 0.46 |
| lexical | all | 22 | 82% | 91% | 0.86 |
| lexical | lexical | 14 | 100% | 100% | 1.00 |
| lexical | paraphrase | 8 | 50% | 75% | 0.60 |
| hybrid | all | 22 | 82% | 91% | 0.85 |
| hybrid | lexical | 14 | 93% | 100% | 0.96 |
| hybrid | paraphrase | 8 | 62% | 75% | 0.66 |

## Per query (rank of first relevant hit, — = not in top k)

| doc | query | kind | dense | lexical | hybrid |
|---|---|---|---|---|---|
| manual.pdf | 냉각수 온도 유지 범위 | lexical | 1 | 1 | 1 |
| manual.pdf | 쿨링 워터를 몇 도로 관리해야 하나 | paraphrase | — | — | — |
| manual.pdf | UPS 정전 유지 시간 | lexical | 4 | 1 | 1 |
| manual.pdf | 전기가 끊겼을 때 장비가 버티는 시간 | paraphrase | — | 3 | 4 |
| manual.pdf | 리크 테스트 주기 | lexical | 1 | 1 | 1 |
| manual.pdf | 누설 검사는 언제 하나 | paraphrase | 5 | — | — |
| manual.pdf | N2 가스 순도 기준 | lexical | 1 | 1 | 1 |
| manual.pdf | 비상 정지 버튼 위치 | lexical | 1 | 1 | 1 |
| manual.pdf | 작업자가 입어야 하는 보호 장비 | paraphrase | 4 | 1 | 1 |
| manual.pdf | E-305 알람 의미 | lexical | 1 | 1 | 1 |
| manual.pdf | 배기 필터 교체 주기 | lexical | 1 | 1 | 1 |
| manual.pdf | 센서 데이터 수집 간격 | lexical | 1 | 1 | 1 |
| manual.pdf | 측정값은 어디에 저장되나 | paraphrase | 4 | 1 | 1 |
| manual.pdf | 2분기 가동률 | lexical | 1 | 1 | 1 |
| manual.pdf | 가동률이 가장 낮은 분기와 이유 | paraphrase | 1 | 1 | 1 |
| manual.pdf | 냉각 계통도 그림 | lexical | 1 | 1 | 1 |
| deck.pptx | 3월 생산량 | lexical | 1 | 1 | 1 |
| deck.pptx | 발표에서 배경을 설명하는 슬라이드 | paraphrase | 1 | 1 | 1 |
| deck.pptx | 압력 점검 결과 | lexical | 1 | 1 | 1 |
| guide.docx | 온도 점검 주기와 기준 | lexical | 2 | 1 | 2 |
| guide.docx | 설치 전에 준비할 것 | paraphrase | 1 | 2 | 1 |
| sheet.xlsx | 장비별 평균 온도 요약 | lexical | 1 | 1 | 1 |
