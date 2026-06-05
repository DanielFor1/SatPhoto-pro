@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "SATPHOTO_ENV=%USERPROFILE%\anaconda\envs\satphoto"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

if exist "%SATPHOTO_ENV%\Library\share\gdal" set "GDAL_DATA=%SATPHOTO_ENV%\Library\share\gdal"
if exist "%SATPHOTO_ENV%\Library\share\proj" set "PROJ_LIB=%SATPHOTO_ENV%\Library\share\proj"
if exist "%SATPHOTO_ENV%\Library\bin" set "PATH=%SATPHOTO_ENV%;%SATPHOTO_ENV%\Library\bin;%SATPHOTO_ENV%\Scripts;%PATH%"

set "PY=%SATPHOTO_ENV%\pythonw.exe"
if not exist "%PY%" set "PY=%SATPHOTO_ENV%\python.exe"
if not exist "%PY%" set "PY=%USERPROFILE%\anaconda\pythonw.exe"
if not exist "%PY%" set "PY=%USERPROFILE%\anaconda\python.exe"
if not exist "%PY%" set "PY=pythonw.exe"

"%PY%" "%~dp0photogrammetry_suite\main.py"
if errorlevel 1 (
    echo Failed to start. Expected environment:
    echo   %SATPHOTO_ENV%
    pause
)
