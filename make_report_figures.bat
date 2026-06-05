@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "E=%USERPROFILE%\anaconda\envs\satphoto"
if not exist "%E%\python.exe" set "E=%USERPROFILE%\anaconda3\envs\satphoto"
set "PATH=%E%;%E%\Library\bin;%E%\Library\mingw-w64\bin;%E%\Scripts;%PATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
"%E%\python.exe" "%~dp0make_report_figures.py" %*
