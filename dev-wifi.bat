@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" goto build
.venv\Scripts\python.exe -c "import fastapi, uvicorn, openpyxl, reportlab" 1>nul 2>nul
if errorlevel 1 goto rebuild
goto net

:rebuild
echo [PONUDE] Postojeci .venv ne radi na ovom racunalu - ponovo gradim...
rmdir /s /q ".venv" 2>nul

:build
echo [PONUDE] Kreiram okruzenje i instaliram ovisnosti...
py -3 -m venv .venv
if errorlevel 1 goto nopy
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt

:net
rem Ako neka stara instanca vec drzi port 8010, ugasi je (sprjecava gresku 10048).
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":8010 .*LISTENING"') do (
    echo [PONUDE] Gasim staru instancu na portu 8010 - PID %%p ...
    taskkill /f /pid %%p 1>nul 2>nul
)

set "IP="
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do if not defined IP set "IP=%%a"
if defined IP set "IP=%IP: =%"

echo.
echo Pokrecem PONUDE server (mreza)...
echo   Lokalno:  http://localhost:8010
if defined IP echo   Mreza:    http://%IP%:8010
echo.
echo Sve IPv4 adrese ovog racunala:
ipconfig | findstr /c:"IPv4"
echo.
echo NAPOMENA: Ako drugi uredjaj ne moze pristupiti, pokreni JEDNOM kao Administrator:
echo   netsh advfirewall firewall add rule name="Ponude 8010" dir=in action=allow protocol=TCP localport=8010
echo.

.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8010
pause
goto :eof

:nopy
echo.
echo GRESKA: Python nije pronadjen. Instaliraj Python 3 (Add to PATH) pa pokreni ponovno.
echo.
pause
