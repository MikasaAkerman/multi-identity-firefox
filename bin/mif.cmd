@echo off
rem Entry point on Windows. All logic lives in the mif Python package.
setlocal
pushd "%~dp0.."
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 -m mif %*
) else (
  python -m mif %*
)
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
