# Windows PC에서 실행하기

일반 Windows 10/11 PC에서 IngestLens를 설치하고 실행하는 방법이다. 개발자가 아니어도 따라 할 수 있게 순서대로 적었다. 인터넷이 없는 리눅스 서버에 설치하는 방법은 `deploy/README.md`에 따로 있다.

IngestLens는 프로그램 두 개로 돈다.

| 프로그램 | 하는 일 | 저장소 |
|---|---|---|
| **IngestLens** (이 저장소) | 화면, 문서 처리 순서(분석 → 파싱 → 청킹 → 임베딩), 검색 | https://github.com/kisubkim/IngestLens-v2 |
| **ToolPDF** | PDF 처리 엔진. 문서를 PDF로 바꾸고, 쪽을 분석하고, 글자·표·그림을 꺼낸다 | https://github.com/kisubkim/ToolPDF |

ToolPDF가 꺼져 있으면 문서를 하나도 처리할 수 없다. 아래 스크립트는 둘을 함께 띄운다.

## 0. 어떤 방법으로 실행할까

| 방법 | 이럴 때 | 필요한 것 | 결과 |
|---|---|---|---|
| **A. 스크립트로 바로 실행** (권장) | 처음 써 보거나, 화면과 처리 흐름을 볼 때 | Python 3.12, Node.js, Git | 모델 없이도 동작한다. 글자가 있는 PDF와 Office 문서를 처리한다 |
| **A + 실제 모델** (3절) | 스캔 문서 OCR, 그림 설명, 의미 검색까지 볼 때 | A + Windows용 Ollama, NVIDIA GPU(8GB 이상 권장) | 운영과 같은 품질을 PC에서 확인 |
| **B. Docker 스택** (7절) | 모델까지 한 번에 컨테이너로 띄우고 싶을 때 | WSL2 + Ubuntu + Docker Engine + NVIDIA Container Toolkit | 앱, ToolPDF, Ollama, reranker가 함께 뜬다 |

A와 B는 둘 다 포트 8000을 쓰므로 동시에 띄우지 않는다(바꾸는 법은 5절).

## 1. 준비물 (처음 한 번)

| 프로그램 | 받는 곳 | 주의 |
|---|---|---|
| Python **3.12** (64비트) | https://www.python.org/downloads/ | 설치 화면에서 "py launcher"를 켜 둔다(기본값). 3.13 이상이나 3.11은 쓰지 않는다 |
| Node.js LTS | https://nodejs.org/ | 화면을 빌드할 때만 쓴다 |
| Git | https://git-scm.com/download/win | 두 저장소를 받을 때 쓴다 |

설치한 뒤 새 PowerShell 창에서 확인한다.

```powershell
py -3.12 --version     # Python 3.12.x
node --version         # v22 이상
git --version
```

## 2. 방법 A: 스크립트로 실행

### 2-1. 받기

두 저장소를 **같은 폴더 안에 나란히** 받는다. 스크립트가 `IngestLens-v2` 옆의 `ToolPDF` 폴더를 찾는다. ToolPDF를 따로 받지 않으면 2-2의 `setup_local.bat`이 대신 받는다.

```powershell
cd D:\work                     # 원하는 폴더
git clone https://github.com/kisubkim/IngestLens-v2
git clone https://github.com/kisubkim/ToolPDF
```

```
D:\work\
  IngestLens-v2\
  ToolPDF\
```

경로에 한글이나 공백이 없는 폴더를 권한다.

### 2-2. 설치: `setup_local.bat` (처음 한 번)

`IngestLens-v2` 폴더의 **`setup_local.bat`을 더블클릭**한다. 인터넷이 필요하고 몇 분 걸린다. 하는 일은 다음과 같다.

1. ToolPDF가 없으면 `git clone`으로 받는다.
2. ToolPDF와 IngestLens에 각각 Python 가상환경(`.venv`)을 만들고 패키지를 설치한다.
3. 화면을 빌드한다(`frontend\dist`).

"준비가 끝났습니다"가 나오면 된다. 다시 실행해도 안전하다. 이미 있는 것은 건너뛰고 패키지만 맞춘다(업데이트 뒤에 다시 실행한다).

### 2-3. 실행: `start_local.bat`

**`start_local.bat`을 더블클릭**한다.

- "ToolPDF"와 "IngestLens" 창이 하나씩 열리고, 준비되면 브라우저가 http://localhost:8000 을 연다. 보통 10초 안에 뜬다.
- 두 창은 서버다. **닫으면 꺼진다.** 쓰는 동안 열어 둔다(최소화는 괜찮다).
- 오류가 나면 그 창에 이유가 나온다. 9절을 본다.

### 2-4. 확인

1. 화면 왼쪽 아래의 상태 표시를 누르거나 http://localhost:8000/#status 를 연다.
2. **"PDF 엔진 (ToolPDF)"가 정상**이어야 한다. 모델을 연결하지 않았으면 임베딩, VLM, reranker는 "꺼짐"이 정상이다.
3. 왼쪽에서 PDF 하나를 올리고 실행한다. 단계가 차례로 끝나고 "근거" 탭에 결정 이유가 보이면 된다.

모델 없이 실행하면 다음처럼 동작한다(결정 기록에 대체 동작으로 남는다).
- 스캔 문서와 그림은 PDF 안의 글자로만 처리한다. 글자가 없는 스캔 쪽은 비게 된다.
- 임베딩은 시험용 `dev-hash`를 쓴다. 키워드 검색(BM25)은 제대로 되지만 의미 검색 결과는 의미가 없다.

### 2-5. 중지

**`stop_local.bat`을 더블클릭**하거나 두 창을 닫는다. 올린 문서와 결과는 `IngestLens-v2\data\`에 남고, 다시 실행하면 그대로 보인다.

## 3. 실제 모델 연결 (선택)

### 3-1. Windows용 Ollama로 VLM과 임베딩

1. https://ollama.com/download 에서 Windows용 Ollama를 설치한다. 설치하면 백그라운드에서 돈다(작업 표시줄 아이콘).
2. 모델을 받는다(약 7GB).
   ```powershell
   ollama pull qwen2.5vl:7b     # VLM: 스캔 OCR, 그림 설명, 페이지 분류 보조
   ollama pull bge-m3           # 임베딩
   ```
   GPU 메모리가 8GB보다 작으면 `qwen2.5vl:3b`를 쓴다. 다만 3b는 비상업(연구·평가) 라이선스다(`NOTICE.md` 5절).
3. (선택) Ollama 설정. Ollama 0.40은 기본값으로도 동작한다. 이 PC(GPU 16GB)에서는 아무것도 바꾸지 않은 상태로 VLM 문맥 길이가 16384였고, VLM과 임베딩이 함께 GPU에 올라갔다(`ollama ps`로 확인). 긴 표에서 답이 잘리거나 모델이 번갈아 내려갔다 올라가면 다음을 정한다. **Windows 설정 → 시스템 → 정보 → 고급 시스템 설정 → 환경 변수**에서 사용자 변수로 추가하고 Ollama를 다시 시작한다(트레이 아이콘 → Quit 후 다시 실행).

   | 변수 | 값 | 이유 |
   |---|---|---|
   | `OLLAMA_CONTEXT_LENGTH` | `12288` 이상 | 쪽 이미지와 긴 답이 잘리지 않게(`ollama ps`의 CONTEXT가 이보다 작을 때) |
   | `OLLAMA_NUM_PARALLEL` | `2` | 설정 파일의 `max_concurrency: 2`와 맞춘다 |
   | `OLLAMA_MAX_LOADED_MODELS` | `2` | VLM과 임베딩을 함께 올려 둔다 |

4. `IngestLens-v2` 폴더에 `.env` 파일을 만들고 다음 한 줄을 적는다. 메모장으로 만들 때 이름이 `.env.txt`가 되지 않게 "모든 파일"로 저장한다.
   ```
   RAG_MODELS_FILE=config/models.windows.yaml
   ```
   `config/models.windows.yaml`은 Ollama 기본 주소(`http://127.0.0.1:11434/v1`)에 맞춘 설정이다. 모델 이름을 바꿨으면 그 파일의 `model`도 바꾼다. 내 설정을 따로 두려면 `config/models.local.yaml`로 복사해서 고치고 그 이름을 적는다(`*.local.yaml`은 git에 올라가지 않는다).
5. `stop_local.bat` → `start_local.bat`으로 다시 시작하고 `/#status`에서 임베딩과 VLM이 "정상"인지 본다.
   - "주의(서버는 응답하지만 모델이 없습니다)"는 `ollama pull`을 안 했거나 이름이 다르다는 뜻이다.
   - "오류(연결할 수 없습니다)"는 Ollama가 꺼져 있다는 뜻이다.

임베딩 모델을 바꾸거나 처음 연결했으면 **이미 처리한 문서를 다시 실행**해야 새 모델로 검색된다.

**첫 문서는 느리다.** 받은 모델을 처음 쓸 때 Ollama가 모델을 새 형식으로 바꾸면서, 그동안 같은 VLM이 GPU에 두 번 올라가기도 한다. 이 PC에서 첫 문서(6쪽)는 193초, 바로 다음 같은 문서는 12초였다. 이때 `ollama list`에 `qwen2.5vl:7b`가 두 줄, `llamacpp:<긴 ID>`가 한 줄 더 보이는데 Ollama가 만든 사본이다(디스크 약 6GB 더 씀).

### 3-2. 확인할 것

- 스캔 쪽이 있는 문서를 올려 "파싱 리포트"에서 OCR 결과가 제목, 본문, 표로 나뉘는지 본다. 저장소의 `evals\samples\ko_scan_kostat.pdf`(한국어 스캔 3쪽)를 쓰면 된다. 이 PC에서는 84초 걸렸고, 표가 빽빽한 두 쪽은 답이 잘려 한도를 올려 다시 요청했다("근거"의 `vlm_truncated_retry`, 정상).
- 글자가 전혀 없는 스캔 쪽은 VLM이 빈 답을 주고 PDF 텍스트로 대체된다("근거"의 `vlm_error`). 이것도 정상이다.
- "근거" 탭의 `embedding model`이 `dev-hash`가 아니라 `bge-m3`인지 본다.
- Ollama에는 토큰 수를 세는 `/tokenize`가 없어서 토큰 비율은 기본값 2.5를 쓴다. 결정 기록에 "default"로 나오는 것은 정상이다.

### 3-3. reranker (선택)

검색 결과를 다시 정렬하는 reranker는 Ollama에 없다. 없어도 검색은 된다(검색 화면의 rerank 옵션만 꺼진다). 쓰려면 이 저장소의 모델 서버(`docker/model-server/server.py`)를 별도 Python 환경에서 띄운다. 처음 실행할 때 Hugging Face에서 모델(약 2.3GB)을 받는다.

```powershell
py -3.12 -m venv D:\work\model-server-venv
D:\work\model-server-venv\Scripts\pip install torch transformers fastapi "uvicorn[standard]"
# NVIDIA GPU 를 쓰려면 torch 는 https://pytorch.org 의 안내대로 CUDA 판으로 설치한다
D:\work\model-server-venv\Scripts\python docker\model-server\server.py --rerank-model BAAI/bge-reranker-v2-m3 --rerank-name BAAI/bge-reranker-v2-m3 --port 8081 --host 127.0.0.1
```

그다음 모델 설정 파일의 `reranker.base_url`을 `http://127.0.0.1:8081`로 바꾸고 앱을 다시 시작한다. 같은 서버로 임베딩까지 맡기려면 `--embed-model BAAI/bge-m3 --embed-name bge-m3`를 더하고 `embedding.base_url`을 `http://127.0.0.1:8081/v1`로 둔다(운영과 같은 구성, 토큰 비율도 실제로 잰다).

### 3-4. GPU 없이 흐름만 보기 (mock)

모델 대신 정해진 답을 돌려주는 가짜 서버로 VLM 경로를 확인할 수 있다.

```powershell
.venv\Scripts\python scripts\mock_vllm.py --port 8001 --latency 0.3
```

모델 설정 파일을 복사해 `base_url`을 모두 `http://127.0.0.1:8001/v1`로 바꾸고 `.env`의 `RAG_MODELS_FILE`로 지정한다. mock의 분류기는 항상 `diagram`이라고 답한다.

## 4. 다른 PC에서 접속하게 하기

기본은 이 PC에서만 열린다(`127.0.0.1`). 같은 네트워크의 다른 PC에서 쓰려면:

1. `.env`에 관리자 키를 적는다. 다른 PC에서 설정 변경, 문서 삭제, 수집 API를 쓸 때 이 키가 필요하다.
   ```
   RAG_API_KEY=길고-임의의-문자열
   ```
2. 받을 주소를 바꿔서 시작한다. PowerShell에서:
   ```powershell
   $env:INGESTLENS_HOST = '0.0.0.0'; .\start_local.bat
   ```
   (cmd에서는 `set INGESTLENS_HOST=0.0.0.0` 후 `start_local.bat`.)
3. Windows 방화벽에서 8000 포트를 연다. 처음 시작할 때 방화벽 창이 뜨면 "개인 네트워크"만 허용한다. 직접 열려면 관리자 PowerShell에서:
   ```powershell
   New-NetFirewallRule -DisplayName "IngestLens 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private
   ```
4. 다른 PC의 브라우저에서 `http://<이 PC의 IP>:8000`을 연다. IP는 `ipconfig`의 IPv4 주소다.

ToolPDF는 계속 이 PC(`127.0.0.1`)에서만 열린다. 바꾸지 않는다.

## 5. 설정 바꾸기

**`.env`** (`IngestLens-v2` 폴더, 앱 설정. 바꾼 뒤 앱을 다시 시작한다)

| 항목 | 예 | 뜻 |
|---|---|---|
| `RAG_MODELS_FILE` | `config/models.windows.yaml` | 모델 설정 파일. 상대 경로는 저장소 폴더 기준 |
| `RAG_API_KEY` | `긴-임의-문자열` | 관리자 키(4절) |
| `RAG_DATA_DIR` | `E:/ingestlens-data` | 문서와 결과를 저장할 폴더(기본 `data`). 화면의 "저장 위치 설정"에서도 바꿀 수 있다 |

**스크립트 환경 변수** (`start_local.bat`을 실행하기 전에 정한다)

| 변수 | 기본값 | 뜻 |
|---|---|---|
| `INGESTLENS_PORT` | `8000` | 앱 포트. Docker 스택(방법 B)과 함께 쓰려면 `8100` 등으로 |
| `TOOLPDF_PORT` | `8095` | ToolPDF 포트 |
| `INGESTLENS_HOST` | `127.0.0.1` | `0.0.0.0`이면 다른 PC에서 접속 가능(4절) |
| `TOOLPDF_DIR` | `..\ToolPDF` | ToolPDF 폴더가 다른 곳에 있을 때 |

PowerShell에서는 `$env:INGESTLENS_PORT='8100'; .\start_local.bat`, cmd에서는 `set INGESTLENS_PORT=8100` 후 `start_local.bat`.

**ToolPDF 설정**은 `ToolPDF` 폴더의 `toolpdf.toml`에 적는다(`toolpdf.example.toml`을 복사). 예: 처리 프로세스 수 `workers = 4`, LibreOffice 위치(6절). 바꾼 뒤 다시 시작한다.

## 6. LibreOffice (선택)

없어도 docx, pptx, xlsx는 ToolPDF가 자체 렌더링으로 PDF로 바꾼다. **doc, ppt, hwp** 같은 옛 형식을 처리하거나 원본과 똑같은 레이아웃이 필요할 때만 설치한다.

1. https://www.libreoffice.org/ 에서 설치한다.
2. `ToolPDF\toolpdf.toml`에 실행 파일 위치를 적는다(PATH에 있으면 생략).
   ```toml
   soffice_path = "C:/Program Files/LibreOffice/program/soffice.exe"
   ```
3. 다시 시작하면 `/#status`의 LibreOffice 항목이 "정상"이 된다.

Windows에는 한글 글꼴이 이미 있어 따로 설치할 것이 없다. 이 방식은 개발 PC에서 아직 시험하지 않았다(`docs/HANDOFF.md` 1절).

## 7. 방법 B: Docker 스택 (실제 모델까지 한 번에)

앱, ToolPDF, Ollama(VLM `qwen2.5vl:7b`, 임베딩 `bge-m3`), reranker를 컨테이너로 한 번에 띄운다. Docker Desktop 없이 **WSL2 안의 Docker Engine**을 쓴다.

1. 준비(처음 한 번): WSL2 Ubuntu-24.04, Docker Engine, NVIDIA Container Toolkit, `.wslconfig`. 순서는 `docs/HANDOFF.md` 3-1에 있다.
2. ToolPDF를 2-1처럼 `IngestLens-v2` 옆에 받아 둔다. 이미지를 그 소스로 빌드한다.
3. **`start_test.bat`** 더블클릭: 이미지를 빌드하고 모델(약 9.5GB)을 받은 뒤 브라우저를 연다. 첫 실행은 오래 걸린다.
4. 중지: **`stop_test.bat`**. 받은 모델과 `data-docker\`의 문서는 남는다.

- 데이터는 `IngestLens-v2\data-docker\`에 저장된다(방법 A의 `data\`와 다르다).
- 백신이나 사내 프록시 때문에 빌드가 인증서 오류로 실패하면 `docker\certs\README.md`를 따른다.
- 자세한 설명은 `README.md`의 "로컬 PC에서 실제 모델로 실행 (Docker)".

### 7-1. Open WebUI까지 함께: `start_webui_test.bat`

IngestLens 스택과 **Open WebUI**(v0.11.3)를 함께 띄워, Open WebUI에 파일을 넣고 질문하는 흐름까지 시험한다. 준비는 7절과 같다.

1. **`start_webui_test.bat`** 더블클릭.
   - IngestLens 스택(앱, ToolPDF, Ollama, reranker)과 Open WebUI 컨테이너를 띄운다. **이미 떠 있는 것은 건너뛴다.**
   - PDF 엔진, 임베딩, VLM, reranker, Open WebUI가 모두 응답할 때까지 기다린다(첫 실행은 모델을 받느라 오래 걸리고, 그 뒤로는 1분 안팎).
   - 준비되면 두 화면을 연다: IngestLens http://localhost:8000, Open WebUI http://localhost:3000.
2. 중지: **`stop_webui_test.bat`**. 받은 모델, IngestLens 문서(`data-docker\`), Open WebUI의 계정·대화·지식 베이스(Docker 볼륨 `owui-test-data`)는 남는다.

Open WebUI는 이렇게 연결된다(`deploy/OPENWEBUI.md`와 같은 설정).

| Open WebUI 기능 | 쓰는 것 |
|---|---|
| 파일 추가 시 문서 처리(External 문서 로더) | IngestLens 앱 `http://app:8000/api/openwebui` |
| 임베딩 | 스택의 Ollama `bge-m3` |
| reranker | 스택의 모델 서버 `BAAI/bge-reranker-v2-m3` |
| 채팅 모델 (기본) | 스택의 Ollama `gemma4:e4b`(약 6.6GB, `docker-compose.yml`의 `CHAT_MODEL`). `qwen2.5vl:7b`는 OCR·그림 설명용 VLM이라 긴 문서를 정리하는 질문에는 빈 답을 내곤 했다 |

- **로그인:** Open WebUI 컨테이너를 처음 만들고 처음 가입한 사람이 관리자가 된다. 이 PC의 시험용 관리자 계정은 `admin@example.com`이다.
- **답변에 쪽 이미지:** 필터 함수(`deploy/openwebui_page_images.py`)를 설치하면 답변 아래에 근거 쪽 썸네일이 붙는다(`deploy/OPENWEBUI.md` 10절). 밸브 `INGESTLENS_URL`은 `http://127.0.0.1:8000`.
- **시험 순서 예:** Open WebUI에서 작업 공간 → 지식 → 새 지식 베이스에 PDF 추가 → IngestLens 화면의 문서 목록에 나타나고 "성공"이 되는지 → 채팅에서 `#`으로 그 지식 베이스를 골라 질문 → 답변의 출처 쪽 번호와 썸네일 확인.
- 채팅 모델을 바꾸려면 `docker-compose.yml`의 `CHAT_MODEL`과 `OWUI_CHAT_MODEL`(기본 `gemma4:e4b`)을 함께 바꾸고 WSL에서 `bash scripts/webui_test.sh recreate`로 Open WebUI 컨테이너만 다시 만든다(계정·대화·지식 베이스는 남는다). 채팅 화면의 모델 선택에서 그때그때 골라도 된다.
- 썸네일은 답변 내용과 맞는 쪽만 보인다(필터 0.4.0, `deploy/OPENWEBUI.md` 10-3).
- 다른 Open WebUI 컨테이너 이름, 데이터 볼륨, 포트를 쓰려면 `OWUI_NAME`, `OWUI_VOLUME`, `OWUI_PORT`(기본 `owui-test`, `owui-test-data`, `3000`)를 정한다. 실제 동작은 `scripts\webui_test.sh`에 있다(리눅스에서는 `bash scripts/webui_test.sh up|status|recreate|down`).
- 검색 설정을 바꿔 시험하려면 `OWUI_TOP_K`(질문마다 가져올 청크 수, 기본 5), `OWUI_BM25_WEIGHT`(키워드 비중, 기본 0.5)를 정하고 WSL에서 `env OWUI_TOP_K=10 bash scripts/webui_test.sh recreate`. 권장값과 근거는 `deploy/OPENWEBUI.md` 4-4. 청크 크기·겹침·최소 크기는 IngestLens의 `config\strategy_rules.yaml`에서 정한다(바꾸면 문서를 다시 처리하고 Open WebUI에 다시 넣는다).
- `start_test.bat`(7절)과 같은 스택을 쓰므로 둘 중 하나만 쓰면 된다. Windows용 Ollama가 켜져 있으면 GPU를 나눠 쓰니, 느리면 트레이에서 종료한다.

## 8. 업데이트

```powershell
cd D:\work\ToolPDF;        git pull
cd D:\work\IngestLens-v2;  git pull
```

그다음 `stop_local.bat` → `setup_local.bat` → `start_local.bat`. 올린 문서와 결과(`data\`)는 그대로 쓴다.

## 9. 문제 해결

| 증상 | 원인과 해결 |
|---|---|
| `setup_local.bat`: "Python 3.12 가 없습니다" | Python 3.12를 설치한다. 이미 설치했으면 새 창에서 `py -0`으로 3.12가 보이는지 확인한다 |
| pip나 npm이 `CERTIFICATE_VERIFY_FAILED`, `SELF_SIGNED_CERT_IN_CHAIN`으로 실패 | 백신(HTTPS 검사)이나 사내 프록시가 인증서를 바꾸는 경우다. 백신의 HTTPS 검사를 잠시 끄거나, 사내 루트 인증서를 PEM 파일로 내보내(`docker\certs\README.md`의 PowerShell 명령) `set PIP_CERT=<파일>`, `set NODE_EXTRA_CA_CERTS=<파일>`을 정한 같은 cmd 창에서 `setup_local.bat`을 실행한다 |
| `start_local.bat`: "포트 8000 를 이미 다른 프로그램이 쓰고 있습니다" | 이미 실행 중이면 `stop_local.bat`. Docker 스택(방법 B)이 떠 있으면 `stop_test.bat`이나 `INGESTLENS_PORT=8100` |
| 상태에서 "PDF 엔진 (ToolPDF)"가 오류 | "ToolPDF" 창이 닫혔거나 오류로 멈췄다. 창의 메시지를 보고 `start_local.bat`을 다시 실행한다. ToolPDF 폴더나 그 안의 `.venv`가 없으면 `setup_local.bat` |
| 문서가 "실패"로 끝남 | 실행 화면의 "경고/오류" 탭에 이유가 있다. doc/ppt/hwp는 LibreOffice가 필요하다(6절). 암호가 걸린 PDF는 처리하지 않는다 |
| 브라우저에 화면 대신 `{"detail":"Not Found"}` | 화면이 빌드되지 않았다. Node.js를 설치하고 `setup_local.bat`을 다시 실행한다 |
| 임베딩·VLM이 "오류(연결할 수 없습니다)" | Ollama가 꺼져 있다. 시작 메뉴에서 Ollama를 실행한다 |
| 임베딩·VLM이 "주의(모델이 없습니다)" | `ollama pull <모델>`을 하거나 설정 파일의 `model` 이름을 `ollama list`의 이름과 맞춘다 |
| 처리가 아주 느림 | 모델을 받은 뒤 첫 문서는 Ollama가 모델 형식을 바꾸느라 느리다(3-1). 그 뒤에도 VLM 한 번에 수 초~수십 초가 걸리는 것은 정상이다(GPU에 따라 다름). 작업 관리자에서 GPU 사용을 확인한다. 모델 주소에 `localhost`를 쓰면 요청마다 약 2초가 더 걸리니 `127.0.0.1`로 쓴다 |
| 그림 설명이 영어로 나옴 | 7b 모델에서 알려진 현상이다(`docs/HANDOFF.md` 6절) |
| 창을 닫았더니 꺼짐 | 정상이다. 두 창이 서버다. 다시 `start_local.bat` |

## 10. 이 문서의 확인 범위 (2026-10-09, 개발 PC)

- 확인함: `setup_local.bat`(가상환경, 패키지, 화면 빌드), `start_local.bat`(두 서버 시작, 포트 충돌 검사), `stop_local.bat`. 모델 없이 PDF 처리.
- 확인함, 3절 순서 그대로: Windows용 Ollama 0.40.1에 `qwen2.5vl:7b`, `bge-m3`를 받고 `.env`에 `RAG_MODELS_FILE=config/models.windows.yaml` 한 줄. Ollama 환경 변수는 바꾸지 않음. 상태 화면 임베딩·VLM 정상, `sample.pdf`(그림 설명, 차트 재분류) 처리, 한국어 실제 스캔 3쪽 OCR(청크 12개, 표 포함).
- 확인함: Docker의 Ollama와 모델 서버 reranker로 hybrid+rerank 검색.
- 확인 못 함: 3-3의 모델 서버를 Windows Python에서 직접 실행, LibreOffice(6절), 다른 PC에서 접속(4절).

## 11. 스크립트 없이 직접 실행 (개발자용)

PowerShell 창 두 개에서 실행한다.

```powershell
# 창 1: ToolPDF
cd D:\work\ToolPDF
.venv\Scripts\python -m uvicorn toolpdf.server:app --host 127.0.0.1 --port 8095

# 창 2: IngestLens
cd D:\work\IngestLens-v2\backend
$env:RAG_TOOLPDF_URL = 'http://127.0.0.1:8095'      # 기본값과 같으면 생략
..\.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

화면을 고치며 개발할 때는 `cd frontend; npm run dev`(Vite가 알려 주는 주소, 보통 http://localhost:5173, `/api`는 8000으로 전달)를 쓴다. 테스트는 `cd backend; ..\.venv\Scripts\python -m pytest -q`이고, ToolPDF를 직접 띄우므로 따로 실행해 둘 필요가 없다. 나머지 개발 명령은 `README.md`와 `docs/HANDOFF.md` 10절에 있다.
