@echo off
setlocal
if defined ZQHJ_PYTHON (
  set "ZQHJ_EXE=%ZQHJ_PYTHON%"
) else if exist "%~dp0.venv\Scripts\python.exe" (
  set "ZQHJ_EXE=%~dp0.venv\Scripts\python.exe"
) else (
  set "ZQHJ_EXE=%~dp0..\python\python.exe"
)
if not exist "%ZQHJ_EXE%" exit /b 2
"%ZQHJ_EXE%" -B -X utf8 "%~dp0tools\run_perception_probe.py" %*
exit /b %ERRORLEVEL%
