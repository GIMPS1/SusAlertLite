@echo off
setlocal
cd /d %~dp0
py -3 -m pip install --upgrade pip
py -3 -m pip install -r requirements.txt
py -3 -m pip install pyinstaller
py -3 -m PyInstaller --noconsole --onefile --name SusAlertLite susalert_lite.py
echo.
echo Built: dist\SusAlertLite.exe
pause
