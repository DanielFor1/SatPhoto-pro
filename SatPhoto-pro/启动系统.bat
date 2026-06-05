@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "SATPHOTO_ENV=%USERPROFILE%\anaconda\envs\satphoto"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "QT_AUTO_SCREEN_SCALE_FACTOR=1"
set "QT_ENABLE_HIGHDPI_SCALING=1"

if exist "%SATPHOTO_ENV%\Library\share\gdal" set "GDAL_DATA=%SATPHOTO_ENV%\Library\share\gdal"
if exist "%SATPHOTO_ENV%\Library\share\proj" set "PROJ_LIB=%SATPHOTO_ENV%\Library\share\proj"
if exist "%SATPHOTO_ENV%\Library\bin" set "PATH=%SATPHOTO_ENV%;%SATPHOTO_ENV%\Library\bin;%SATPHOTO_ENV%\Scripts;%PATH%"

set "PYW="
set "PY="
if exist "%SATPHOTO_ENV%\pythonw.exe" set "PYW=%SATPHOTO_ENV%\pythonw.exe"
if exist "%SATPHOTO_ENV%\python.exe" set "PY=%SATPHOTO_ENV%\python.exe"

if not defined PYW if exist "%USERPROFILE%\anaconda3\pythonw.exe" set "PYW=%USERPROFILE%\anaconda3\pythonw.exe"
if not defined PY if exist "%USERPROFILE%\anaconda3\python.exe" set "PY=%USERPROFILE%\anaconda3\python.exe"
if not defined PYW if exist "%USERPROFILE%\anaconda\pythonw.exe" set "PYW=%USERPROFILE%\anaconda\pythonw.exe"
if not defined PY if exist "%USERPROFILE%\anaconda\python.exe" set "PY=%USERPROFILE%\anaconda\python.exe"
if not defined PYW where pythonw >nul 2>&1 && for /f "delims=" %%i in ('where pythonw 2^>nul') do set "PYW=%%i" & goto :launch
if not defined PY where python >nul 2>&1 && for /f "delims=" %%i in ('where python 2^>nul') do set "PY=%%i" & goto :launch_py

:launch
if exist "%PYW%" (
    start "" "%PYW%" "%~dp0photogrammetry_suite\qt_app\main.py"
    exit /b 0
)

:launch_py
if exist "%PY%" (
    start "" "%PY%" "%~dp0photogrammetry_suite\qt_app\main.py"
    exit /b 0
)

echo Failed to start SatPhoto-Pro.
echo Please create/install the environment first, then run this file again:
echo   %USERPROFILE%\anaconda\envs\satphoto\python.exe
pause
exit /b 1
