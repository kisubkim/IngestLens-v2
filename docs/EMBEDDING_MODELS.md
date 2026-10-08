# 임베딩 모델 선택 메모

조사한 날: 2026-10-04. 라이선스는 Hugging Face 모델 정보에서 확인했다. 차원과 최대 입력 길이는 각 모델 카드 기준이다.

## 1. 지금 쓰는 모델: BAAI/bge-m3

| 항목 | 값 |
|---|---|
| 차원 | 1024 (고정, 차원 축소 학습 없음) |
| 최대 입력 | 8192 토큰 |
| 언어 | 100개 이상 다국어, 한국어 양호 |
| 라이선스 | MIT (상업 사용 가능) |

- bge-m3는 원래 dense, sparse, multi-vector(ColBERT) 세 가지 출력을 지원한다.
- vLLM이나 Ollama의 `/v1/embeddings`로 서빙하면 dense 벡터만 나온다. 이 프로젝트도 dense만 쓴다.
- 키워드 검색은 따로 만든 BM25(한글 bigram)가 맡는다(`tools/lexical.py`).

## 2. 이 프로젝트에서 모델을 바꾸는 방법

- `models.yaml`의 `embedding.base_url`과 `embedding.model`만 바꾸면 된다. OpenAI 호환 `/v1/embeddings`를 제공하면 어떤 모델이든 된다.
- 오프라인 배포의 모델 서버(`model-server.env`의 `EMBED_MODEL`, `EMBED_NAME`, Singularity는 `singularity.env`)로 서빙할 때는 그 설정도 함께 바꾼다. 모델 서버는 bge-m3 방식(CLS 토큰, L2 정규화)으로 dense 벡터를 만든다. 평균 풀링을 쓰는 모델(e5, gte 등)로 바꾸면 `docker/model-server/server.py`의 풀링도 맞춰야 한다.
- 차원은 모델 응답에서 자동으로 알아낸다(`tools/embedding.py`). `embedding.dim`은 dev-hash 임베더와 검증에만 쓴다.
- 벡터는 "모델 이름 + 차원"별 Qdrant 컬렉션에 저장된다(예: `chunks__bge_m3__1024`). 그래서 모델을 바꿔도 기존 벡터와 섞이지 않는다.
- **검색은 현재 설정된 모델의 컬렉션만 본다.** 모델을 바꾼 뒤에는 기존 문서를 다시 실행해야 새 모델로 검색된다.
- 첫 화면의 "벡터 컬렉션" 표에서 모델별 벡터 수를 볼 수 있다.

## 3. 후보 모델

| 모델 | 차원 | 최대 입력 | 라이선스 | 특징 |
|---|---|---|---|---|
| BAAI/bge-m3 (현재) | 1024 | 8192 | MIT | 다국어, 한국어 양호 |
| nlpai-lab/KURE-v1 | 1024 | 8192 | MIT | bge-m3를 한국어로 추가 학습한 모델. 차원이 같아 그대로 바꿔 끼울 수 있다 |
| dragonkue/BGE-m3-ko | 1024 | 8192 | Apache-2.0 | bge-m3 한국어 추가 학습판 |
| Qwen/Qwen3-Embedding-0.6B | 1024 (32까지 축소 가능) | 32k | Apache-2.0 | 최신 다국어 상위권. 4B는 2560차원, 8B는 4096차원 |
| Snowflake/snowflake-arctic-embed-l-v2.0 | 1024 (256까지 축소 가능) | 8192 | Apache-2.0 | 다국어, 검색 특화 |
| Alibaba-NLP/gte-multilingual-base | 768 | 8192 | Apache-2.0 | 작고 빠르다 |
| intfloat/multilingual-e5-large | 1024 | 512 | MIT | 입력이 짧아 긴 청크는 잘린다 |
| google/embeddinggemma-300m | 768 (128까지 축소 가능) | 2048 | Gemma 약관 | 작다. 사용 약관을 확인해야 한다 |
| jinaai/jina-embeddings-v3 | 1024 | 8192 | **CC BY-NC 4.0 (비상업)** | 상업 서비스에 쓸 수 없다 |

"축소 가능"은 Matryoshka 방식으로 학습해서, 벡터 앞부분만 잘라 써도 성능이 크게 떨어지지 않는다는 뜻이다. 차원을 줄이면 저장 공간과 검색 속도에 유리하다.

## 4. 바꾸기 전에 해결할 것

- **질의·문서 접두어를 지원하지 않는다.**
  - e5 계열은 `query: `/`passage: ` 접두어가 필요하다. Qwen3-Embedding은 질의 앞에 지시문(`Instruct: ...\nQuery: `)이 필요하다. 접두어가 없으면 제 성능이 나오지 않는다.
  - 지금 코드(`tools/embedding.py`)는 텍스트를 그대로 보낸다. 이 모델들을 쓰려면 `models.yaml`에 `query_prefix`/`document_prefix`를 추가하고, 임베딩 단계와 검색 단계에서 붙여야 한다.
  - bge-m3, KURE-v1, BGE-m3-ko는 접두어가 필요 없다.
- **차원 축소를 지원하지 않는다.** Matryoshka 모델의 차원을 줄이려면 서빙 쪽 옵션(vLLM의 `dimensions` 파라미터 등)이나 클라이언트에서 자르고 정규화하는 처리를 넣어야 한다.

## 5. 비교 방법

- 검색 정확도는 `scripts/eval_retrieval.py --dataset <질의 세트> --models <다른 models.yaml>`로 같은 문서와 질의로 비교한다(`evals/README.md` 2절).
- 지금 질의 세트는 합성 22문항뿐이다. 실제 운영 문서로 질의를 만들어야 의미 있는 비교가 된다.
- 결과는 `evals/reports/`에 남기고 `docs/HANDOFF.md` 7절에 조건과 함께 적는다.

## 6. 추천 순서

1. bge-m3를 기준선으로 둔다.
2. KURE-v1을 먼저 비교한다. 차원이 같고 접두어가 필요 없어 설정만 바꾸면 된다.
3. Qwen3-Embedding-0.6B까지 비교하려면 접두어 설정(4절)을 먼저 추가한다.

## 자료 출처

- [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3)
- [nlpai-lab/KURE-v1](https://huggingface.co/nlpai-lab/KURE-v1)
- [dragonkue/BGE-m3-ko](https://huggingface.co/dragonkue/BGE-m3-ko)
- [Qwen/Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
- [Snowflake/snowflake-arctic-embed-l-v2.0](https://huggingface.co/Snowflake/snowflake-arctic-embed-l-v2.0)
- [Alibaba-NLP/gte-multilingual-base](https://huggingface.co/Alibaba-NLP/gte-multilingual-base)
- [intfloat/multilingual-e5-large](https://huggingface.co/intfloat/multilingual-e5-large)
- [google/embeddinggemma-300m](https://huggingface.co/google/embeddinggemma-300m)
- [jinaai/jina-embeddings-v3](https://huggingface.co/jinaai/jina-embeddings-v3)
