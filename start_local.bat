@echo off
chcp 65001 >nul
setlocal
rem IngestLens 실행 (Windows, Docker 없이): PDF 엔진 ToolPDF 와 앱을 각각 창 하나로 띄우고 브라우저를 연다.
rem   start_local.bat          ToolPDF 와 함께. ToolPDF 가 준비되지 않았으면 앱만 띄우고 내장 PDF 엔진을 쓴다(auto)
rem   start_local.bat local    ToolPDF 없이 앱만 띄운다(내장 PDF 엔진, RAG_PDF_ENGINE=local)
rem 먼저 setup_local.bat 을 한 번 실행한다. 중지는 stop_local.bat 또는 창을 닫는다. 자세히: docs\WINDOWS.md
rem 환경 변수로 바꿀 수 있는 것:
rem   TOOLPDF_DIR      ToolPDF 폴더 (기본: 이 폴더 옆 ..\ToolPDF)
rem   INGESTLENS_PORT  앱 포트 (기본 8000)        TOOLPDF_PORT  ToolPDF 포트 (기본 8095)
rem   INGESTLENS_HOST  앱이 받을 주소 (기본 127.0.0.1 = 이 PC만. 다른 PC에서 접속하려면 0.0.0.0, 그때는 .env 에 RAG_API_KEY)
rem 모델 주소, API 키 등 앱 설정은 이 폴더의 .env 에 적는다(RAG_MODELS_FILE 등, docs\WINDOWS.md).
cd /d "%~dp0"
if not defined TOOLPDF_DIR set "TOOLPDF_DIR=%~dp0..\ToolPDF"
if not defined INGESTLENS_PORT set "INGESTLENS_PORT=8000"
if not defined TOOLPDF_PORT set "TOOLPDF_PORT=8095"
if not defined INGESTLENS_HOST set "INGESTLENS_HOST=127.0.0.1"
if /i "%~1"=="local" set "RAG_PDF_ENGINE=local"

if not exist ".venv\Scripts\python.exe" goto :nosetup
if not exist "frontend\dist\index.html" echo [경고] 화면이 빌드되지 않았습니다(frontend\dist). setup_local.bat 을 실행하세요. API 만 동작합니다.

netstat -ano | findstr /r /c:":%INGESTLENS_PORT% .*LISTENING" >nul
if not errorlevel 1 (
  echo [오류] 포트 %INGESTLENS_PORT% 를 이미 다른 프로그램이 쓰고 있습니다. 실행 중인 IngestLens 가 있으면 stop_local.bat 으로 끄거나,
  echo        INGESTLENS_PORT 로 다른 포트를 정하세요. 예: set INGESTLENS_PORT=8100
  goto :fail
)

rem ---- ToolPDF ----
if /i "%RAG_PDF_ENGINE%"=="local" (
  echo ToolPDF 없이 실행합니다: 내장 PDF 엔진을 씁니다.
  goto :app
)
if not exist "%TOOLPDF_DIR%\.venv\Scripts\python.exe" (
  echo [안내] %TOOLPDF_DIR% 에 준비된 ToolPDF 가 없어 앱만 띄웁니다. 내장 PDF 엔진으로 처리합니다.
  echo        ToolPDF 를 쓰려면 setup_local.bat 을 실행하세요.
  goto :app
)
curl -fs http://127.0.0.1:%TOOLPDF_PORT%/v1/health >nul 2>nul
if not errorlevel 1 (
  echo ToolPDF 가 이미 포트 %TOOLPDF_PORT% 에서 실행 중입니다. 그대로 씁니다.
  goto :app
)
echo ToolPDF 를 시작합니다 (포트 %TOOLPDF_PORT%)...
rem ToolPDF 폴더에서 실행해야 그 폴더의 toolpdf.toml(있으면)을 읽는다.
start "ToolPDF" /d "%TOOLPDF_DIR%" cmd /k ""%TOOLPDF_DIR%\.venv\Scripts\python.exe" -m uvicorn toolpdf.server:app --host 127.0.0.1 --port %TOOLPDF_PORT%"
for /l %%i in (1,1,60) do (
  curl -fs http://127.0.0.1:%TOOLPDF_PORT%/v1/health >nul 2>nul && goto :app
  ping -n 2 127.0.0.1 >nul
)
echo [오류] ToolPDF 가 60초 안에 응답하지 않았습니다. "ToolPDF" 창의 메시지를 확인하세요.
goto :fail

:app
echo IngestLens 를 시작합니다 (포트 %INGESTLENS_PORT%)...
set "RAG_TOOLPDF_URL=http://127.0.0.1:%TOOLPDF_PORT%"
start "IngestLens" /d "%~dp0backend" cmd /k ""%~dp0.venv\Scripts\python.exe" -m uvicorn app.main:app --host %INGESTLENS_HOST% --port %INGESTLENS_PORT%"
for /l %%i in (1,1,60) do (
  curl -fs http://127.0.0.1:%INGESTLENS_PORT%/api/health >nul 2>nul && goto :ready
  ping -n 2 127.0.0.1 >nul
)
echo [오류] 앱이 60초 안에 응답하지 않았습니다. "IngestLens" 창의 메시지를 확인하세요.
goto :fail

:ready
echo.
echo IngestLens 준비 완료: http://localhost:%INGESTLENS_PORT%
echo   백엔드 상태: http://localhost:%INGESTLENS_PORT%/#status
echo   중지: stop_local.bat (또는 "ToolPDF", "IngestLens" 창 닫기)
echo   PDF 엔진: 화면의 백엔드 상태에서 확인 (ToolPDF 또는 내장)
if not defined INGESTLENS_NO_BROWSER start "" http://localhost:%INGESTLENS_PORT%
exit /b 0

:nosetup
echo [오류] 아직 준비되지 않았습니다. 먼저 setup_local.bat 을 실행하세요.
:fail
if not defined INGESTLENS_NO_BROWSER pause
exit /b 1
