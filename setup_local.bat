@echo off
chcp 65001 >nul
setlocal
rem IngestLens 처음 준비 (Windows, Docker 없이). 한 번만 실행한다. 인터넷이 필요하다.
rem   setup_local.bat          ToolPDF 와 함께 (PDF 처리 품질이 가장 좋다)
rem   setup_local.bat local    ToolPDF 없이, 앱 안의 내장 PDF 엔진만 (MIT 등 퍼미시브 라이선스만, git 불필요)
rem   1. PDF 엔진 ToolPDF 를 이 폴더 옆(..\ToolPDF)에 받는다(없을 때만, git 필요. local 이면 건너뛴다).
rem   2. ToolPDF 와 IngestLens 의 Python 가상환경(.venv)을 만들고 패키지를 설치한다(Python 3.12).
rem   3. 화면(frontend)을 빌드한다(Node.js 필요).
rem 다시 실행해도 된다. 이미 있는 것은 건너뛰고 패키지만 맞춘다. 실행은 start_local.bat. 자세히: docs\WINDOWS.md
cd /d "%~dp0"
if not defined TOOLPDF_DIR set "TOOLPDF_DIR=%~dp0..\ToolPDF"
if /i "%~1"=="local" set "RAG_PDF_ENGINE=local"

set "PY="
py -3.12 --version >nul 2>nul && set "PY=py -3.12"
if not defined PY (
  python --version 2>nul | findstr /b "Python 3.12" >nul && set "PY=python"
)
if not defined PY (
  echo [오류] Python 3.12 가 없습니다. https://www.python.org/downloads/ 에서 3.12 를 설치하세요.
  goto :fail
)
echo Python: %PY%

rem ---- 1. ToolPDF ----
if /i "%RAG_PDF_ENGINE%"=="local" (
  echo ToolPDF 없이 준비합니다: 내장 PDF 엔진을 씁니다. 실행은 start_local.bat local
  goto :app
)
if not exist "%TOOLPDF_DIR%\toolpdf\server.py" (
  where git >nul 2>nul
  if errorlevel 1 (
    echo [오류] %TOOLPDF_DIR% 에 ToolPDF 가 없고 git 도 없습니다.
    echo        https://github.com/kisubkim/ToolPDF 를 받아 그 위치에 풀거나, TOOLPDF_DIR 환경 변수로 위치를 정하세요.
    goto :fail
  )
  echo ToolPDF 를 받습니다: %TOOLPDF_DIR%
  git clone https://github.com/kisubkim/ToolPDF "%TOOLPDF_DIR%"
  if errorlevel 1 goto :fail
)
if not exist "%TOOLPDF_DIR%\.venv\Scripts\python.exe" (
  echo ToolPDF 가상환경을 만듭니다...
  %PY% -m venv "%TOOLPDF_DIR%\.venv"
  if errorlevel 1 goto :fail
)
echo ToolPDF 패키지를 설치합니다...
"%TOOLPDF_DIR%\.venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r "%TOOLPDF_DIR%\requirements.txt"
if errorlevel 1 goto :pipfail

rem ---- 2. IngestLens ----
:app
if not exist ".venv\Scripts\python.exe" (
  echo IngestLens 가상환경을 만듭니다...
  %PY% -m venv .venv
  if errorlevel 1 goto :fail
)
echo IngestLens 패키지를 설치합니다...
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r backend\requirements-dev.txt
if errorlevel 1 goto :pipfail

rem ---- 3. 화면 ----
where npm >nul 2>nul
if errorlevel 1 (
  echo [경고] Node.js 의 npm 이 없어 화면을 빌드하지 못했습니다. https://nodejs.org/ 에서 LTS 를 설치하고 다시 실행하세요.
  echo        화면 없이도 API 는 동작합니다.
  goto :done
)
echo 화면을 빌드합니다...
pushd frontend
call npm ci --no-audit --no-fund
if errorlevel 1 (popd & goto :npmfail)
call npm run build
if errorlevel 1 (popd & goto :npmfail)
popd

:done
echo.
if /i "%RAG_PDF_ENGINE%"=="local" (echo 준비가 끝났습니다. 실행: start_local.bat local) else (echo 준비가 끝났습니다. 실행: start_local.bat)
exit /b 0

:pipfail
echo [오류] pip 설치에 실패했습니다. 사내 프록시나 백신이 HTTPS 를 가로채면 docs\WINDOWS.md 의 "문제 해결"을 보세요.
goto :fail
:npmfail
echo [오류] 화면 빌드에 실패했습니다. 위 메시지를 확인하세요. 인증서 오류면 docs\WINDOWS.md 의 "문제 해결"을 보세요.
:fail
pause
exit /b 1
