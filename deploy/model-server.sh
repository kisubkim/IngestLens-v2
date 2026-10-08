#!/usr/bin/env sh
# 임베딩(bge-m3)과 reranker(bge-reranker-v2-m3)를 프로세스 하나로 띄운다. root 권한도 Docker도 필요 없다.
# GPU가 Exclusive_Process 모드(프로세스 1개만 허용)여도 CUDA 컨텍스트가 하나뿐이라 동작한다.
#
#   ./model-server.sh start     시작 (백그라운드, 로그는 model-server.log)
#   ./model-server.sh stop      중지
#   ./model-server.sh status    상태와 GPU를 잡은 프로세스
#   ./model-server.sh logs      로그 보기
#   ./model-server.sh run       앞에서 실행 (문제 확인용)
#
# 설정은 model-server.env (model-server.env.example 을 복사).
set -e
cd "$(dirname "$0")"
[ -f model-server.env ] || { echo "[오류] model-server.env 가 없습니다. model-server.env.example 을 복사해 고치세요." >&2; exit 1; }
set -a; . ./model-server.env; set +a

PIDFILE=model-server.pid
LOG=model-server.log
SERVER=model-server/server.py
ARGS="--device ${DEVICE:-cuda} --port ${PORT:-8090} --max-batch-tokens ${MAX_BATCH_TOKENS:-16384}"
[ -n "$EMBED_MODEL" ] && ARGS="$ARGS --embed-model $EMBED_MODEL --embed-name ${EMBED_NAME:-bge-m3}"
[ -n "$RERANK_MODEL" ] && ARGS="$ARGS --rerank-model $RERANK_MODEL --rerank-name ${RERANK_NAME:-bge-reranker-v2-m3}"
[ -n "$API_KEY" ] && ARGS="$ARGS --api-key $API_KEY"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1   # 미리 받아 둔 폴더만 쓴다

running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

case "${1:-}" in
  start)
    if running; then echo "이미 실행 중입니다 (pid $(cat "$PIDFILE"))."; exit 0; fi
    "$PYTHON" -c "import torch, transformers, fastapi, uvicorn" 2>/dev/null || {
      echo "[오류] $PYTHON 에 torch, transformers, fastapi, uvicorn 이 없습니다. vLLM 이 설치된 Python 을 PYTHON 에 적으세요." >&2; exit 1; }
    nohup "$PYTHON" "$SERVER" $ARGS >> "$LOG" 2>&1 &
    echo $! > "$PIDFILE"
    echo "시작했습니다 (pid $!). 모델을 올리는 데 수십 초 걸립니다. 확인: ./model-server.sh status"
    ;;
  stop)
    if running; then kill "$(cat "$PIDFILE")"; rm -f "$PIDFILE"; echo "중지했습니다."; else echo "실행 중이 아닙니다."; rm -f "$PIDFILE"; fi
    ;;
  status)
    if running; then echo "실행 중 (pid $(cat "$PIDFILE"))"; else echo "실행 중이 아님"; fi
    curl -s "http://localhost:${PORT:-8090}/health" && echo || echo "(아직 응답 없음: 모델을 올리는 중이거나 실패. ./model-server.sh logs)"
    command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv || true
    ;;
  logs)
    tail -n 50 -f "$LOG"
    ;;
  run)
    exec "$PYTHON" "$SERVER" $ARGS
    ;;
  *)
    sed -n '2,10p' "$0"; exit 1
    ;;
esac
