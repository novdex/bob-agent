@echo off
echo ============================================
echo  BOBCHAT WEB - Starting Server...
echo ============================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed!
    echo Please install Python from https://python.org
    pause
    exit /b 1
)

REM Install requirements if needed
if not exist "installed.flag" (
    echo Installing required packages...
    pip install -r requirements.txt
    echo. > installed.flag
    echo Packages installed!
    echo.
)

echo Starting BobChat Server...
echo.
echo ============================================
echo  CHAT LINKS:
echo ============================================
echo  Your Link: http://localhost:5000
echo.
echo  To share with friend on same WiFi:
echo  1. Find your IP: Open Command Prompt
echo  2. Type: ipconfig
echo  3. Look for "IPv4 Address"
echo  4. Share: http://YOUR_IP:5000
echo.
echo  For internet access, install ngrok:
echo  https://ngrok.com/download
echo  Then run: ngrok http 5000
echo ============================================
echo.

python app.py

pause
