@echo off
:: ==========================================================
:: SCRIPT OTOMATIS RUN AS ADMINISTRATOR UNTUK BOT VD
:: ==========================================================
>nul 2>&1 "%SYSTEMROOT%\system32\cacls.exe" "%SYSTEMROOT%\system32\config\system"

if '%errorlevel%' NEQ '0' (
    echo Meminta izin Administrator...
    goto UACPrompt
) else ( goto gotAdmin )

:UACPrompt
    echo Set UAC = CreateObject^("Shell.Application"^) > "%temp%\getadmin.vbs"
    echo UAC.ShellExecute "%~s0", "", "", "runas", 1 >> "%temp%\getadmin.vbs"
    "%temp%\getadmin.vbs"
    exit /B

:gotAdmin
    if exist "%temp%\getadmin.vbs" ( del "%temp%\getadmin.vbs" )
    pushd "%CD%"
    CD /D "%~dp0"

:: ==========================================================
:: MENJALANKAN SKRIP PYTHON BOT ANDA
:: ==========================================================
echo ==========================================================
echo  MENJALANKAN BOT SKILL CHECK VIOLENCE DISTRICT...
echo ==========================================================
python main.py
pause