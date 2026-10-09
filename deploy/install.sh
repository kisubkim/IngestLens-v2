#!/usr/bin/env sh
# 오프라인 서버에서 배포 묶음을 설치·시작한다. 인터넷이 필요 없다.
#   ./install.sh    이미지 불러오기 + 앱과 PDF 엔진(ToolPDF, 들어 있는 묶음만) 시작. 모델 서버는 model-server.sh 로 따로 띄운다(README.md).
set -e
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "[오류] docker 와 docker compose 플러그인이 필요합니다 (Docker Engine 24 이상)." >&2
  exit 1
fi

[ -f .env ] || { echo "[오류] .env 가 없습니다. .env.example 을 복사해 고치세요." >&2; exit 1; }
if grep -q "^RAG_API_KEY=change-me" .env; then
  echo "[경고] .env 의 RAG_API_KEY 가 기본값입니다. 다른 PC에서 설정 변경·삭제를 막으려면 바꾸세요." >&2
fi

if [ -f SHA256SUMS ] && command -v sha256sum >/dev/null 2>&1; then
  echo "파일 무결성을 확인합니다..."
  sha256sum -c --quiet SHA256SUMS
fi

for img in images/*.tar.gz toolpdf/*-docker.tar.gz; do
  [ -e "$img" ] || continue
  echo "이미지 불러오기: $img"
  docker load -i "$img"
done

set -a; . ./.env; set +a

if grep -q "<VLM 서버 주소>\|<vLLM 의" models.yaml; then
  echo "[경고] models.yaml 의 VLM 주소와 모델 이름을 아직 적지 않았습니다. 스캔·그림 페이지는 PDF 텍스트로만 처리됩니다." >&2
fi

docker compose up -d
echo
echo "시작했습니다. 상태 확인: curl http://localhost:${INGESTLENS_PORT:-8000}/api/health"
if [ "${RAG_PDF_ENGINE:-auto}" = "local" ]; then
  echo "화면: http://<서버 주소>:${INGESTLENS_PORT:-8000}  · 백엔드 상태: /#status  · 로그: docker compose logs -f app (PDF 엔진: 앱 안의 내장 엔진)"
else
  echo "화면: http://<서버 주소>:${INGESTLENS_PORT:-8000}  · 백엔드 상태: /#status  · 로그: docker compose logs -f app (PDF 엔진: toolpdf)"
fi
