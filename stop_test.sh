#!/usr/bin/env sh
# IngestLens 로컬 실행 중지. 받아 둔 모델(Docker 볼륨)과 data-docker/ 의 문서·결과는 남는다.
# Windows Git Bash 에서 docker 명령이 없으면 start_test.sh 처럼 WSL 배포판의 Docker Engine을 쓴다.
cd "$(dirname "$0")"
DISTRO="${INGESTLENS_WSL_DISTRO:-Ubuntu-24.04}"
if command -v docker >/dev/null 2>&1; then
  docker compose down
else
  MSYS_NO_PATHCONV=1 wsl.exe -d "$DISTRO" -u root --cd "$(pwd -W 2>/dev/null || pwd)" -- docker compose down </dev/null
  echo "WSL($DISTRO)은 켜져 있습니다. 메모리를 비우려면: wsl --terminate $DISTRO"
fi
echo "중지했습니다. 다시 시작하려면 ./start_test.sh"
