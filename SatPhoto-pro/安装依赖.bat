@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

set "SATPHOTO_ENV=%USERPROFILE%\anaconda\envs\satphoto"

echo ========================================
echo  SatPhoto-Pro environment setup
echo ========================================
echo.

where conda >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Conda was not found in PATH.
    echo Please install Anaconda or Miniconda first.
    pause
    exit /b 1
)

if exist "%SATPHOTO_ENV%\python.exe" (
    echo Existing environment found:
    echo   %SATPHOTO_ENV%
) else (
    echo Creating environment:
    echo   %SATPHOTO_ENV%
    conda create -p "%SATPHOTO_ENV%" --override-channels -c conda-forge --solver libmamba ^
        python=3.11 numpy scipy opencv matplotlib tifffile pandas rasterio gdal pillow ^
        onnxruntime python-docx pyqt=5.15 pip -y
    if errorlevel 1 (
        echo [ERROR] Conda environment creation failed.
        pause
        exit /b 1
    )
)

echo.
echo Installing pip-only packages...
"%SATPHOTO_ENV%\python.exe" -m pip install --upgrade pip -q
"%SATPHOTO_ENV%\python.exe" -m pip install pygeodesy
if errorlevel 1 (
    echo [ERROR] pip package installation failed.
    pause
    exit /b 1
)

echo.
echo Verifying imports...
if exist "%SATPHOTO_ENV%\Library\share\gdal" set "GDAL_DATA=%SATPHOTO_ENV%\Library\share\gdal"
if exist "%SATPHOTO_ENV%\Library\share\proj" set "PROJ_LIB=%SATPHOTO_ENV%\Library\share\proj"
if exist "%SATPHOTO_ENV%\Library\bin" set "PATH=%SATPHOTO_ENV%;%SATPHOTO_ENV%\Library\bin;%SATPHOTO_ENV%\Scripts;%PATH%"
"%SATPHOTO_ENV%\python.exe" -c "import numpy, scipy, cv2, matplotlib, tifffile, pandas, rasterio, PyQt5, osgeo, pygeodesy, PIL, onnxruntime, docx; print('ALL_IMPORTS_OK')"
if errorlevel 1 (
    echo [ERROR] Import verification failed.
    pause
    exit /b 1
)

echo.
echo ========================================
echo  Setup complete. Run:
echo   启动系统.bat
echo ========================================
pause
