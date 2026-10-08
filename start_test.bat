@echo off
chcp 65001 >nul
setlocal
rem IngestLens 로컬 실행 (Windows): WSL Ubuntu 안의 Docker Engine으로 앱 + Ollama(VLM, 임베딩) + rerank 서버를 띄우고 브라우저를 연다.
rem 준비: WSL 배포판(기본 Ubuntu-24.04)에 Docker Engine과 NVIDIA Container Toolkit (docs\HANDOFF.md 3-1).
rem       배포판 이름이 다르면 INGESTLENS_WSL_DISTRO 환경 변수로 정한다.
rem 첫 실행은 이미지 빌드와 모델 다운로드(약 9.5GB)로 오래 걸린다. 인터넷이 필요하다.
cd /d "%~dp0"
if not defined INGESTLENS_WSL_DISTRO set "INGESTLENS_WSL_DISTRO=Ubuntu-24.04"
rem "%CD%" 는 끝에 \ 가 없어 wsl.exe 가 경로를 제대로 받는다.
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
  %WSLD% docker info >nul 2>nul && goto :up
  "%SystemRoot%\System32\timeout.exe" /t 2 /nobreak >nul
)
echo [오류] %INGESTLENS_WSL_DISTRO% 안의 Docker가 준비되지 않았습니다. "%WSLD% systemctl status docker" 로 확인하세요.
goto :fail

:up
echo 컨테이너를 빌드하고 시작합니다. 첫 실행은 모델을 받느라 오래 걸립니다...
%WSLD% docker compose up -d --build
if errorlevel 1 (
  echo [오류] docker compose 실행에 실패했습니다. 인증서 오류라면 docker\certs\README.md 를 보세요.
  goto :fail
)

echo 앱이 응답할 때까지 기다립니다...
for /l %%i in (1,1,120) do (
  curl -fs http://127.0.0.1:8000/api/health >nul 2>nul && goto :ready
  "%SystemRoot%\System32\timeout.exe" /t 5 /nobreak >nul
)
echo [오류] 10분 안에 앱이 응답하지 않았습니다. "%WSLD% docker compose logs app" 으로 확인하세요.
goto :fail

:ready
echo.
echo IngestLens 준비 완료: http://localhost:8000
echo   VLM 평가 비교 화면: http://localhost:8000/#evals
echo   중지: stop_test.bat
start "" http://localhost:8000
exit /b 0

:fail
pause
exit /b 1
