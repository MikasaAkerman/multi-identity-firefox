@echo off
call "%~dp0mif.cmd" new-identity %*
exit /b %ERRORLEVEL%
