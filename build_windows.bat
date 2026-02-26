@echo off
REM ─── Build P2P para Windows ────────────────────────────────────────
REM Genera un ejecutable .exe standalone para Windows usando PyInstaller.
REM Uso: Doble click en build_windows.bat o ejecutar desde CMD
REM ────────────────────────────────────────────────────────────────────

echo.
echo ╔══════════════════════════════════════════════╗
echo ║   P2P File Transfer — Build para Windows     ║
echo ╚══════════════════════════════════════════════╝
echo.

REM Verificar Python
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python no encontrado. Instalalo desde python.org
    echo         Asegurate de marcar "Add Python to PATH" al instalar.
    pause
    exit /b 1
)

REM Instalar PyInstaller
echo ● Verificando PyInstaller...
python -m pip install --quiet pyinstaller

REM Instalar dependencias del control remoto
echo ● Instalando dependencias de Remote Desktop...
python -m pip install --quiet mss Pillow pyautogui

REM Generar icono .ico si no existe
if not exist "logo.ico" (
    if exist "logo.png" (
        echo ● Generando icono Windows (logo.ico)...
        python -c "from PIL import Image; img=Image.open('logo.png'); img.save('logo.ico', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
    )
)

REM Limpiar builds anteriores
echo ● Limpiando builds anteriores...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist *.spec del /q *.spec

REM Determinar flag de icono
set ICON_FLAG=
if exist "logo.ico" (
    set ICON_FLAG=--icon=logo.ico
    echo ● Usando icono: logo.ico
)

REM Construir
echo ● Compilando P2P Terminal...
python -m PyInstaller ^
    --onefile ^
    --name "P2P" ^
    --clean ^
    --noconfirm ^
    --console ^
    %ICON_FLAG% ^
    --hidden-import=mss ^
    --hidden-import=PIL ^
    --hidden-import=PIL.Image ^
    --hidden-import=PIL.ImageTk ^
    --hidden-import=pyautogui ^
    --hidden-import=tkinter ^
    --hidden-import=pyscreeze ^
    --hidden-import=pygetwindow ^
    --hidden-import=pymsgbox ^
    --hidden-import=pytweening ^
    --hidden-import=mouseinfo ^
    --collect-all mss ^
    p2p.py

echo.
echo ✔ Build completado exitosamente
echo.
echo   El ejecutable esta en: dist\P2P.exe
echo   Para ejecutar:  dist\P2P.exe
echo.

REM Limpiar archivos temporales de build
if exist build rmdir /s /q build
if exist *.spec del /q *.spec
echo ● Archivos temporales limpiados
echo.
pause
