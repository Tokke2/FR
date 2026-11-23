@echo off
rem Startar Fordonsreg utan att ett terminalfonster blir kvar.
rem PowerShell kors dolt och cmd avslutas direkt nar den startats.
start "" /min powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0start_fordonsreg.ps1"
exit /b 0
