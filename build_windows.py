import os
import sys
import subprocess
import shutil
from pathlib import Path

def print_banner():
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║   P2P File Transfer — Build para Windows     ║")
    print("╚══════════════════════════════════════════════╝")
    print()

def run_cmd(cmd, desc):
    print(f"● {desc}...")
    try:
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Falló: {' '.join(cmd)}")
        return False

def main():
    print_banner()

    # 1. Instalar dependencias
    deps = ["pyinstaller", "mss", "Pillow", "pyautogui"]
    for dep in deps:
        run_cmd([sys.executable, "-m", "pip", "install", "--quiet", dep], f"Instalando {dep}")

    # 2. Generar Icono
    icon_flag = ""
    if not os.path.exists("logo.ico") and os.path.exists("logo.png"):
        print("● Generando icono Windows (logo.ico)...")
        try:
            from PIL import Image
            img = Image.open("logo.png")
            img.save("logo.ico", format="ICO", sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
        except Exception as e:
            print(f"[WARNING] No se pudo generar logo.ico: {e}")
            
    if os.path.exists("logo.ico"):
        icon_flag = "--icon=logo.ico"
        print("● Usando icono: logo.ico")

    # 3. Limpiar builds anteriores
    print("● Limpiando builds anteriores...")
    shutil.rmtree("build", ignore_errors=True)
    shutil.rmtree("dist", ignore_errors=True)
    for p in Path(".").glob("*.spec"):
        p.unlink()

    # 4. Compilar
    print("● Compilando P2P Terminal (esto puede tomar un minuto)...")
    pyinstaller_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name=P2P",
        "--clean",
        "--noconfirm",
        "--console"
    ]
    if icon_flag:
        pyinstaller_cmd.append(icon_flag)
    
    hidden_imports = [
        "mss", "PIL", "PIL.Image", "PIL.ImageTk", "pyautogui", "tkinter",
        "pyscreeze", "pygetwindow", "pymsgbox", "pytweening", "mouseinfo"
    ]
    for hi in hidden_imports:
        pyinstaller_cmd.extend(["--hidden-import", hi])
        
    pyinstaller_cmd.extend(["--collect-all", "mss", "p2p.py"])

    try:
        subprocess.check_call(pyinstaller_cmd)
        print("\n✔ Build completado exitosamente\n")
        print(f"  El ejecutable está en: {Path('dist/P2P.exe').resolve()}")
        print("  Para ejecutar: doble click en dist\\P2P.exe\n")
    except subprocess.CalledProcessError:
        print("\n[ERROR] El build de PyInstaller falló.\n")
        input("Presiona [Enter] para salir...")
        sys.exit(1)

    # 5. Limpieza final
    shutil.rmtree("build", ignore_errors=True)
    for p in Path(".").glob("*.spec"):
        p.unlink()
    print("● Archivos temporales limpiados\n")

    input("Presiona [Enter] para salir...")

if __name__ == "__main__":
    # Ensure working directory is the script directory
    os.chdir(Path(__file__).parent.resolve())
    main()
