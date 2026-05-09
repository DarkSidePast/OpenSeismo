@echo off
title Build Seismic Disaster Tracker EXE
echo Installing requirements...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

echo.
echo Building EXE...
pyinstaller --onefile --name SeismicDisasterTracker --add-data "templates;templates" --add-data "static;static" app.py

echo.
echo Done.
echo Your EXE should be here:
echo dist\SeismicDisasterTracker.exe
pause
