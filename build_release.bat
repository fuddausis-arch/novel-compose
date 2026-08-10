@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo  NovelCompose Release Builder
echo ============================================
echo.

REM ---- Check environment ----
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.11+
    exit /b 1
)

where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Please install Node.js 18+
    exit /b 1
)

REM ---- Use China mirrors to avoid Electron download timeout ----
set ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/
set ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/

echo [1/5] Checking PyInstaller...
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo       Installing PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] PyInstaller install failed
        exit /b 1
    )
)

echo [2/5] Building frontend dist...
cd frontend
call npm run build
if errorlevel 1 (
    echo [ERROR] Frontend build failed
    cd ..
    exit /b 1
)
cd ..

echo [3/5] PyInstaller packaging backend...
python -m PyInstaller novel_agent.spec --noconfirm --clean
if errorlevel 1 (
    echo [ERROR] Backend packaging failed
    exit /b 1
)

echo [4/5] Copying frontend dist into backend dir...
xcopy /E /I /Y "frontend\dist" "dist\novel-agent-server\frontend\dist" >nul
if errorlevel 1 (
    echo [ERROR] Copy frontend dist failed
    exit /b 1
)

echo [5/5] electron-builder packaging installer...
cd frontend
call npx electron-builder --win -c.directories.output=../release5
if errorlevel 1 (
    echo [ERROR] Electron builder failed
    cd ..
    exit /b 1
)
cd ..

echo.
echo ============================================
echo  Build complete!
echo  Installer location: release5\
echo ============================================
echo.
echo  Usage for your friend:
echo  1. Install release5\NovelCompose Setup *.exe
echo  2. Launch from desktop shortcut
echo  3. API key is built-in, no extra config
echo.
