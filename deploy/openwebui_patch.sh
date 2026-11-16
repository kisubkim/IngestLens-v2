#!/usr/bin/env sh
# Docker로 도는 Open WebUI 컨테이너에 openwebui_patch.py 를 적용한다 (OPENWEBUI.md 12절).
#   ./openwebui_patch.sh [컨테이너 이름]            패치 후 컨테이너 재시작 (기본 이름 open-webui)
#   ./openwebui_patch.sh [컨테이너 이름] --check    상태만 본다
#   ./openwebui_patch.sh [컨테이너 이름] --revert   되돌리고 재시작
# 컨테이너를 새로 만들면(이미지 교체, docker rm) 패치가 사라진다. 다시 실행하거나 docker commit 으로 이미지를 남긴다.
set -eu
cd "$(dirname "$0")"
NAME="${1:-open-webui}"
MODE="${2:-}"
case "$MODE" in ""|--check|--revert) ;; *) echo "[오류] 알 수 없는 옵션: $MODE" >&2; exit 1 ;; esac

docker inspect "$NAME" >/dev/null 2>&1 || { echo "[오류] 컨테이너 $NAME 이 없습니다. docker ps 로 이름을 확인하세요." >&2; exit 1; }
docker cp openwebui_patch.py "$NAME":/tmp/openwebui_patch.py
docker exec "$NAME" python3 /tmp/openwebui_patch.py $MODE
docker exec "$NAME" rm -f /tmp/openwebui_patch.py
if [ "$MODE" != "--check" ]; then
  docker restart "$NAME" >/dev/null
  echo "$NAME 을 다시 시작했습니다. 로그: docker logs -f $NAME"
fi
