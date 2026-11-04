@echo off
call "%~dp0mif.cmd" wipe %*
exit /b %ERRORLEVEL%
