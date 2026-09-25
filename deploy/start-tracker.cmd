@echo off
rem Starts TCG Tracker (used by the scheduled task; can also be double-clicked).
cd /d "%~dp0.."
set PYTHONUTF8=1
".venv\Scripts\python.exe" run.py
