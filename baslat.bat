@echo off
title albion sesli uyari
cd /d "%~dp0"

echo gereksinimler kontrol ediliyor...
python -m pip install -r gereksinimler.txt >nul 2>&1

echo program baslatiliyor...
python app.py
pause
