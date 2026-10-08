@echo off
chcp 65001 >nul
setlocal
rem IngestLens 로컬 실행 중지. 받아 둔 모델(Docker 볼륨)과 data-docker\ 의 문서·결과는 남는다.
cd /d "%~dp0"
if not defined INGESTLENS_WSL_DISTRO set "INGESTLENS_WSL_DISTRO=Ubuntu-24.04"
wsl.exe -d %INGESTLENS_WSL_DISTRO% -u root --cd "%CD%" -- docker compose down
echo 중지했습니다. 다시 시작하려면 start_test.bat
echo WSL(%INGESTLENS_WSL_DISTRO%)은 켜져 있습니다. 메모리를 비우려면: wsl --terminate %INGESTLENS_WSL_DISTRO%
