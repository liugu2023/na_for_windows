@echo off
REM Nekro-Agent V-OS Multi-Edition ISO Build Script
REM Requires Docker Desktop to be running

echo =========================================
echo    Nekro-Agent V-OS ISO Builder
echo =========================================
echo.

REM Check Docker
docker info >nul 2>&1
if errorlevel 1 (
    echo Error: Docker is not running. Please start Docker Desktop.
    pause
    exit /b 1
)

cd /d "%~dp0"

echo 1/4 Building ISO Builder Image...
docker build -t nekro-iso-builder .

REM Create output directory
if not exist "..\v-core" mkdir "..\v-core"

echo.
echo 2/4 Building: Lite Edition...
docker run --rm ^
    -e BUILD_MODE=lite ^
    -v //var/run/docker.sock:/var/run/docker.sock ^
    -v "%cd%:/compose:ro" ^
    -v "%cd%\..\v-core:/out" ^
    nekro-iso-builder

echo.
echo 3/4 Building: Napcat Edition...
docker run --rm ^
    -e BUILD_MODE=napcat ^
    -v //var/run/docker.sock:/var/run/docker.sock ^
    -v "%cd%:/compose:ro" ^
    -v "%cd%\..\v-core:/out" ^
    nekro-iso-builder

echo.
echo 4/4 All builds completed!
echo.
echo ISO Files:
echo  - ..\v-core\alpine-docker-lite.iso
echo  - ..\v-core\alpine-docker-napcat.iso
echo.
pause
