#!/usr/bin/env python3
"""
P2P File Transfer — Transfiere archivos entre Windows y Mac sin internet.
Usa red local (Wi-Fi directo o Ethernet) con descubrimiento automático.

Uso:
  Receptor:  python3 p2p.py receive [--dir DESTINO] [--port PUERTO]
  Emisor:    python3 p2p.py send <RUTA> [--to IP] [--port PUERTO]
"""

import argparse
import hashlib
import json
import os
import platform
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

# ─── Constantes ──────────────────────────────────────────────────────────────

VERSION = "1.4.0"
DEFAULT_TCP_PORT = 50506
DEFAULT_UDP_PORT = 50505
BROADCAST_INTERVAL = 1.0      # segundos entre broadcasts
CHUNK_SIZE = 1048576           # 1 MB — reduce syscalls para máxima velocidad
DISCOVERY_TIMEOUT = 10         # segundos límite esperando al menos un peer
PEER_SCAN_TIME = 2.0           # segundos que escanea la red tras encontrar el primero
MAGIC = b"P2P1"                # identificador de protocolo
SOCKET_BUFFER = 4194304        # 4 MB buffer de socket

# Extensiones de archivos ya comprimidos (no se re-comprimen)
COMPRESSED_EXTENSIONS = {
    ".zip", ".rar", ".7z", ".gz", ".bz2", ".xz", ".tar.gz", ".tgz",
    ".mp4", ".mkv", ".avi", ".mov", ".mp3", ".aac", ".flac", ".ogg",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic",
    ".pdf", ".docx", ".xlsx", ".pptx",
    ".dmg", ".iso", ".cab", ".deb", ".rpm",
}

# ─── Colores para terminal ──────────────────────────────────────────────────

class Colors:
    """Colores ANSI para terminal. Se desactivan en Windows sin soporte."""
    _enabled = True

    @classmethod
    def init(cls):
        if platform.system() == "Windows":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            except Exception:
                cls._enabled = False

    @classmethod
    def _wrap(cls, code, text):
        if cls._enabled:
            return f"\033[{code}m{text}\033[0m"
        return text

    @classmethod
    def bold(cls, t):    return cls._wrap("1", t)
    @classmethod
    def green(cls, t):   return cls._wrap("32", t)
    @classmethod
    def cyan(cls, t):    return cls._wrap("36", t)
    @classmethod
    def yellow(cls, t):  return cls._wrap("33", t)
    @classmethod
    def red(cls, t):     return cls._wrap("31", t)
    @classmethod
    def dim(cls, t):     return cls._wrap("2", t)
    @classmethod
    def magenta(cls, t): return cls._wrap("35", t)

Colors.init()

# ─── Utilidades ──────────────────────────────────────────────────────────────

def optimize_socket(sock):
    """Aplica optimizaciones de velocidad al socket TCP."""
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except Exception:
        pass
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SOCKET_BUFFER)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, SOCKET_BUFFER)
    except Exception:
        pass


def is_compressed_file(filepath):
    """Detecta si un archivo ya está comprimido por su extensión."""
    ext = Path(filepath).suffix.lower()
    return ext in COMPRESSED_EXTENSIONS


def get_local_ip():
    """Obtiene la IP local de la interfaz activa."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("10.254.254.254", 1))  # No envía datos realmente
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def clear_screen():
    """Limpia la terminal."""
    os.system('cls' if platform.system() == "Windows" else 'clear')


class Settings:
    """Gestor de configuración global interactiva."""
    def __init__(self):
        self.name = platform.node()
        self.downloads_dir = str(Path.home() / "Downloads")
        self.port = DEFAULT_TCP_PORT


def format_size(size_bytes):
    """Formatea bytes a unidad legible."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def format_speed(bytes_per_sec):
    """Formatea velocidad de transferencia."""
    return f"{format_size(bytes_per_sec)}/s"


def format_time(seconds):
    """Formatea segundos a mm:ss."""
    if seconds < 0 or seconds > 86400:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def compute_checksum(filepath):
    """Calcula SHA-256 de un archivo."""
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()


def draw_progress(current, total, start_time, prefix=""):
    """Dibuja barra de progreso en terminal."""
    if total == 0:
        return
    pct = current / total
    elapsed = time.time() - start_time
    speed = current / elapsed if elapsed > 0 else 0
    remaining = (total - current) / speed if speed > 0 else 0

    bar_width = 30
    filled = int(bar_width * pct)
    bar = "█" * filled + "░" * (bar_width - filled)

    line = (
        f"\r  {prefix}"
        f"{Colors.cyan(bar)} "
        f"{Colors.bold(f'{pct*100:5.1f}%')}  "
        f"{format_size(current)}/{format_size(total)}  "
        f"{Colors.dim(format_speed(speed))}  "
        f"ETA {Colors.dim(format_time(remaining))}"
    )
    sys.stdout.write(line + "  ")
    sys.stdout.flush()


def print_banner():
    """Muestra banner de la app interactivo con calavera P2P-Pirate."""
    clear_screen()
    banner = f"""
{Colors.bold(Colors.cyan('                                        '))}
{Colors.bold(Colors.cyan('              @@@%%%%%%%%%@@            '))}
{Colors.bold(Colors.cyan('           @@@%%%%%%%%%#######%@@       '))}
{Colors.bold(Colors.cyan('         @@@@%%%%%%%######?######%@     '))}
{Colors.bold(Colors.cyan('        @@@@%%%%%%%#######:########%@   '))}
{Colors.bold(Colors.cyan('      @@@@@%%%%%%#########:??#######%   '))}
{Colors.bold(Colors.cyan('      @@@%%%%%####???###?+:??####?###@  '))}
{Colors.bold(Colors.cyan('     @@@%%%%%%#?+???###?:+?##??###?##@  '))}
{Colors.bold(Colors.cyan('   @??%@%%%##????????++:;+?+????????#@  '))}
{Colors.bold(Colors.cyan('   #  ;?%#?+; ..::+?+ ::;++++++?+???#   '))}
{Colors.bold(Colors.cyan('   %  :?%;;;:  ....:#+ :;+++????+???@   '))}
{Colors.bold(Colors.cyan('   #;;+??+++:   ...;##: ;;;++???++?%    '))}
{Colors.bold(Colors.cyan('   %#%+::++?#+;:::;?##+ ;;;;++??++#     '))}
{Colors.bold(Colors.cyan('   %?% : :???+?++???######?+;;+??#      '))}
{Colors.bold(Colors.cyan('   @%# ; ;??;;+ ;???+;;:..::.:+?%       '))}
{Colors.bold(Colors.cyan('    @???;;?+;;;+ ;:;;......;;;#@        '))}
{Colors.bold(Colors.cyan('    %##?++?+++;+ ??% @%%@@@@            '))}
{Colors.bold(Colors.cyan('    @_:?_:+_:_:#%                       '))}

{Colors.bold(Colors.magenta('  ╔══════════════════════════════════════╗'))}
{Colors.bold(Colors.magenta('  ║'))}     {Colors.bold('P2P File Transfer')} {Colors.dim(f'v{VERSION}')}        {Colors.bold(Colors.magenta('║'))}
{Colors.bold(Colors.magenta('  ║'))}   {Colors.dim('Sin internet · Red local · Directo')}  {Colors.bold(Colors.magenta('║'))}
{Colors.bold(Colors.magenta('  ╚══════════════════════════════════════╝'))}
"""
    print(banner)

def print_settings_banner():
    """Muestra enorme texto ALONSO para configuraciones."""
    clear_screen()
    alonso = f"""
{Colors.bold(Colors.cyan('    █████╗ ██╗      ██████╗ ███╗   ██╗███████╗ ██████╗ '))}
{Colors.bold(Colors.cyan('   ██╔══██╗██║     ██╔═══██╗████╗  ██║██╔════╝██╔═══██╗'))}
{Colors.bold(Colors.cyan('   ███████║██║     ██║   ██║██╔██╗ ██║███████╗██║   ██║'))}
{Colors.bold(Colors.cyan('   ██╔══██║██║     ██║   ██║██║╚██╗██║╚════██║██║   ██║'))}
{Colors.bold(Colors.cyan('   ██║  ██║███████╗╚██████╔╝██║ ╚████║███████║╚██████╔╝'))}
{Colors.bold(Colors.cyan('   ╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚═╝  ╚═══╝╚══════╝ ╚═════╝ '))}
"""
    print(alonso)


def print_info(msg):
    print(f"  {Colors.cyan('●')} {msg}")

def print_success(msg):
    print(f"  {Colors.green('✔')} {msg}")

def print_warning(msg):
    print(f"  {Colors.yellow('!')} {msg}")

def print_error(msg):
    print(f"  {Colors.red('✖')} {msg}")


# ─── Compresión ──────────────────────────────────────────────────────────────

def compress_path(source_path):
    """
    Comprime archivo o carpeta a ZIP temporal.
    Detecta archivos ya comprimidos y usa ZIP_STORED para no perder tiempo.
    Retorna (ruta_zip, nombre_original, cantidad_archivos, is_raw).
    is_raw=True significa que se envía el archivo directamente sin ZIP.
    """
    source = Path(source_path).resolve()
    if not source.exists():
        print_error(f"No existe: {source}")
        sys.exit(1)

    original_name = source.name

    # Si es un archivo ya comprimido, enviarlo directo sin re-empaquetar
    if source.is_file() and is_compressed_file(source):
        file_size = source.stat().st_size
        print_info(
            f"Archivo ya comprimido: {Colors.bold(original_name)} "
            f"({Colors.cyan(format_size(file_size))}) — envío directo"
        )
        return str(source), original_name, 1, True

    tmp_dir = tempfile.mkdtemp(prefix="p2p_")
    zip_path = os.path.join(tmp_dir, f"{original_name}.zip")

    print_info(f"Comprimiendo {Colors.bold(original_name)}...")

    file_count = 0
    total_size = 0

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        if source.is_file():
            zf.write(source, source.name)
            file_count = 1
            total_size = source.stat().st_size
        elif source.is_dir():
            for root, dirs, files in os.walk(source):
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(source.parent)
                    # Archivos ya comprimidos: ZIP_STORED (sin re-comprimir)
                    if is_compressed_file(file_path):
                        zf.write(file_path, arcname, compress_type=zipfile.ZIP_STORED)
                    else:
                        zf.write(file_path, arcname)
                    file_count += 1
                    total_size += file_path.stat().st_size
        else:
            print_error("Ruta no válida (no es archivo ni carpeta)")
            sys.exit(1)

    zip_size = os.path.getsize(zip_path)
    ratio = (1 - zip_size / total_size) * 100 if total_size > 0 else 0

    print_success(
        f"Comprimido: {Colors.bold(str(file_count))} archivo(s), "
        f"{format_size(total_size)} → {Colors.green(format_size(zip_size))} "
        f"({Colors.dim(f'-{ratio:.0f}%')})"
    )

    return zip_path, original_name, file_count, False


def decompress_zip(zip_path, dest_dir):
    """Descomprime ZIP en directorio destino. Retorna lista de archivos."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.namelist()
        zf.extractall(dest_dir)
    return members


# ─── Descubrimiento UDP ─────────────────────────────────────────────────────

class PeerDiscovery:
    """Maneja broadcast/descubrimiento de peers en la red local."""

    def __init__(self, udp_port=DEFAULT_UDP_PORT, tcp_port=DEFAULT_TCP_PORT, name=None):
        self.udp_port = udp_port
        self.tcp_port = tcp_port
        self.name = name or platform.node()
        self._stop = threading.Event()

    def start_broadcasting(self):
        """Anuncia disponibilidad del receptor via UDP broadcast."""
        local_ip = get_local_ip()
        msg = json.dumps({
            "type": "P2P_READY",
            "name": self.name,
            "ip": local_ip,
            "tcp_port": self.tcp_port
        }).encode()

        def _broadcast():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(1.0)
            while not self._stop.is_set():
                try:
                    sock.sendto(msg, ("<broadcast>", self.udp_port))
                except Exception:
                    pass
                self._stop.wait(BROADCAST_INTERVAL)
            sock.close()

        t = threading.Thread(target=_broadcast, daemon=True)
        t.start()
        return t

    def discover_peers(self, timeout=DISCOVERY_TIMEOUT, scan_time=PEER_SCAN_TIME):
        """Escanea la red buscando receptores. Retorna lista de dicts con info de peers."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError:
            pass
        sock.settimeout(0.5)
        sock.bind(("", self.udp_port))

        local_ip = get_local_ip()
        peers = {}  # dict {ip: peer_info} para no duplicar
        
        print_info(f"Escaneando red local... (aprox {scan_time}s)")
        
        # Fase 1: Esperar hasta encontrar el primer peer (o timeout)
        first_peer_time = None
        deadline = time.time() + timeout

        while time.time() < deadline and not self._stop.is_set():
            # Si ya encontramos uno, iniciamos el temporizador corto de escaneo
            if first_peer_time and (time.time() - first_peer_time) > scan_time:
                break

            try:
                data, addr = sock.recvfrom(1024)
                try:
                    info = json.loads(data.decode())
                    if info.get("type") == "P2P_READY":
                        peer_ip = info.get("ip", addr[0])
                        if peer_ip != local_ip or addr[0] != local_ip:
                            if peer_ip not in peers:
                                peers[peer_ip] = {
                                    "ip": peer_ip,
                                    "tcp_port": info.get("tcp_port", DEFAULT_TCP_PORT),
                                    "name": info.get("name", info.get("hostname", "?"))
                                }
                                if not first_peer_time:
                                    first_peer_time = time.time()
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
            except socket.timeout:
                continue

        sock.close()
        return list(peers.values())

    def stop(self):
        self._stop.set()


# ─── Transferencia ───────────────────────────────────────────────────────────

def send_file(sock, zip_path, original_name, file_count, is_raw=False, sender_name="Sender"):
    """Envía un archivo por socket TCP con header JSON."""
    optimize_socket(sock)
    file_size = os.path.getsize(zip_path)
    checksum = compute_checksum(zip_path)

    # Header
    header = json.dumps({
        "sender_name": sender_name,
        "original_name": original_name,
        "file_count": file_count,

        "size": file_size,
        "checksum": checksum,
        "is_raw": is_raw
    }).encode()

    # Enviar magic + header length + header
    sock.sendall(MAGIC)
    sock.sendall(struct.pack("!I", len(header)))
    sock.sendall(header)

    # Esperar confirmación manual (ACK interactivo) del receptor
    print_info("Esperando que el receptor acepte la transferencia...")
    sock.settimeout(None)  # El usuario humano puede tardar en responder
    ack = sock.recv(2)
    if ack != b"OK":
        print_error("Transferencia rechazada por el receptor")
        return False

    # Enviar datos
    print_info("Transfiriendo...")
    start_time = time.time()
    sent = 0

    with open(zip_path, "rb") as f:
        # Optimización extrema Zero-Copy usando sendfile (si está disponible)
        if hasattr(os, "sendfile") and file_size > 0:
            try:
                sock.setblocking(True)
                # socket.sendfile was added in Python 3.5
                sock.sendfile(f)
                sent = file_size
                draw_progress(sent, file_size, start_time)
            except Exception:
                # Fallback on fallback zero-copy failure
                f.seek(0)
                sent = 0

        # Transferencia manual en chunks (en fallback o si sendfile no existe)
        if sent == 0:
            while sent < file_size:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                sock.sendall(chunk)
                sent += len(chunk)
                draw_progress(sent, file_size, start_time)

    print()  # Salto de línea después de la barra

    # Esperar confirmación final
    try:
        sock.settimeout(30)
        result = sock.recv(4)
        if result == b"DONE":
            elapsed = time.time() - start_time
            avg_speed = file_size / elapsed if elapsed > 0 else 0
            print_success(
                f"Transferencia completa en {Colors.bold(format_time(elapsed))} "
                f"({Colors.dim(format_speed(avg_speed))} promedio)"
            )
            return True
        else:
            print_error("El receptor reportó un error en la verificación")
            return False
    except socket.timeout:
        print_warning("Sin confirmación del receptor (timeout)")
        return False


def receive_file(sock, dest_dir):
    """Recibe un archivo por socket TCP y lo descomprime si es necesario."""
    optimize_socket(sock)
    # Leer magic
    magic = sock.recv(4)
    if magic != MAGIC:
        print_error("Protocolo no reconocido")
        sock.sendall(b"NO")
        return False

    # Leer header
    header_len_data = sock.recv(4)
    header_len = struct.unpack("!I", header_len_data)[0]
    header_data = b""
    while len(header_data) < header_len:
        chunk = sock.recv(header_len - len(header_data))
        if not chunk:
            break
        header_data += chunk

    header = json.loads(header_data.decode())
    sender_name = header.get("sender_name", "Alguien")
    original_name = header["original_name"]
    file_count = header["file_count"]
    file_size = header["size"]
    expected_checksum = header["checksum"]
    is_raw = header.get("is_raw", False)

    print()
    print(f"  {Colors.bold(Colors.magenta('── Petición de Transferencia ──'))}")
    print(f"  {Colors.dim('De:')}      {Colors.bold(Colors.cyan(sender_name))}")
    print(f"  {Colors.dim('Archivo:')} {Colors.bold(original_name)}")
    print(f"  {Colors.dim('Tamaño:')}  {Colors.bold(format_size(file_size))}")
    if not is_raw:
        print(f"  {Colors.dim('Ítems:')}   {Colors.bold(str(file_count))}")
    print()

    # Prompt de confirmación al usuario
    try:
        ans = input(f"  {Colors.yellow('?')} ¿Aceptar transferencia? [S/n] ").strip().lower()
        if ans not in ('', 's', 'y'):
            print_warning("Transferencia declinada")
            sock.sendall(b"NO")
            return False
    except (KeyboardInterrupt, EOFError):
        sock.sendall(b"NO")
        print("\n")
        return False

    # Enviar ACK
    sock.sendall(b"OK")

    # Recibir datos
    tmp_dir = tempfile.mkdtemp(prefix="p2p_rx_")
    zip_path = os.path.join(tmp_dir, f"{original_name}.zip")

    print_info("Recibiendo...")
    start_time = time.time()
    received = 0

    with open(zip_path, "wb") as f:
        while received < file_size:
            remaining = file_size - received
            chunk = sock.recv(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            f.write(chunk)
            received += len(chunk)
            draw_progress(received, file_size, start_time)

    print()

    if received != file_size:
        print_error(f"Transferencia incompleta: {format_size(received)}/{format_size(file_size)}")
        sock.sendall(b"FAIL")
        return False

    # Verificar checksum
    print_info("Verificando integridad (SHA-256)...")
    actual_checksum = compute_checksum(zip_path)
    if actual_checksum != expected_checksum:
        print_error("Checksum no coincide — archivo corrupto")
        sock.sendall(b"FAIL")
        return False

    print_success("Integridad verificada")

    # Descomprimir o copiar directo
    dest_path = Path(dest_dir).resolve()
    dest_path.mkdir(parents=True, exist_ok=True)

    if is_raw:
        # Archivo ya comprimido — mover directamente al destino
        final_path = dest_path / original_name
        shutil.move(zip_path, str(final_path))
        members = [original_name]
        print_info(f"Guardado directo: {Colors.bold(str(final_path))}")
    else:
        print_info(f"Descomprimiendo en {Colors.bold(str(dest_path))}...")
        members = decompress_zip(zip_path, str(dest_path))

    # Limpiar temporal
    shutil.rmtree(tmp_dir, ignore_errors=True)

    # Confirmar
    sock.sendall(b"DONE")

    elapsed = time.time() - start_time
    avg_speed = file_size / elapsed if elapsed > 0 else 0
    print_success(
        f"Recibido {Colors.bold(str(len(members)))} archivo(s) en "
        f"{Colors.bold(format_time(elapsed))} "
        f"({Colors.dim(format_speed(avg_speed))} promedio)"
    )
    print()
    print(f"  {Colors.dim('Guardado en:')} {Colors.green(str(dest_path))}")
    print()

    return True


# ─── Modo Sender ─────────────────────────────────────────────────────────────

def cmd_send(settings):
    """Interfaz interactiva: enviar archivo/carpeta."""
    print_banner()
    print(f"  {Colors.bold(Colors.magenta('── Enviar Archivo / Carpeta ──'))}")
    print(f"  {Colors.dim('Arrastra un archivo aquí o escribe su ruta.')}\n")
    
    try:
        path_input = input(f"  {Colors.yellow('→')} Ruta: ").strip()
        if not path_input:
            return
        # Remover comillas si el usuario arrastró el archivo en Mac/Windows
        path_input = path_input.strip("'\" ")
    except (KeyboardInterrupt, EOFError):
        print("\n")
        return
        
    source = Path(path_input).resolve()
    if not source.exists():
        print_error(f"No existe: {source}")
        input(f"\n  {Colors.dim('[Enter] para continuar...')} ")
        return

    my_name = settings.name
    local_ip = get_local_ip()
    print()
    print_info(f"Tu IP: {Colors.bold(local_ip)} {Colors.dim(f'({my_name})')}")
    print_info(f"Fuente: {Colors.bold(str(source))}")
    print()

    # Comprimir (o detectar archivo ya comprimido)
    zip_path, original_name, file_count, is_raw = compress_path(source)
    print()

    # Encontrar receptor
    target_port = settings.port
    discovery = PeerDiscovery(tcp_port=target_port)
    peers = discovery.discover_peers()
    target_ip = None

    if not peers:
        print_warning("No se encontró ningún receptor automáticamente en la red")
        target_ip = input(f"  {Colors.yellow('→')} Ingresa la IP del receptor manualmente: ").strip()
        if not target_ip:
            print_error("Cancelado")
            input(f"\n  {Colors.dim('[Enter] para volver...')} ")
            return
    elif len(peers) == 1:
        peer = peers[0]
        target_ip, target_port = peer["ip"], peer["tcp_port"]
        print_success(
            f"Receptor encontrado: {Colors.bold(peer['name'])} "
            f"({Colors.cyan(target_ip)}:{target_port})"
        )
    else:
        print_success(f"Se encontraron {len(peers)} posibles receptores:")
        for i, p in enumerate(peers, 1):
            print(f"    {Colors.cyan(f'[{i}]')} {Colors.bold(p['name'])} {Colors.dim(f'({p['ip']})')}")
        
        while True:
            try:
                choice = input(f"\n  {Colors.yellow('→')} Elige un receptor (1-{len(peers)}): ").strip()
                idx = int(choice) - 1
                if 0 <= idx < len(peers):
                    peer = peers[idx]
                    target_ip, target_port = peer["ip"], peer["tcp_port"]
                    print_info(f"Seleccionado: {Colors.bold(peer['name'])}")
                    break
                else:
                    print_error("Opción inválida")
            except ValueError:
                print_error("Ingresa un número válido")
            except (KeyboardInterrupt, EOFError):
                print("\n")
                print_info("Cancelado")
                return
    
    if target_ip:
        print_info(f"Conectando a: {Colors.bold(target_ip)}:{target_port}")

    print()

    # Conectar y enviar
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((target_ip, target_port))
        sock.settimeout(None)
        send_file(sock, zip_path, original_name, file_count, is_raw, sender_name=my_name)
    except ConnectionRefusedError:
        print_error(f"Conexión rechazada en {target_ip}:{target_port}")
        print_info("Asegúrate de que el receptor esté en la pantalla de 'Recibir Archivos'")
    except socket.timeout:
        print_error("Timeout al conectar")
    except Exception as e:
        print_error(f"Error: {e}")
    finally:
        try:
            sock.close()
        except Exception:
            pass
        # Limpiar ZIP temporal (solo si no es raw)
        if not is_raw:
            shutil.rmtree(os.path.dirname(zip_path), ignore_errors=True)

    print()
    try:
        input(f"  {Colors.dim('[Enter] para volver al menú...')} ")
    except (KeyboardInterrupt, EOFError):
        pass



# ─── Modo Receiver ───────────────────────────────────────────────────────────

def cmd_receive(settings):
    """Interfaz interactiva: esperar y recibir archivos."""
    print_banner()
    print(f"  {Colors.bold(Colors.green('── Recibir Archivos (Radar Encendido) ──'))}")
    
    dest_dir = settings.downloads_dir
    port = settings.port
    local_ip = get_local_ip()

    my_name = settings.name
    print_info(f"Tu nombre: {Colors.bold(my_name)}")
    print_info(f"Tu IP:     {Colors.bold(local_ip)}")
    print_info(f"Destino:   {Colors.bold(dest_dir)}")
    print()

    # Iniciar servidor TCP
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("0.0.0.0", port))
    except OSError as e:
        print_error(f"No se pudo escuchar en el puerto {port}: {e}")
        print_info("Es posible que ya haya otra terminal recibiendo, o el puerto esté bloqueado.")
        input(f"\n  {Colors.dim('[Enter] para volver al menú principal...')} ")
        return

    server.listen(1)

    # Iniciar broadcast de descubrimiento
    discovery = PeerDiscovery(tcp_port=port, name=my_name)
    discovery.start_broadcasting()

    print_success("Listo para recibir")
    print(
        f"  {Colors.dim('El sender puede conectarse automáticamente o usar:')}\n"
        f"  {Colors.yellow('python3 p2p.py send <ruta> --to')} {Colors.bold(local_ip)}\n"
    )
    print(f"  {Colors.dim('Esperando conexión... (Ctrl+C para cancelar)')}")

    try:
        while True:
            server.settimeout(1.0)
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue

            print()
            print_info(f"Conexión desde {Colors.bold(addr[0])}:{addr[1]}")

            try:
                receive_file(conn, dest_dir)
            except Exception as e:
                print_error(f"Error en la transferencia: {e}")
            finally:
                conn.close()

            print(f"  {Colors.dim('Esperando más conexiones... (Ctrl+C para salir al menú principal)')}")

    except KeyboardInterrupt:
        print("\n")
    finally:
        discovery.stop()
        server.close()


def cmd_settings(settings):
    """Interfaz interactiva: Configuración."""
    while True:
        print_settings_banner()
        print(f"  {Colors.bold(Colors.magenta('── Configuración General ──'))}")
        print(f"    {Colors.cyan('[1]')} Nombre del Dispositivo : {Colors.bold(settings.name)}")
        print(f"    {Colors.cyan('[2]')} Carpeta de Descargas   : {Colors.bold(settings.downloads_dir)}")
        print(f"    {Colors.cyan('[0]')} Volver al Menú Principal")
        print()
        
        try:
            choice = input(f"  {Colors.yellow('→')} Selecciona una opción: ").strip()
            if choice == "1":
                new_name = input(f"  {Colors.yellow('→')} Nuevo nombre: ").strip()
                if new_name:
                    settings.name = new_name
            elif choice == "2":
                new_dir = input(f"  {Colors.yellow('→')} Nueva ruta de descargas: ").strip()
                if new_dir:
                    settings.downloads_dir = new_dir
            elif choice == "0" or choice == "":
                break
        except (KeyboardInterrupt, EOFError):
            break


# ─── Loop Principal TUI ──────────────────────────────────────────────────────

def main():
    # Desactivar cursor intermitente al salir
    import atexit
    atexit.register(lambda: sys.stdout.write("\033[?25h"))
    
    settings = Settings()
    
    while True:
        print_banner()
        print(f"  {Colors.bold('Bienvenido a P2P Terminal.')} Elige una opción:\n")
        print(f"    {Colors.green('▼')} {Colors.bold(Colors.green('[1] Recibir Archivos'))}  {Colors.dim('(Activar radar)')}")
        print(f"    {Colors.cyan('▲')} {Colors.bold(Colors.cyan('[2] Enviar Archivos'))}   {Colors.dim('(A un equipo en la red)')}")
        print()
        print(f"    {Colors.magenta('⚙')} {Colors.bold(Colors.magenta('[3] Configuración'))}   {Colors.dim(f'(Nombre: {settings.name})')}")
        print(f"    {Colors.red('✖')} {Colors.bold(Colors.red('[0] Salir'))}")
        print()
        
        try:
            choice = input(f"  {Colors.yellow('→')} Opción: ").strip()
            
            if choice == "1":
                cmd_receive(settings)
            elif choice == "2":
                cmd_send(settings)
            elif choice == "3":
                cmd_settings(settings)
            elif choice == "0":
                clear_screen()
                print_info("¡Hasta pronto!")
                sys.exit(0)
        except (KeyboardInterrupt, EOFError):
            clear_screen()
            print_info("Saliendo de P2P...")
            sys.exit(0)


if __name__ == "__main__":
    main()
