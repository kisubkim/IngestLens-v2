@echo off
chcp 65001 >nul
setlocal
rem start_webui_test.bat 으로 띄운 Open WebUI 와 IngestLens 스택을 중지한다.
rem 받아 둔 모델, data-docker\ 의 문서, Open WebUI 의 계정·지식 베이스는 남는다.
cd /d "%~dp0"
if not defined INGESTLENS_WSL_DISTRO set "INGESTLENS_WSL_DISTRO=Ubuntu-24.04"
wsl.exe -d %INGESTLENS_WSL_DISTRO% -u root --cd "%CD%" -- bash scripts/webui_test.sh down
echo 다시 시작하려면 start_webui_test.bat
echo WSL(%INGESTLENS_WSL_DISTRO%)은 켜져 있습니다. 메모리를 비우려면: wsl --terminate %INGESTLENS_WSL_DISTRO%
