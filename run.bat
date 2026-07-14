@echo off
cd /d "%~dp0"
rem Ako neka stara instanca vec drzi port 8010, ugasi je (sprjecava gresku 10048).
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":8010 .*LISTENING"') do (
    echo Gasim staru instancu na portu 8010 - PID %%p ...
    taskkill /f /pid %%p 1>nul 2>nul
)
echo Pokrecem Ponude-app na http://127.0.0.1:8010 ...
start "" http://127.0.0.1:8010
.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8010
