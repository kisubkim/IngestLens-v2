@echo off
chcp 65001 >nul
rem start_local.bat 으로 띄운 IngestLens 앱과 ToolPDF 를 끈다. 올린 문서와 결과(data\)는 남는다.
rem 실행 명령(.venv 의 python 으로 띄운 "uvicorn app.main:app", "uvicorn toolpdf.server:app")으로 찾아, 그 창과 하위 프로세스까지 함께 끈다.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$pat = 'uvicorn (toolpdf\.server|app\.main):app';" ^
  "$all = Get-CimInstance Win32_Process;" ^
  "$hit = $all | Where-Object { $_.CommandLine -match $pat -and $_.CommandLine -match '\.venv\\Scripts\\python\.exe' };" ^
  "$ids = @($hit | ForEach-Object { $p = $_; $par = $all | Where-Object { $_.ProcessId -eq $p.ParentProcessId -and $_.Name -eq 'cmd.exe' }; if ($par) { $par.ProcessId } else { $p.ProcessId } }) | Sort-Object -Unique;" ^
  "foreach ($i in $ids) { taskkill /pid $i /t /f | Out-Null };" ^
  "if ($ids) { 'stopped: ' + ($ids -join ', ') } else { 'nothing to stop' }"
echo 중지했습니다. 다시 시작하려면 start_local.bat
