@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo   Tibia Mapper - Build EXE portable
 echo ========================================

python -m pip install --upgrade pip
if errorlevel 1 goto :error

python -m pip install -r requirements.txt
if errorlevel 1 goto :error

if exist build rmdir /s /q build
if exist dist\tibia-mapper rmdir /s /q dist\tibia-mapper
if exist dist\tibia-mapper-windows-x64.zip del /q dist\tibia-mapper-windows-x64.zip

python -m PyInstaller --noconfirm --clean tibia-mapper.spec
if errorlevel 1 goto :error

for %%D in (routines events checkpoints battle_targets battle_targets\images data logs) do (
    if not exist "dist\tibia-mapper\%%D" mkdir "dist\tibia-mapper\%%D"
)

REM Copia opcional de la configuracion/datos actuales para llevar el mismo estado al otro PC.
if exist settings.json copy /y settings.json dist\tibia-mapper\settings.json >nul
if exist routines xcopy /e /i /y routines dist\tibia-mapper\routines >nul
if exist events xcopy /e /i /y events dist\tibia-mapper\events >nul
if exist checkpoints xcopy /e /i /y checkpoints dist\tibia-mapper\checkpoints >nul
if exist battle_targets xcopy /e /i /y battle_targets dist\tibia-mapper\battle_targets >nul
if exist data xcopy /e /i /y data dist\tibia-mapper\data >nul

> dist\tibia-mapper\LEEME.txt echo Tibia Mapper - paquete portable Windows x64
>> dist\tibia-mapper\LEEME.txt echo.
>> dist\tibia-mapper\LEEME.txt echo 1. Copia esta carpeta completa al PC destino.
>> dist\tibia-mapper\LEEME.txt echo 2. Ejecuta tibia-mapper.exe.
>> dist\tibia-mapper\LEEME.txt echo 3. No requiere Python en el PC destino.
>> dist\tibia-mapper\LEEME.txt echo 4. La captura Battle usa NVIDIA Alt+F1 y espera PNGs en Videos\Desktop.
>> dist\tibia-mapper\LEEME.txt echo 5. No borres las carpetas routines, events, checkpoints, battle_targets, data ni logs si quieres conservar datos.

powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\tibia-mapper\*' -DestinationPath 'dist\tibia-mapper-windows-x64.zip' -Force"
if errorlevel 1 goto :error

 echo.
echo BUILD COMPLETADO
echo Carpeta portable:
echo   %CD%\dist\tibia-mapper
 echo ZIP listo para copiar:
echo   %CD%\dist\tibia-mapper-windows-x64.zip
echo.
pause
exit /b 0

:error
echo.
echo ERROR durante la compilacion.
pause
exit /b 1
