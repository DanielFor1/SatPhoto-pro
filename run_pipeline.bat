@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem activate satphoto env (LAPACK/MKL DLL, GDAL/PROJ data)
if defined SATPHOTO_ENV (
    set "E=%SATPHOTO_ENV%"
) else (
    set "E=%USERPROFILE%\.conda\envs\model"
)
if not exist "%E%\python.exe" set "E=%USERPROFILE%\anaconda\envs\satphoto"
if not exist "%E%\python.exe" set "E=%USERPROFILE%\anaconda3\envs\satphoto"
set "PATH=%E%;%E%\Library\bin;%E%\Library\mingw-w64\bin;%E%\Scripts;%PATH%"
if exist "%E%\Library\share\gdal" set "GDAL_DATA=%E%\Library\share\gdal"
if exist "%E%\Library\share\proj" set "PROJ_LIB=%E%\Library\share\proj"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"

if not exist "%E%\python.exe" (
    echo Failed to find Python environment.
    echo Set SATPHOTO_ENV to your conda env path, for example:
    echo   set SATPHOTO_ENV=%USERPROFILE%\.conda\envs\model
    pause
    exit /b 1
)

"%E%\python.exe" "%~dp0run_pipeline.py" %*
