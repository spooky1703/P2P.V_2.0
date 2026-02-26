#!/bin/bash
# ─── Build P2P para macOS ─────────────────────────────────────────────
# Genera un ejecutable standalone para macOS usando PyInstaller.
# Uso: chmod +x build_mac.sh && ./build_mac.sh

set -e

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   P2P File Transfer — Build para macOS   ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Verificar Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 no encontrado. Instálalo desde python.org"
    exit 1
fi

# Instalar PyInstaller si no existe
echo "● Verificando PyInstaller..."
python3 -m pip install --quiet pyinstaller

# Instalar dependencias del control remoto
echo "● Instalando dependencias de Remote Desktop..."
python3 -m pip install --quiet mss Pillow pyautogui

# Crear icono .icns si no existe
if [ ! -f "logo.icns" ] && [ -f "logo.png" ]; then
    echo "● Generando icono macOS (logo.icns)..."
    mkdir -p /tmp/p2p_icon.iconset
    sips -z 1024 1024 logo.png --out /tmp/p2p_icon.iconset/icon_512x512@2x.png > /dev/null 2>&1
    sips -z 512 512 logo.png --out /tmp/p2p_icon.iconset/icon_512x512.png > /dev/null 2>&1
    sips -z 256 256 logo.png --out /tmp/p2p_icon.iconset/icon_256x256.png > /dev/null 2>&1
    sips -z 128 128 logo.png --out /tmp/p2p_icon.iconset/icon_128x128.png > /dev/null 2>&1
    sips -z 64 64 logo.png --out /tmp/p2p_icon.iconset/icon_32x32@2x.png > /dev/null 2>&1
    sips -z 32 32 logo.png --out /tmp/p2p_icon.iconset/icon_32x32.png > /dev/null 2>&1
    sips -z 16 16 logo.png --out /tmp/p2p_icon.iconset/icon_16x16.png > /dev/null 2>&1
    iconutil -c icns /tmp/p2p_icon.iconset -o logo.icns
    rm -rf /tmp/p2p_icon.iconset
fi

# Limpiar builds anteriores
echo "● Limpiando builds anteriores..."
rm -rf build/ dist/ *.spec

# Determinar flag de icono
ICON_FLAG=""
if [ -f "logo.icns" ]; then
    ICON_FLAG="--icon=logo.icns"
    echo "● Usando icono: logo.icns"
fi

# Construir
echo "● Compilando P2P Terminal..."
python3 -m PyInstaller \
    --onefile \
    --name "P2P" \
    --clean \
    --noconfirm \
    --console \
    $ICON_FLAG \
    --hidden-import=mss \
    --hidden-import=PIL \
    --hidden-import=PIL.Image \
    --hidden-import=PIL.ImageTk \
    --hidden-import=pyautogui \
    --hidden-import=tkinter \
    --hidden-import=pyscreeze \
    --hidden-import=pygetwindow \
    --hidden-import=pymsgbox \
    --hidden-import=pytweening \
    --hidden-import=mouseinfo \
    --collect-all mss \
    p2p.py

echo ""
echo "✔ Build completado exitosamente"
echo ""
echo "  El ejecutable está en: dist/P2P"
echo "  Para ejecutar:  ./dist/P2P"
echo ""

# Limpiar archivos temporales de build
rm -rf build/ *.spec
echo "● Archivos temporales limpiados"
echo ""
