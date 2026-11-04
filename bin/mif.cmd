@echo off
rem Entry point on Windows. All logic lives in the mif Python package.
setlocal
pushd "%~dp0.."
if defined MIF_PYTHON goto run_custom
if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\python.exe" goto run_conda
where py >nul 2>nul
if %ERRORLEVEL%==0 goto run_py
goto run_python

:run_custom
if not exist "%MIF_PYTHON%" (
  echo MIF_PYTHON does not exist: %MIF_PYTHON% 1>&2
  set "RC=1"
  goto done
)
"%MIF_PYTHON%" -m mif %*
goto capture_rc

:run_conda
"%CONDA_PREFIX%\python.exe" -m mif %*
goto capture_rc

:run_py
py -3 -m mif %*
goto capture_rc

:run_python
python -m mif %*

:capture_rc
set "RC=%ERRORLEVEL%"

:done
popd
exit /b %RC%
