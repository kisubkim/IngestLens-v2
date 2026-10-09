#!/usr/bin/env bash
# IngestLens 로컬 스택(docker-compose.yml: 앱, ToolPDF, Ollama, reranker)과 Open WebUI 를 함께 띄우고 내린다.
# start_webui_test.bat / stop_webui_test.bat 이 WSL 안에서 부른다. 리눅스에서는 저장소 루트에서 직접 실행한다.
#
#   bash scripts/webui_test.sh up       이미 떠 있는 것은 건너뛰고, 모두 응답할 때까지 기다린다
#   bash scripts/webui_test.sh status   상태만 보기
#   bash scripts/webui_test.sh recreate Open WebUI 설정을 바꾼 뒤 컨테이너만 다시 만들기 (데이터는 남김)
#   bash scripts/webui_test.sh down     둘 다 중지 (모델, 문서, Open WebUI 계정·지식 베이스는 남는다)
#
# Open WebUI 는 컨테이너 이름 OWUI_NAME(기본 owui-test), 데이터 볼륨 OWUI_VOLUME(기본 owui-test-data)을 쓴다.
# 컨테이너가 없으면 아래 설정으로 만든다. 문서 로더, 임베딩, reranker, 채팅 모델 모두 이 스택을 쓴다(deploy/OPENWEBUI.md).
set -u
cd "$(dirname "$0")/.."

OWUI_NAME="${OWUI_NAME:-owui-test}"
OWUI_VOLUME="${OWUI_VOLUME:-owui-test-data}"
OWUI_IMAGE="${OWUI_IMAGE:-ghcr.io/open-webui/open-webui:v0.11.3}"
OWUI_PORT="${OWUI_PORT:-3000}"
# 채팅 기본 모델. docker-compose.yml 의 CHAT_MODEL 과 같게 둔다(ollama-pull 이 받는다). 바꾸면 컨테이너를 다시 만들어야 적용된다(recreate).
OWUI_CHAT_MODEL="${OWUI_CHAT_MODEL:-gemma4:e4b}"
# 질문마다 가져올 청크 수(RAG_TOP_K, RAG_TOP_K_RERANKER). deploy/OPENWEBUI.md 4-4. 바꾸면 recreate.
OWUI_TOP_K="${OWUI_TOP_K:-5}"
# hybrid 검색에서 키워드(BM25) 점수의 비중(0~1, Open WebUI 기본 0.5). 바꾸면 recreate.
OWUI_BM25_WEIGHT="${OWUI_BM25_WEIGHT:-0.5}"
NET="$(basename "$PWD" | tr '[:upper:]' '[:lower:]')_default"   # compose 기본 네트워크 (예: ingestlens-v2_default)

say() { printf '%s\n' "$*"; }
http_ok() { curl -fs -m 3 -o /dev/null "$1"; }

# 앱 /api/status 의 항목별 상태를 "key=state" 로 한 줄에
status_line() {
  curl -fs -m 10 "http://127.0.0.1:8000/api/status?refresh=true" 2>/dev/null |
    python3 -c 'import json,sys; print(" ".join("%s=%s" % (i["key"], i["state"]) for i in json.load(sys.stdin)["items"]))' 2>/dev/null
}

up_stack() {
  if http_ok http://127.0.0.1:8000/api/health && [ "$(docker compose ps -q --status running app toolpdf ollama reranker | wc -l)" -ge 4 ]; then
    say "IngestLens 스택: 이미 실행 중입니다. 건너뜁니다."
    return
  fi
  say "IngestLens 스택을 빌드하고 시작합니다. 첫 실행은 모델(약 9.5GB)을 받느라 오래 걸립니다..."
  docker compose up -d --build || { say "[오류] docker compose 실행 실패. 인증서 오류라면 docker/certs/README.md"; exit 1; }
}

up_webui() {
  local state
  state="$(docker inspect -f '{{.State.Status}}' "$OWUI_NAME" 2>/dev/null || true)"
  case "$state" in
    running) say "Open WebUI($OWUI_NAME): 이미 실행 중입니다. 건너뜁니다." ;;
    "")
      say "Open WebUI($OWUI_NAME) 컨테이너를 만듭니다 (이미지 $OWUI_IMAGE, 데이터 볼륨 $OWUI_VOLUME)..."
      docker run -d --name "$OWUI_NAME" --restart unless-stopped \
        --network "$NET" -p "127.0.0.1:$OWUI_PORT:8080" -v "$OWUI_VOLUME:/app/backend/data" \
        -e ENABLE_PERSISTENT_CONFIG=false \
        -e OLLAMA_BASE_URL=http://ollama:11434 -e ENABLE_OLLAMA_API=true \
        -e DEFAULT_MODELS="$OWUI_CHAT_MODEL" -e TASK_MODEL="$OWUI_CHAT_MODEL" \
        -e CONTENT_EXTRACTION_ENGINE=external \
        -e EXTERNAL_DOCUMENT_LOADER_URL=http://app:8000/api/openwebui \
        -e EXTERNAL_DOCUMENT_LOADER_API_KEY=dev-no-key \
        -e RAG_EMBEDDING_ENGINE=openai -e RAG_OPENAI_API_BASE_URL=http://ollama:11434/v1 -e RAG_OPENAI_API_KEY=ollama \
        -e RAG_EMBEDDING_MODEL=bge-m3 \
        -e ENABLE_RAG_HYBRID_SEARCH=true -e RAG_HYBRID_BM25_WEIGHT="$OWUI_BM25_WEIGHT" -e RAG_RERANKING_ENGINE=external \
        -e RAG_EXTERNAL_RERANKER_URL=http://reranker:8080/v1/rerank -e RAG_EXTERNAL_RERANKER_API_KEY=EMPTY \
        -e RAG_RERANKING_MODEL=BAAI/bge-reranker-v2-m3 \
        -e CHUNK_SIZE=8000 -e CHUNK_OVERLAP=0 -e CHUNK_MIN_SIZE_TARGET=0 -e ENABLE_MARKDOWN_HEADER_TEXT_SPLITTER=false \
        -e RAG_TOP_K="$OWUI_TOP_K" -e RAG_TOP_K_RERANKER="$OWUI_TOP_K" \
        "$OWUI_IMAGE" >/dev/null || { say "[오류] Open WebUI 컨테이너를 만들지 못했습니다."; exit 1; }
      ;;
    *)
      say "Open WebUI($OWUI_NAME)를 시작합니다..."
      # compose down 이 스택 네트워크를 지우고 up 이 같은 이름으로 새로 만든다. 꺼진 컨테이너는 지워진 예전 네트워크를
      # 기억하고 있어 그대로 start 하면 "network ... not found" 로 실패하므로, 먼저 끊고 시작한 뒤 다시 붙인다.
      docker network disconnect -f "$NET" "$OWUI_NAME" >/dev/null 2>&1 || true
      docker start "$OWUI_NAME" >/dev/null || { say "[오류] Open WebUI 를 시작하지 못했습니다: docker logs $OWUI_NAME"; exit 1; }
      ;;
  esac
  # 앱, Ollama, reranker 를 compose 서비스 이름(app, ollama, reranker)으로 찾도록 스택의 네트워크에 붙인다.
  if ! docker inspect -f '{{json .NetworkSettings.Networks}}' "$OWUI_NAME" | grep -q "\"$NET\""; then
    docker network connect "$NET" "$OWUI_NAME" && say "Open WebUI 를 $NET 네트워크에 연결했습니다."
  fi
}

wait_all() {
  say "모두 응답할 때까지 기다립니다 (최대 15분)..."
  local line i
  for i in $(seq 1 180); do
    line="$(status_line)"
    if echo "$line" | grep -q "engine=ok" && echo "$line" | grep -q "embedding=ok" &&
       echo "$line" | grep -q "vlm=ok" && echo "$line" | grep -q "reranker=ok" && http_ok "http://127.0.0.1:$OWUI_PORT/health"; then
      say "준비 완료: $line"
      return 0
    fi
    sleep 5
  done
  say "[오류] 15분 안에 모두 준비되지 않았습니다. 마지막 상태: ${line:-앱 응답 없음}"
  say "       확인: docker compose logs app / docker logs $OWUI_NAME"
  return 1
}

show_status() {
  docker compose ps --format '{{.Service}}: {{.State}} {{.Status}}' 2>/dev/null
  say "$OWUI_NAME: $(docker inspect -f '{{.State.Status}}' "$OWUI_NAME" 2>/dev/null || echo '없음')"
  say "앱 상태: $(status_line || true)"
}

case "${1:-}" in
  up) up_stack; up_webui; wait_all ;;
  recreate)   # 설정(환경 변수)을 바꾼 뒤: 컨테이너만 지우고 같은 데이터 볼륨으로 다시 만든다. 계정·대화·지식 베이스는 남는다
    docker rm -f "$OWUI_NAME" >/dev/null 2>&1 && say "Open WebUI($OWUI_NAME) 컨테이너를 지웠습니다(데이터 볼륨 $OWUI_VOLUME 은 남김)."
    up_stack; up_webui; wait_all ;;
  status) show_status ;;
  down)
    docker stop "$OWUI_NAME" >/dev/null 2>&1 && say "Open WebUI($OWUI_NAME)를 중지했습니다."
    docker network disconnect -f "$NET" "$OWUI_NAME" >/dev/null 2>&1 || true   # 붙어 있으면 compose 가 네트워크를 못 지운다
    docker compose down && say "IngestLens 스택을 중지했습니다." ;;
  *) sed -n '2,10p' "$0"; exit 1 ;;
esac
