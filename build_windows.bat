@echo off
REM Build EIA Track for Windows
REM Run this from the project directory

echo ==========================================
echo   Building EIA Track for Windows...
echo ==========================================

REM Clean previous builds
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul

REM Build as a single folder with exe
pyinstaller --name "EIA Track" ^
    --noconsole ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --add-data "Georgia-Financial-Advisors-About.jpg;." ^
    --hidden-import yfinance ^
    --hidden-import reportlab ^
    --hidden-import flask ^
    --clean ^
    app.py

echo.
echo ==========================================
if exist "dist\EIA Track\EIA Track.exe" (
    echo   BUILD SUCCESSFUL!
    echo.
    echo   Your app is at:
    echo   dist\EIA Track\EIA Track.exe
    echo.
    echo   To share with your team:
    echo   1. Zip the "dist\EIA Track" folder
    echo   2. Send the .zip to your team
    echo   3. They unzip it and double-click EIA Track.exe
    echo ==========================================
    explorer "dist\EIA Track"
) else (
    echo   BUILD FAILED - check errors above
    echo ==========================================
)
pause
