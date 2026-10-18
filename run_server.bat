@echo off
title YT Premiere Importer - Local Downloader Service
cd /d "%~dp0downloader"
echo ========================================================
echo Starting YT Premiere Importer Downloader Service...
echo Host: http://127.0.0.1:8000
echo ========================================================
".venv\Scripts\python.exe" server.py
pause
