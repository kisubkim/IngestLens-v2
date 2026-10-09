#!/usr/bin/env sh
# Singularity/Apptainer 로 IngestLens 를 실행한다. root 권한도 Docker도 필요 없다. 인터넷도 필요 없다.
#
#   ./singularity.sh start                PDF 엔진, 모델 서버, 앱을 모두 시작 (백그라운드). RAG_PDF_ENGINE=local 이면 PDF 엔진은 건너뛴다
#   ./singularity.sh start-pdf            PDF 엔진(ToolPDF)만 시작
#   ./singularity.sh start-model          모델 서버(임베딩 + reranker, GPU 프로세스 1개)만 시작
#   ./singularity.sh start-app            앱만 시작
#   ./singularity.sh stop [pdf|model|app] 중지 (생략하면 모두)
#   ./singularity.sh status               상태, 응답, GPU를 잡은 프로세스
#   ./singularity.sh logs pdf|model|app   로그 보기
#
# 설정은 singularity.env (singularity.env.example 을 복사). 자세한 순서는 README.md 의 Singularity 절.
set -e
cd "$(dirname "$0")"
[ -f singularity.env ] || { echo "[오류] singularity.env 가 없습니다. singularity.env.example 을 복사해 고치세요." >&2; exit 1; }
set -a; . ./singularity.env; set +a

SING="${SINGULARITY:-$(command -v apptainer || command -v singularity || true)}"
[ -n "$SING" ] || { echo "[오류] apptainer 나 singularity 명령이 없습니다." >&2; exit 1; }

running() { [ -f "$1.pid" ] && kill -0 "$(cat "$1.pid")" 2>/dev/null; }

start_model() {
  if running model; then echo "모델 서버가 이미 실행 중입니다 (pid $(cat model.pid))."; return; fi
  [ -f "$MODEL_SIF" ] || { echo "[오류] $MODEL_SIF 가 없습니다." >&2; exit 1; }
  for m in "$EMBED_DIR" "$RERANK_DIR"; do
    [ -d "$MODELS_DIR/$m" ] || echo "[경고] 모델 폴더가 없습니다: $MODELS_DIR/$m" >&2
  done
  set -- --embed-model "/models/$EMBED_DIR" --embed-name "${EMBED_NAME:-bge-m3}" \
         --rerank-model "/models/$RERANK_DIR" --rerank-name "${RERANK_NAME:-bge-reranker-v2-m3}" \
         --device "${DEVICE:-cuda}" --port "${MS_PORT:-8090}" --max-batch-tokens "${MAX_BATCH_TOKENS:-16384}"
  [ -n "$MS_API_KEY" ] && set -- "$@" --api-key "$MS_API_KEY"
  NV="--nv"; [ "${DEVICE:-cuda}" = "cpu" ] && NV=""
  nohup "$SING" run $NV --cleanenv --env "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}" \
    --bind "$MODELS_DIR:/models:ro" "$MODEL_SIF" "$@" >> model.log 2>&1 &
  echo $! > model.pid
  echo "모델 서버를 시작했습니다 (pid $!, 포트 ${MS_PORT:-8090}). 모델을 올리는 데 수십 초 걸립니다."
}

start_pdf() {
  if [ "${RAG_PDF_ENGINE:-auto}" = "local" ]; then echo "RAG_PDF_ENGINE=local: ToolPDF 없이 앱 안의 내장 PDF 엔진을 씁니다."; return; fi
  if running pdf; then echo "PDF 엔진이 이미 실행 중입니다 (pid $(cat pdf.pid))."; return; fi
  [ -f "$TOOLPDF_SIF" ] || { echo "[오류] $TOOLPDF_SIF 가 없습니다." >&2; exit 1; }
  mkdir -p "$INGESTLENS_DATA_DIR" "$TOOLPDF_CACHE_DIR"
  # 앱과 같은 데이터 폴더를 /data 로 붙이고 그 안의 상대 경로로 파일을 주고받는다(공유 폴더 방식).
  nohup "$SING" run --cleanenv \
    --bind "$INGESTLENS_DATA_DIR:/data" --bind "$TOOLPDF_CACHE_DIR:/cache" \
    --env TOOLPDF_SHARED_ROOT=/data --env TOOLPDF_CACHE_DIR=/cache --env "TOOLPDF_PORT=${TOOLPDF_PORT:-8095}" \
    --env "TOOLPDF_WORKERS=${TOOLPDF_WORKERS:-4}" --env "TOOLPDF_API_KEY=${TOOLPDF_API_KEY:-}" \
    "$TOOLPDF_SIF" >> pdf.log 2>&1 &
  echo $! > pdf.pid
  [ -n "${TOOLPDF_API_KEY:-}" ] || echo "[경고] TOOLPDF_API_KEY 가 비어 있습니다. 포트 ${TOOLPDF_PORT:-8095} 에 다른 서버가 접속할 수 있다면 키를 정하세요." >&2
  echo "PDF 엔진을 시작했습니다 (pid $!, 포트 ${TOOLPDF_PORT:-8095})."
}

start_app() {
  if running app; then echo "앱이 이미 실행 중입니다 (pid $(cat app.pid))."; return; fi
  [ -f "$APP_SIF" ] || { echo "[오류] $APP_SIF 가 없습니다." >&2; exit 1; }
  mkdir -p "$INGESTLENS_DATA_DIR"
  if [ "${RAG_API_KEY:-}" = "change-me-to-a-long-random-string" ]; then
    echo "[경고] singularity.env 의 RAG_API_KEY 가 기본값입니다. 다른 PC에서 설정 변경·삭제를 막으려면 바꾸세요." >&2
  fi
  nohup "$SING" run --cleanenv \
    --bind "$INGESTLENS_DATA_DIR:/data" --bind "$MODELS_YAML:/config/models.yaml:ro" \
    --env RAG_DATA_DIR=/data --env RAG_SETTINGS_FILE=/data/settings.local.yaml \
    --env RAG_MODELS_FILE=/config/models.yaml --env "RAG_API_KEY=${RAG_API_KEY:-}" --env "RAG_PDF_ENGINE=${RAG_PDF_ENGINE:-auto}" \
    --env "RAG_TOOLPDF_URL=http://127.0.0.1:${TOOLPDF_PORT:-8095}" --env RAG_TOOLPDF_TRANSFER=shared \
    --env "RAG_TOOLPDF_API_KEY=${TOOLPDF_API_KEY:-}" \
    --env "INGESTLENS_PORT=${INGESTLENS_PORT:-8000}" "$APP_SIF" >> app.log 2>&1 &
  echo $! > app.pid
  echo "앱을 시작했습니다 (pid $!). 화면: http://<서버 주소>:${INGESTLENS_PORT:-8000}"
}

stop_one() {
  if running "$1"; then kill "$(cat "$1.pid")"; echo "$1 을(를) 중지했습니다."; else echo "$1 은(는) 실행 중이 아닙니다."; fi
  rm -f "$1.pid"
}

case "${1:-}" in
  start) start_pdf; start_model; start_app ;;
  start-pdf) start_pdf ;;
  start-model) start_model ;;
  start-app) start_app ;;
  stop) if [ -n "${2:-}" ]; then stop_one "$2"; else stop_one app; stop_one model; stop_one pdf; fi ;;
  status)
    for n in pdf model app; do
      if running $n; then echo "$n: 실행 중 (pid $(cat $n.pid))"; else echo "$n: 실행 중 아님"; fi
    done
    if command -v curl >/dev/null 2>&1; then
      if [ "${RAG_PDF_ENGINE:-auto}" = "local" ]; then echo "PDF 엔진:  앱 안의 내장 엔진 (RAG_PDF_ENGINE=local)"
      else echo "PDF 엔진:  $(curl -s "http://127.0.0.1:${TOOLPDF_PORT:-8095}/v1/health" || echo '응답 없음')"; fi
      echo "모델 서버: $(curl -s "http://127.0.0.1:${MS_PORT:-8090}/health" || echo '응답 없음')"
      echo "앱:        $(curl -s "http://127.0.0.1:${INGESTLENS_PORT:-8000}/api/health" || echo '응답 없음')"
    else
      echo "(curl 이 없어 응답 확인을 건너뜁니다. 브라우저로 http://<서버>:${INGESTLENS_PORT:-8000}/#status 를 여세요)"
    fi
    command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv || true
    ;;
  logs) tail -n 50 -f "${2:-app}.log" ;;
  *) sed -n '2,11p' "$0"; exit 1 ;;
esac
