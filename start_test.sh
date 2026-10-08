#!/usr/bin/env sh
# IngestLens 로컬 실행: 앱 + Ollama(VLM, 임베딩) + rerank 서버를 Docker로 띄운다.
# - Linux, macOS, WSL 안: 그 환경의 docker 를 쓴다.
# - Windows Git Bash: docker 명령이 없으면 WSL 배포판(기본 Ubuntu-24.04, INGESTLENS_WSL_DISTRO)의 Docker Engine을 쓴다.
# 첫 실행은 이미지 빌드와 모델 다운로드(약 9.5GB)로 오래 걸린다. 인터넷과 NVIDIA GPU(컨테이너 툴킷)가 필요하다.
set -e
cd "$(dirname "$0")"
DISTRO="${INGESTLENS_WSL_DISTRO:-Ubuntu-24.04}"

if command -v docker >/dev/null 2>&1; then
  dk() { docker "$@"; }
  WHERE="docker"
elif command -v wsl.exe >/dev/null 2>&1; then
  WIN_DIR="$(pwd -W 2>/dev/null || pwd)"
  dk() { MSYS_NO_PATHCONV=1 wsl.exe -d "$DISTRO" -u root --cd "$WIN_DIR" -- docker "$@" </dev/null; }
  WHERE="WSL $DISTRO"
else
  echo "[오류] docker 명령도 wsl.exe 도 없습니다. Docker를 설치하세요." >&2
  exit 1
fi

i=0
until dk info >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 30 ]; then
    echo "[오류] Docker 데몬($WHERE)이 실행 중이 아닙니다. Docker를 시작한 뒤 다시 실행하세요." >&2
    exit 1
  fi
  sleep 2
done

echo "컨테이너를 빌드하고 시작합니다($WHERE). 첫 실행은 모델을 받느라 오래 걸립니다..."
if ! dk compose up -d --build; then
  echo "[오류] docker compose 실행에 실패했습니다. 인증서 오류라면 docker/certs/README.md 를 보세요." >&2
  exit 1
fi

echo "앱이 응답할 때까지 기다립니다..."
i=0
until curl -fs http://127.0.0.1:8000/api/health >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 120 ]; then
    echo "[오류] 10분 안에 앱이 응답하지 않았습니다. 'docker compose logs app' 으로 확인하세요." >&2
    exit 1
  fi
  sleep 5
done

echo
echo "IngestLens 준비 완료: http://localhost:8000"
echo "  VLM 평가 비교 화면: http://localhost:8000/#evals"
echo "  중지: ./stop_test.sh"
if command -v xdg-open >/dev/null 2>&1; then xdg-open http://localhost:8000 >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then open http://localhost:8000 || true
elif command -v cmd.exe >/dev/null 2>&1; then cmd.exe //c start "" http://localhost:8000 || true
fi
