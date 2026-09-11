@echo off
setlocal
set "ZQHJ_VISION_PY=%~dp0.venv-learning\Scripts\python.exe"
if not exist "%ZQHJ_VISION_PY%" (
  echo Missing learning environment. See TRAINING_AND_INFERENCE.md.
  exit /b 2
)
"%ZQHJ_VISION_PY%" -B -X utf8 "%~dp0tools\vision_cli.py" %*
exit /b %ERRORLEVEL%
