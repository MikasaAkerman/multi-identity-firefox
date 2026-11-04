@echo off
call "%~dp0mif.cmd" status %*
exit /b %ERRORLEVEL%
