@echo off
title SettlementLens Merchant Dashboard
echo ========================================================
echo Starting SettlementLens Merchant Interface...
echo ========================================================
cd /d "%~dp0\.."
python -m gui.app
pause
