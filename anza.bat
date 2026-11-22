@echo off
cd /d "%~dp0"
taskkill /F /FI "WINDOWTITLE eq Seva ya Kanisa*" >nul 2>&1
start "Seva ya Kanisa" /min python -m http.server 5500
timeout /t 2 >nul
start chrome --new-window --disk-cache-size=1 http://localhost:5500/index.html
timeout /t 1 >nul
start chrome --new-window --disk-cache-size=1 http://localhost:5500/tv.html
