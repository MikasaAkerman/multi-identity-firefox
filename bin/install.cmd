@echo off
call "%~dp0mif.cmd" install %*
exit /b %ERRORLEVEL%
