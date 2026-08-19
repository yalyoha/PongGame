@echo off
title PONG
cd /d "%~dp0"
python -c "import pygame" 2>nul
if errorlevel 1 (
    echo Ustanavlivayu pygame-ce, podozhdite...
    python -m pip install --quiet pygame-ce
)
python pong.py
if errorlevel 1 pause
