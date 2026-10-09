@echo off
chcp 65001 >nul
setlocal
rem IngestLens + Open WebUI 시험 환경 (Windows): WSL Ubuntu 안의 Docker Engine 으로
rem   IngestLens 스택(앱, PDF 엔진 ToolPDF, Ollama VLM·임베딩, reranker)과 Open WebUI 를 함께 띄우고 두 화면을 연다.
rem 이미 떠 있는 것은 건너뛴다. 모든 모델이 응답할 때까지 기다린다. 중지: stop_webui_test.bat
rem 준비: WSL 배포판(기본 Ubuntu-24.04)에 Docker Engine 과 NVIDIA Container Toolkit (docs\HANDOFF.md 3-1),
rem       이 폴더 옆에 ToolPDF (..\ToolPDF). 배포판 이름이 다르면 INGESTLENS_WSL_DISTRO 환경 변수로 정한다.
rem 자세히: docs\WINDOWS.md 7절
cd /d "%~dp0"
if not defined INGESTLENS_WSL_DISTRO set "INGESTLENS_WSL_DISTRO=Ubuntu-24.04"
set "WSLD=wsl.exe -d %INGESTLENS_WSL_DISTRO% -u root --cd "%CD%" --"

where wsl.exe >nul 2>nul
if errorlevel 1 (
  echo [오류] wsl.exe 가 없습니다. WSL을 설치하세요.
  goto :fail
)
%WSLD% true >nul 2>nul
if errorlevel 1 (
  echo [오류] WSL 배포판 %INGESTLENS_WSL_DISTRO% 를 시작하지 못했습니다. "wsl -l -v" 로 이름을 확인하세요.
  goto :fail
)

rem 배포판이 막 켜졌으면 systemd 가 Docker를 띄울 때까지 잠시 걸린다.
for /l %%i in (1,1,30) do (
  %WSLD% docker info >nul 2>nul && goto :docker_up
  ping -n 3 127.0.0.1 >nul
)
echo [오류] %INGESTLENS_WSL_DISTRO% 안의 Docker가 준비되지 않았습니다.
goto :fail

:docker_up
rem Windows용 Ollama 가 켜져 있으면 같은 GPU 를 나눠 쓰므로 느려질 수 있다.
netstat -ano | findstr /r /c:"127.0.0.1:11434 .*LISTENING" /c:"0.0.0.0:11434 .*LISTENING" >nul
if not errorlevel 1 echo [참고] Windows용 Ollama 가 실행 중입니다. GPU 메모리가 모자라면 트레이에서 Ollama 를 종료하세요.

%WSLD% bash scripts/webui_test.sh up
if errorlevel 1 goto :fail

echo.
echo 준비 완료
echo   IngestLens : http://localhost:8000      (백엔드 상태: /#status)
echo   Open WebUI : http://localhost:3000      (관리자 계정: admin@example.com)
echo   중지: stop_webui_test.bat
if not defined INGESTLENS_NO_BROWSER (
  start "" http://localhost:8000
  start "" http://localhost:3000
)
exit /b 0

:fail
if not defined INGESTLENS_NO_BROWSER pause
exit /b 1
