@echo off
rem Baut zwei EXEs, die ohne installiertes Python laufen:
rem   dist\AutoISO-DxOPureRaw.exe      Oberflaeche (ohne Konsolenfenster)
rem   dist\AutoISO-DxOPureRaw-cli.exe  Kommandozeile (Ausgabe und Exit-Code in der Konsole)
rem PyInstaller kommt in eine eigene Build-Umgebung (.venv-build), die System-Python bleibt unberuehrt.
setlocal
cd /d "%~dp0"
set PY=.venv-build\Scripts\python.exe

if not exist "%PY%" (
    echo Lege Build-Umgebung an ...
    python -m venv .venv-build || goto :error
)
"%PY%" -m pip install --upgrade --quiet pip pyinstaller || goto :error

"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "AutoISO-DxOPureRaw" auto_iso_dxo_pureraw.py || goto :error
"%PY%" -m PyInstaller --noconfirm --clean --onefile --console ^
    --name "AutoISO-DxOPureRaw-cli" auto_iso_dxo_pureraw.py || goto :error

echo.
echo Fertig:
echo   %~dp0dist\AutoISO-DxOPureRaw.exe
echo   %~dp0dist\AutoISO-DxOPureRaw-cli.exe
exit /b 0

:error
echo.
echo Build fehlgeschlagen.
exit /b 1
