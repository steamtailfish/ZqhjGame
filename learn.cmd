@echo off
setlocal
set "ZQHJ_LEARN_PY=%~dp0.venv-learning\Scripts\python.exe"
if not exist "%ZQHJ_LEARN_PY%" (
  echo Missing learning environment. See TRAINING_AND_INFERENCE.md.
  exit /b 2
)
if "%~1"=="train" (
  set "ZQHJ_LEARN_TOOL=train_guidance.py"
) else if "%~1"=="export" (
  set "ZQHJ_LEARN_TOOL=export_guidance.py"
) else if "%~1"=="verify" (
  set "ZQHJ_LEARN_TOOL=verify_guidance.py"
) else (
  echo Usage: learn.cmd train^|export^|verify [options]
  exit /b 2
)
rem Use a Python dispatcher to preserve quoted arguments; batch SHIFT does not change %%*.
"%ZQHJ_LEARN_PY%" -B -X utf8 "%~dp0tools\learning_cli.py" %*
exit /b %ERRORLEVEL%
