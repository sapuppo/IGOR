@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 run.py --brain auto --cycles 0 --interval 900
) else (
  python run.py --brain auto --cycles 0 --interval 900
)
pause
