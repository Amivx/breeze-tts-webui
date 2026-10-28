@echo off
rem Thin launcher: hands over to PowerShell, which handles UTF-8 output and
rem argument parsing reliably (cmd.exe + chcp 65001 mangles non-ASCII output).
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-webui.ps1" %*
endlocal