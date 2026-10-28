# 임베딩 모델 선택 메모

조사한 날: 2026-10-04, EmbeddingGemma 2 추가 2026-10-28. 라이선스는 Hugging Face 모델 정보에서 확인했다. 차원과 최대 입력 길이는 각 모델 카드 기준이다.

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
- 오프라인 배포의 모델 서버(`model-server.env`의 `EMBED_MODEL`, `EMBED_NAME`, Singularity는 `singularity.env`)로 서빙할 때는 그 설정도 함께 바꾼다. 모델 서버는 bge-m3를 CLS 토큰 방식으로, Gemma 계열(EmbeddingGemma)은 sentence-transformers 방식(모델에 든 풀링·dense 층)과 bfloat16으로 올린다(`--embed-backend auto`). 다른 평균 풀링 모델(e5, gte)은 `MS_EMBED_BACKEND=st`로 sentence-transformers 방식을 쓴다.
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

- ~~질의·문서 접두어를 지원하지 않는다.~~ 2026-10-28 추가: `models.yaml` `embedding.query_prefix`, `document_prefix`(`{title}`은 청크의 절 제목), `dimensions`. 실행마다 쓴 접두어를 기록하고, 검색은 그 실행이 색인된 질의 접두어를 쓴다.
  - e5 계열은 `query: `/`passage: `, Qwen3-Embedding은 질의 앞에 지시문(`Instruct: ...\nQuery: `), EmbeddingGemma는 아래 7절.
  - bge-m3, KURE-v1, BGE-m3-ko는 접두어가 필요 없다.
  - Open WebUI도 청크를 자기 임베딩으로 다시 넣는다. 같은 접두어를 Open WebUI의 `RAG_EMBEDDING_QUERY_PREFIX`, `RAG_EMBEDDING_CONTENT_PREFIX`에도 넣는다(0.11.3 소스에서 확인: 별도 필드 설정이 없으면 글 앞에 그대로 붙인다).
- **차원 축소를 지원하지 않는다.** Matryoshka 모델의 차원을 줄이려면 서빙 쪽 옵션(vLLM의 `dimensions` 파라미터 등)이나 클라이언트에서 자르고 정규화하는 처리를 넣어야 한다.

## 5. 비교 방법

- 검색 정확도는 `scripts/eval_retrieval.py --dataset <질의 세트> --models <다른 models.yaml>`로 같은 문서와 질의로 비교한다(`evals/README.md` 2절).
- 지금 질의 세트는 합성 22문항뿐이다. 실제 운영 문서로 질의를 만들어야 의미 있는 비교가 된다.
- 결과는 `evals/reports/`에 남기고 `docs/HANDOFF.md` 7절에 조건과 함께 적는다.

## 6. 추천 순서

1. bge-m3를 기준선으로 둔다.
2. KURE-v1을 먼저 비교한다. 차원이 같고 접두어가 필요 없어 설정만 바꾸면 된다.
3. Qwen3-Embedding-0.6B까지 비교하려면 접두어 설정(4절)을 먼저 추가한다.

## 7. EmbeddingGemma 2 (google/embeddinggemma-2, 2026-10-06 공개)

| 항목 | 값 |
|---|---|
| 크기 | 740M(텍스트 270M + 이미지 170M + 오디오 300M, 텍스트만 쓸 수 있음) |
| 차원 | 768, Matryoshka로 512/256/128 |
| 최대 입력 | 8192 토큰 |
| 라이선스 | Apache-2.0 |
| 다국어 | MTEB(multilingual, v2) 61.36 (1세대 61.15). 한국어 따로 낸 공식 수치는 없음 |

**꼭 지킬 것**
- 질의·문서 지시문: 질의 `task: search result | query: `, 문서 `title: {title} | text: `(제목이 없으면 `title: none | text: `). 모델 폴더의 `config_sentence_transformers.json` 값과 같다.
- **float16 금지.** 모델 카드가 "값이 소리 없이 틀린다"고 한다. GPU는 bfloat16, CPU는 float32. 모델 서버는 Gemma 계열을 알아보고 자동으로 bfloat16을 쓴다. vLLM으로 띄운다면 `--dtype bfloat16`.
- 모델 서버에 sentence-transformers 6.1 이상, Pillow, torchvision이 필요하다(텍스트만 써도 모델의 전처리기가 불러온다). 모델 서버 이미지에 넣었다.

**vLLM으로 띄울 때 (vLLM 0.32.0 이상, 2026-10-18 출시 노트에 EmbeddingGemma 2 지원이 있다)**

```bash
vllm serve /models/embeddinggemma-2 --served-model-name embeddinggemma-2 \
    --runner pooling --dtype bfloat16 --max-model-len 8192 \
    --limit-mm-per-prompt image=0,audio=0,video=0 \
    --gpu-memory-utilization 0.1 --port 8091
```

- `--limit-mm-per-prompt image=0,audio=0,video=0`: 이미지·영상·오디오 인코더를 올리지 않는다(텍스트 270M만, vLLM PR #60254 기준 약 517MiB).
- `--dtype bfloat16`을 꼭 준다. `auto`는 bfloat16을 못 쓰는 GPU(V100, T4)에서 float16이 될 수 있고, 이 모델은 float16에서 값이 틀린다. bfloat16이 없는 GPU면 `float32`.
- MPS로 다른 vLLM과 GPU를 나눠 쓰면 `--gpu-memory-utilization`을 프로세스마다 작게 정해 합이 1을 넘지 않게 한다.
- IngestLens `models.yaml`: `base_url: http://<서버>:8091/v1`, `model: embeddinggemma-2`, `dim: 768`, 위의 `query_prefix`/`document_prefix`. 토큰 수 측정은 vLLM의 `/tokenize`를 그대로 쓴다.
- `dimensions`(짧은 벡터)는 vLLM에서 이 모델로 시험하지 않았다. 768 그대로 쓰는 것을 기본으로 한다.

**측정 (2026-10-28, 합성 검색 세트 22문항, 같은 문서·같은 내장 PDF 엔진, rerank 없음)**

| | dense hit@1 | paraphrase hit@1 | hybrid hit@1 | hybrid MRR |
|---|---|---|---|---|
| bge-m3 (Windows Ollama) | 95% | 88% | 82% | 0.90 |
| EmbeddingGemma 2, 접두어 있음 (모델 서버, CPU float32) | **100%** | **100%** | **91%** | **0.95** |
| EmbeddingGemma 2, 접두어 없음 | 91% | 75% | 82% | 0.88 |

- 보고서: `evals/reports/retrieval_synthetic_bgem3_20261028.md`, `..._embeddinggemma2_20261028.md`, `..._embeddinggemma2_noprefix_20261028.md`.
- 표본이 작다(바꿔 말한 질문 8개). 운영 문서로 `eval_retrieval.py`를 다시 재고 정한다. 접두어 없이는 bge-m3보다 낫지 않다.
- 차원이 768이라 bge-m3(1024)와 다른 컬렉션에 저장된다. 바꾸면 기존 문서를 다시 실행해야 새 모델로 검색된다(Open WebUI 지식 베이스도 다시 넣는다).

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
