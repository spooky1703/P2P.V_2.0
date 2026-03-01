#!/usr/bin/env python3
"""
P2P File Transfer v2.0 — Transfiere archivos y controla equipos remotos.
Sin internet · Red local · Directo.

Uso: python3 p2p.py  (interfaz interactiva)
"""


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

VERSION = "2.0.0"
DEFAULT_TCP_PORT = 50506
DEFAULT_UDP_PORT = 50505
BROADCAST_INTERVAL = 1.0      # segundos entre broadcasts
CHUNK_SIZE = 1048576           # 1 MB — reduce syscalls para máxima velocidad
DISCOVERY_TIMEOUT = 10         # segundos límite esperando al menos un peer
PEER_SCAN_TIME = 2.0           # segundos que escanea la red tras encontrar el primero
MAGIC = b"P2P1"                # identificador de protocolo
SOCKET_BUFFER = 4194304        # 4 MB buffer de socket
REMOTE_PORT = 50507             # puerto para control remoto (stream)
REMOTE_EVT_PORT = 50508         # puerto para eventos de input
REMOTE_FPS = 20                 # frames por segundo objetivo
REMOTE_QUALITY = 55             # calidad JPEG (0-100), menor = más rápido

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
    @classmethod
    def white(cls, t):   return cls._wrap("37", t)

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


def get_all_local_ips():
    """Obtiene todas las IPs locales (Wi-Fi, Ethernet, VPN, etc)."""
    ips = set()
    # 1. Intento principal (interfaz por defecto)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("10.254.254.254", 1))
        ip = s.getsockname()[0]
        if not ip.startswith("127."):
            ips.add(ip)
        s.close()
    except Exception:
        pass

    # 2. Agregar el resto de interfaces (útil si la principal es Docker/VMware)
    try:
        for addrinfo in socket.getaddrinfo(socket.gethostname(), None):
            ip = addrinfo[4][0]
            if ":" not in ip and not ip.startswith("127."):  # Solo IPv4
                ips.add(ip)
    except Exception:
        pass
    
    if not ips:
        ips.add("127.0.0.1")
        
    return sorted(list(ips))


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
{Colors.bold(Colors.red('                                        '))}
{Colors.bold(Colors.red('              @@@%%%%%%%%%@@            '))}
{Colors.bold(Colors.red('           @@@%%%%%%%%%#######%@@       '))}
{Colors.bold(Colors.red('         @@@@%%%%%%%######?######%@     '))}
{Colors.bold(Colors.red('        @@@@%%%%%%%#######:########%@   '))}
{Colors.bold(Colors.red('      @@@@@%%%%%%#########:??#######%   '))}
{Colors.bold(Colors.red('      @@@%%%%%####???###?+:??####?###@  '))}
{Colors.bold(Colors.red('     @@@%%%%%%#?+???###?:+?##??###?##@  '))}
{Colors.bold(Colors.red('   @??%@%%%##????????++:;+?+????????#@  '))}
{Colors.bold(Colors.red('   #  ;?%#?+; ..::+?+ ::;++++++?+???#   '))}
{Colors.bold(Colors.red('   %  :?%;;;:  ....:#+ :;+++????+???@   '))}
{Colors.bold(Colors.red('   #;;+??+++:   ...;##: ;;;++???++?%    '))}
{Colors.bold(Colors.red('   %#%+::++?#+;:::;?##+ ;;;;++??++#     '))}
{Colors.bold(Colors.red('   %?% : :???+?++???######?+;;+??#      '))}
{Colors.bold(Colors.red('   @%# ; ;??;;+ ;???+;;:..::.:+?%       '))}
{Colors.bold(Colors.red('    @???;;?+;;;+ ;:;;......;;;#@        '))}
{Colors.bold(Colors.red('    %##?++?+++;+ ??% @%%@@@@            '))}
{Colors.bold(Colors.red('    @_:?_:+_:_:#%                       '))}

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
        return None, None, 0, False

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
            return None, None, 0, False

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
        local_ips = get_all_local_ips()
        ip_to_share = local_ips[0] if local_ips else "127.0.0.1"
        msg = json.dumps({
            "type": "P2P_READY",
            "name": self.name,
            "ip": ip_to_share,
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

        local_ips = get_all_local_ips()
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
                        if peer_ip not in local_ips or addr[0] not in local_ips:
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
    local_ips = get_all_local_ips()
    ip_str = " | ".join(local_ips)
    print()
    print_info(f"Tus IPs: {Colors.bold(ip_str)} {Colors.dim(f'({my_name})')}")
    print_info(f"Fuente: {Colors.bold(str(source))}")
    print()

    # Comprimir (o detectar archivo ya comprimido)
    zip_path, original_name, file_count, is_raw = compress_path(source)
    if zip_path is None:
        input(f"\n  {Colors.dim('[Enter] para volver...')} ")
        return
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
            pip = p['ip']
            print(f"    {Colors.cyan(f'[{i}]')} {Colors.bold(p['name'])} {Colors.dim(f'({pip})')}")
        
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
        print_error(f"Error al conectar: {e}")
        print_info("⚠️ Si están en la misma red, revisa el Firewall de Windows/Mac.")
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
    local_ips = get_all_local_ips()
    ip_str = " | ".join(local_ips)

    my_name = settings.name
    print_info(f"Tu nombre: {Colors.bold(my_name)}")
    print_info(f"Tus IPs:   {Colors.white(Colors.bold(ip_str))}")
    print_info(f"Destino:   {Colors.bold(dest_dir)}")
    print_info(f"⚠️ {Colors.dim('Asegúrate de conceder permisos de Firewall si el OS lo pide.')}")
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
        f"  {Colors.dim('Otros equipos en la misma red te encontrarán automáticamente.')}\n"
        f"  {Colors.dim('Si la conexión falla, asegúrate de que ambos usen la misma red Wi-Fi y')}\n"
        f"  {Colors.dim('el Firewall no esté bloqueando Python/P2P.')}\n"
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


# ─── Control Remoto: Dependencias ───────────────────────────────────────────

def check_remote_deps():
    """Verifica e instala dependencias para control remoto."""
    missing = []
    try:
        import mss
    except ImportError:
        missing.append("mss")
    try:
        from PIL import Image
    except ImportError:
        missing.append("Pillow")
    try:
        import pyautogui
    except ImportError:
        missing.append("pyautogui")
    
    if not missing:
        return True
    
    print_info(f"Instalando dependencias necesarias: {Colors.bold(', '.join(missing))}")
    print_info("Esto solo se hace una vez...")
    print()
    
    import subprocess
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet"] + missing,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        print_success("Dependencias instaladas correctamente")
        return True
    except Exception as e:
        print_error(f"No se pudieron instalar: {e}")
        print_info("Intenta manualmente: pip install " + " ".join(missing))
        return False


# ─── Control Remoto: Agente Remoto (Controlado) ───────────────────────

class RemoteAgent:
    """Captura pantalla, envía frames, recibe y ejecuta eventos del controlador.
    
    Usa dos sockets separados para evitar race conditions:
    - stream_conn: envía frames JPEG (Remote → Controller)
    - event_conn: recibe eventos de mouse/teclado (Controller → Remote)
    """
    
    def __init__(self, stream_conn, event_conn, name):
        self.stream_conn = stream_conn
        self.event_conn = event_conn
        self.name = name
        self._stop = threading.Event()
    
    def start(self):
        """Arranca hilos de streaming y de escucha de eventos."""
        t_stream = threading.Thread(target=self._stream_screen, daemon=True)
        t_events = threading.Thread(target=self._listen_events, daemon=True)
        t_stream.start()
        t_events.start()
        return t_stream, t_events
    
    def stop(self):
        self._stop.set()
    
    def _stream_screen(self):
        """Captura y envía frames JPEG continuamente."""
        import mss
        from PIL import Image
        import io
        
        sct = mss.mss()
        monitor = sct.monitors[1]  # monitor principal
        frame_interval = 1.0 / REMOTE_FPS
        
        # Enviar resolución inicial
        res_data = json.dumps({"width": monitor["width"], "height": monitor["height"]}).encode()
        try:
            self.stream_conn.sendall(struct.pack("!I", len(res_data)))
            self.stream_conn.sendall(res_data)
        except Exception:
            self.stop()
            return
        
        while not self._stop.is_set():
            t0 = time.time()
            try:
                # Capturar
                shot = sct.grab(monitor)
                img = Image.frombytes("RGB", (shot.width, shot.height), shot.rgb)
                
                # Reducir resolución para velocidad (50% del tamaño original)
                w, h = img.size
                img = img.resize((w // 2, h // 2), Image.LANCZOS)
                
                # Comprimir a JPEG
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=REMOTE_QUALITY, optimize=True)
                frame_data = buf.getvalue()
                
                # Enviar: [4 bytes longitud][datos JPEG]
                self.stream_conn.sendall(struct.pack("!I", len(frame_data)))
                self.stream_conn.sendall(frame_data)
                
                # Controlar FPS
                elapsed = time.time() - t0
                if elapsed < frame_interval:
                    time.sleep(frame_interval - elapsed)
            except (BrokenPipeError, ConnectionResetError, OSError):
                self.stop()
                break
            except Exception:
                continue
    
    def _listen_events(self):
        """Escucha eventos de mouse/teclado del controlador y los ejecuta."""
        import pyautogui
        pyautogui.FAILSAFE = False  # Desactivar failsafe para control remoto
        
        buf = b""
        while not self._stop.is_set():
            try:
                self.event_conn.settimeout(0.5)
                data = self.event_conn.recv(4096)
                if not data:
                    self.stop()
                    break
                
                buf += data
                # Procesar mensajes delimitados por newlines
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line:
                        continue
                    try:
                        event = json.loads(line.decode())
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    
                    self._handle_event(event, pyautogui)
            except socket.timeout:
                continue
            except (ConnectionResetError, BrokenPipeError, OSError):
                self.stop()
                break
    
    def _handle_event(self, event, pyautogui):
        """Ejecuta un evento de input en la máquina local."""
        try:
            etype = event.get("type", "")
            
            # Escalar coordenadas: el viewer manda coords en su escala (50%)
            # necesitamos escalarlas a la resolución real
            if etype == "mouse_move":
                x, y = event["x"] * 2, event["y"] * 2
                pyautogui.moveTo(x, y, _pause=False)
            
            elif etype == "click":
                x, y = event["x"] * 2, event["y"] * 2
                button = event.get("button", "left")
                pyautogui.click(x, y, button=button, _pause=False)
            
            elif etype == "double_click":
                x, y = event["x"] * 2, event["y"] * 2
                pyautogui.doubleClick(x, y, _pause=False)
            
            elif etype == "scroll":
                x, y = event["x"] * 2, event["y"] * 2
                delta = event.get("delta", 0)
                pyautogui.scroll(delta, x=x, y=y, _pause=False)
            
            elif etype == "key":
                key = event.get("key", "")
                if key:
                    pyautogui.press(key, _pause=False)
            
            elif etype == "key_combo":
                keys = event.get("keys", [])
                if keys:
                    pyautogui.hotkey(*keys, _pause=False)
            
            elif etype == "disconnect":
                self.stop()
        except Exception:
            pass  # No crashear agent por eventos mal formados


# ─── Control Remoto: Visor del Controlador ───────────────────────────

class ControllerViewer:
    """Ventana tkinter que muestra el escritorio remoto y captura eventos.
    
    Usa dos sockets separados:
    - stream_sock: recibe frames JPEG (Remote → Controller)
    - event_sock: envía eventos de mouse/teclado (Controller → Remote)
    """
    
    def __init__(self, stream_sock, event_sock, remote_name):
        self.stream_sock = stream_sock
        self.event_sock = event_sock
        self.remote_name = remote_name
        self._stop = threading.Event()
        self.width = 960
        self.height = 540
    
    def run(self):
        """Inicia la ventana del visor (bloqueante, debe correr en hilo principal)."""
        import tkinter as tk
        from PIL import Image, ImageTk
        import io
        
        # Recibir resolución inicial
        try:
            res_len_data = self._recv_exact(self.stream_sock, 4)
            res_len = struct.unpack("!I", res_len_data)[0]
            res_data = self._recv_exact(self.stream_sock, res_len)
            res = json.loads(res_data.decode())
            self.width = res["width"] // 2
            self.height = res["height"] // 2
        except Exception:
            pass
        
        # Crear ventana
        self.root = tk.Tk()
        self.root.title(f"P2P Remote — {self.remote_name}")
        self.root.geometry(f"{self.width}x{self.height}")
        self.root.configure(bg="black")
        self.root.resizable(True, True)
        
        self.canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        self._photo = None
        self._frame_buffer = None
        self._frame_lock = threading.Lock()
        
        # Bindings de eventos
        self.canvas.bind("<Motion>", self._on_mouse_move)
        self.canvas.bind("<Button-1>", lambda e: self._on_click(e, "left"))
        self.canvas.bind("<Button-2>", lambda e: self._on_click(e, "middle"))
        self.canvas.bind("<Button-3>", lambda e: self._on_click(e, "right"))
        self.canvas.bind("<Double-Button-1>", self._on_double_click)
        self.canvas.bind("<MouseWheel>", self._on_scroll)  # Mac/Windows
        self.canvas.bind("<Button-4>", lambda e: self._on_scroll_linux(e, 3))  # Linux up
        self.canvas.bind("<Button-5>", lambda e: self._on_scroll_linux(e, -3)) # Linux down
        self.root.bind("<Key>", self._on_key)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Focus en el canvas para capturar teclas
        self.canvas.focus_set()
        
        # Hilo receptor de frames
        t = threading.Thread(target=self._receive_frames, daemon=True)
        t.start()
        
        # Loop de actualización del canvas
        self._update_canvas()
        
        self.root.mainloop()
    
    def _recv_exact(self, sock, n):
        """Recibe exactamente n bytes de un socket."""
        data = b""
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Conexión cerrada")
            data += chunk
        return data
    
    def _receive_frames(self):
        """Hilo que recibe frames JPEG del agente remoto."""
        from PIL import Image
        import io
        
        while not self._stop.is_set():
            try:
                # Leer longitud del frame
                size_data = self._recv_exact(self.stream_sock, 4)
                frame_size = struct.unpack("!I", size_data)[0]
                
                if frame_size > 10_000_000:  # Protección: máx 10MB por frame
                    continue
                
                # Leer frame JPEG
                frame_data = self._recv_exact(self.stream_sock, frame_size)
                
                # Decodificar
                img = Image.open(io.BytesIO(frame_data))
                
                with self._frame_lock:
                    self._frame_buffer = img
                    
            except Exception:
                self._stop.set()
                break
    
    def _update_canvas(self):
        """Actualiza el canvas con el último frame (corre en hilo principal de tk)."""
        if self._stop.is_set():
            self.root.destroy()
            return
        
        from PIL import ImageTk
        
        with self._frame_lock:
            img = self._frame_buffer
            self._frame_buffer = None
        
        if img is not None:
            # Redimensionar al tamaño actual de la ventana
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()
            if cw > 1 and ch > 1:
                img = img.resize((cw, ch), Image.NEAREST)
            
            self._photo = ImageTk.PhotoImage(img)
            self.canvas.delete("all")
            self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
        
        self.root.after(33, self._update_canvas)  # ~30 fps display
    
    def _send_event(self, event_dict):
        """Envía evento JSON al agente remoto."""
        try:
            data = json.dumps(event_dict).encode() + b"\n"
            self.event_sock.sendall(data)
        except Exception:
            pass
    
    def _scale_coords(self, event):
        """Escala las coordenadas del click al tamaño del frame remoto."""
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw <= 0 or ch <= 0:
            return event.x, event.y
        sx = self.width / cw
        sy = self.height / ch
        return int(event.x * sx), int(event.y * sy)
    
    def _on_mouse_move(self, event):
        x, y = self._scale_coords(event)
        self._send_event({"type": "mouse_move", "x": x, "y": y})
    
    def _on_click(self, event, button):
        x, y = self._scale_coords(event)
        self._send_event({"type": "click", "x": x, "y": y, "button": button})
    
    def _on_double_click(self, event):
        x, y = self._scale_coords(event)
        self._send_event({"type": "double_click", "x": x, "y": y})
    
    def _on_scroll(self, event):
        x, y = self._scale_coords(event)
        # Mac/Windows: event.delta
        delta = event.delta // 120 if abs(event.delta) >= 120 else event.delta
        self._send_event({"type": "scroll", "x": x, "y": y, "delta": delta})
    
    def _on_scroll_linux(self, event, delta):
        x, y = self._scale_coords(event)
        self._send_event({"type": "scroll", "x": x, "y": y, "delta": delta})
    
    def _on_key(self, event):
        # Mapear teclas especiales de tkinter a nombres de pyautogui
        key_map = {
            "Return": "enter", "BackSpace": "backspace", "Tab": "tab",
            "Escape": "escape", "space": "space", "Delete": "delete",
            "Up": "up", "Down": "down", "Left": "left", "Right": "right",
            "Home": "home", "End": "end", "Prior": "pageup", "Next": "pagedown",
            "F1": "f1", "F2": "f2", "F3": "f3", "F4": "f4",
            "F5": "f5", "F6": "f6", "F7": "f7", "F8": "f8",
            "F9": "f9", "F10": "f10", "F11": "f11", "F12": "f12",
        }
        
        keysym = event.keysym
        
        # Detectar combos con modificadores
        mods = []
        if event.state & 0x4:   # Control
            mods.append("ctrl")
        if event.state & 0x8:   # Alt/Option
            mods.append("alt")
        if event.state & 0x1:   # Shift
            mods.append("shift")
        if event.state & 0x40:  # Command (Mac)
            mods.append("command")
        
        key = key_map.get(keysym, "")
        if not key and len(keysym) == 1:
            key = keysym.lower()
        
        if not key or key in ("shift_l", "shift_r", "control_l", "control_r",
                               "alt_l", "alt_r", "meta_l", "meta_r",
                               "super_l", "super_r"):
            return  # Ignorar modificadores solos
        
        if mods:
            self._send_event({"type": "key_combo", "keys": mods + [key]})
        else:
            self._send_event({"type": "key", "key": key})
    
    def _on_close(self):
        """Se ejecuta al cerrar la ventana."""
        self._send_event({"type": "disconnect"})
        self._stop.set()
        try:
            self.stream_sock.close()
            self.event_sock.close()
        except Exception:
            pass
        self.root.destroy()


# ─── Control Remoto: Flujos Interactivos ─────────────────────────────

def cmd_allow_control(settings):
    """Permite que otro equipo controle esta máquina."""
    print_banner()
    print(f"  {Colors.bold(Colors.red('── Permitir Control Remoto ──'))}")
    print()
    
    if not check_remote_deps():
        input(f"\n  {Colors.dim('[Enter] para volver...')} ")
        return
    
    port = REMOTE_PORT
    local_ips = get_all_local_ips()
    ip_str = " | ".join(local_ips)
    my_name = settings.name
    
    print_info(f"Tu nombre: {Colors.bold(my_name)}")
    print_info(f"Tus IPs:   {Colors.white(Colors.bold(ip_str))}")
    print_warning("Otro usuario podrá ver y controlar tu pantalla")
    print_info(f"⚠️ {Colors.dim('Importante: Autoriza las conexiones si el Firewall te pregunta.')}")
    print()
    
    # Servidor TCP para stream de control remoto
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Segundo servidor para canal de eventos
    evt_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    evt_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("0.0.0.0", port))
        evt_server.bind(("0.0.0.0", REMOTE_EVT_PORT))
    except OSError as e:
        print_error(f"No se pudo abrir los puertos de control remoto: {e}")
        input(f"\n  {Colors.dim('[Enter] para volver...')} ")
        return
    
    server.listen(1)
    evt_server.listen(1)
    
    # Broadcast de disponibilidad (reutilizar PeerDiscovery con puerto remoto)
    discovery = PeerDiscovery(tcp_port=port, name=my_name)
    discovery.start_broadcasting()
    
    print_success("Radar activado — esperando solicitudes de control...")
    print(f"  {Colors.dim('(Ctrl+C para cancelar)')}")
    print()
    
    try:
        while True:
            server.settimeout(1.0)
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue
            
            print_info(f"Solicitud desde {Colors.bold(addr[0])}")
            
            # Recibir nombre del controlador
            try:
                conn.settimeout(5)
                name_len_data = conn.recv(4)
                name_len = struct.unpack("!I", name_len_data)[0]
                controller_name = conn.recv(name_len).decode()
            except Exception:
                controller_name = addr[0]
            
            # Prompt de confirmación
            print()
            print(f"  {Colors.bold(Colors.yellow('── Solicitud de Control Remoto ──'))}")
            print(f"    {Colors.dim('De:')} {Colors.bold(Colors.cyan(controller_name))}")
            print(f"    {Colors.dim('IP:')} {addr[0]}")
            print()
            
            try:
                ans = input(f"  {Colors.yellow('?')} ¿Permitir que controle tu equipo? [S/n] ").strip().lower()
                if ans not in ('', 's', 'y'):
                    print_warning("Solicitud rechazada")
                    conn.sendall(b"NO")
                    conn.close()
                    print(f"\n  {Colors.dim('Esperando más solicitudes...')}")
                    continue
            except (KeyboardInterrupt, EOFError):
                conn.sendall(b"NO")
                conn.close()
                break
            
            # Aceptar
            conn.sendall(b"OK")
            
            # Esperar segunda conexión para canal de eventos
            print_info("Estableciendo canal de eventos...")
            evt_server.settimeout(10)
            try:
                evt_conn, _ = evt_server.accept()
                optimize_socket(evt_conn)
            except socket.timeout:
                print_error("El controlador no estableció el canal de eventos")
                conn.close()
                continue
            
            print_success(f"Control concedido a {Colors.bold(controller_name)}")
            print(f"  {Colors.dim('(La ventana remota se ha activado)')}")
            print(f"  {Colors.dim('Esperando desconexión...')}")
            
            # Iniciar agente remoto con sockets separados
            agent = RemoteAgent(conn, evt_conn, my_name)
            t_stream, t_events = agent.start()
            
            # Esperar hasta desconexión
            try:
                while not agent._stop.is_set():
                    time.sleep(0.5)
            except KeyboardInterrupt:
                agent.stop()
            
            print()
            print_info("Sesión de control finalizada")
            try:
                conn.close()
                evt_conn.close()
            except Exception:
                pass
            
            print(f"\n  {Colors.dim('Esperando más solicitudes... (Ctrl+C para salir)')}")
    
    except KeyboardInterrupt:
        print("\n")
    finally:
        discovery.stop()
        server.close()
        evt_server.close()


def cmd_control(settings):
    """Controla remotamente el escritorio de otro equipo."""
    print_banner()
    print(f"  {Colors.bold(Colors.cyan('── Controlar Equipo Remoto ──'))}")
    print()
    
    if not check_remote_deps():
        input(f"\n  {Colors.dim('[Enter] para volver...')} ")
        return
    
    my_name = settings.name
    port = REMOTE_PORT
    
    # Buscar equipos controlables en la red
    print_info("Buscando equipos con control remoto activado...")
    discovery = PeerDiscovery(tcp_port=port)
    peers = discovery.discover_peers()
    target_ip = None
    target_name = "Remoto"
    
    if not peers:
        print_warning("No se encontró ningún equipo con control remoto activado")
        try:
            target_ip = input(f"  {Colors.yellow('→')} IP del equipo a controlar: ").strip()
            if not target_ip:
                return
        except (KeyboardInterrupt, EOFError):
            return
    elif len(peers) == 1:
        peer = peers[0]
        target_ip = peer["ip"]
        target_name = peer["name"]
        print_success(f"Equipo encontrado: {Colors.bold(target_name)} ({Colors.cyan(target_ip)})")
    else:
        print_success(f"Se encontraron {len(peers)} equipos controlables:")
        for i, p in enumerate(peers, 1):
            ip_addr = p["ip"]
            print(f"    {Colors.cyan(f'[{i}]')} {Colors.bold(p['name'])} {Colors.dim(f'({ip_addr})')}")
        
        while True:
            try:
                choice = input(f"\n  {Colors.yellow('→')} Elige un equipo (1-{len(peers)}): ").strip()
                idx = int(choice) - 1
                if 0 <= idx < len(peers):
                    peer = peers[idx]
                    target_ip = peer["ip"]
                    target_name = peer["name"]
                    break
                else:
                    print_error("Opción inválida")
            except ValueError:
                print_error("Ingresa un número válido")
            except (KeyboardInterrupt, EOFError):
                return
    
    print()
    print_info(f"Conectando a {Colors.bold(target_name)} ({target_ip})...")
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((target_ip, port))
        sock.settimeout(None)
        optimize_socket(sock)
    except (ConnectionRefusedError, socket.timeout, OSError) as e:
        print_error(f"No se pudo conectar: {e}")
        print_info("Causas comunes:")
        print_info(" 1. El equipo destino NO está en la misma red Wi-Fi.")
        print_info(" 2. El Firewall de Windows o Mac del destino bloqueó la conexión.")
        print_info(" 3. Usaste la IP incorrecta (prueba las otras IPs si aparecieron varias).")
        input(f"\n  {Colors.dim('[Enter] para volver...')} ")
        return
    
    # Enviar nombre del controlador
    name_data = my_name.encode()
    sock.sendall(struct.pack("!I", len(name_data)))
    sock.sendall(name_data)
    
    # Esperar respuesta
    print_info("Esperando aprobación del usuario remoto...")
    try:
        sock.settimeout(60)  # 1 minuto para que el humano responda
        response = sock.recv(2)
        sock.settimeout(None)
    except socket.timeout:
        print_error("Sin respuesta del equipo remoto")
        sock.close()
        input(f"\n  {Colors.dim('[Enter] para volver...')} ")
        return
    
    if response != b"OK":
        print_error("El usuario remoto rechazó la solicitud de control")
        sock.close()
        input(f"\n  {Colors.dim('[Enter] para volver...')} ")
        return
    
    print_success(f"¡Conectado a {Colors.bold(target_name)}!")
    print_info("Estableciendo canal de eventos...")
    
    # Crear segundo socket para eventos
    try:
        evt_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        evt_sock.settimeout(10)
        evt_sock.connect((target_ip, REMOTE_EVT_PORT))
        evt_sock.settimeout(None)
        optimize_socket(evt_sock)
    except (ConnectionRefusedError, socket.timeout, OSError) as e:
        print_error(f"No se pudo abrir canal de eventos: {e}")
        sock.close()
        input(f"\n  {Colors.dim('[Enter] para volver...')} ")
        return
    
    print_info("Abriendo ventana de control remoto...")
    print(f"  {Colors.dim('Cierra la ventana para desconectarte')}")
    
    # Abrir visor (bloqueante — corre tkinter mainloop)
    viewer = ControllerViewer(sock, evt_sock, target_name)
    viewer.run()
    
    print()
    print_info("Sesión de control finalizada")
    try:
        sock.close()
        evt_sock.close()
    except Exception:
        pass
    
    try:
        input(f"\n  {Colors.dim('[Enter] para volver al menú...')} ")
    except (KeyboardInterrupt, EOFError):
        pass


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
        print(f"    {Colors.yellow('◆')} {Colors.bold(Colors.yellow('[3] Controlar Equipo'))} {Colors.dim('(Escritorio remoto)')}")
        print(f"    {Colors.red('◆')} {Colors.bold(Colors.red('[4] Permitir Control'))} {Colors.dim('(Compartir tu pantalla)')}")
        print()
        print(f"    {Colors.magenta('⚙')} {Colors.bold(Colors.magenta('[5] Configuración'))}   {Colors.dim(f'(Nombre: {settings.name})')}")
        print(f"    {Colors.dim('✖')} {Colors.bold(Colors.dim('[0] Salir'))}")
        print()
        
        try:
            choice = input(f"  {Colors.yellow('→')} Opción: ").strip()
            
            if choice == "1":
                cmd_receive(settings)
            elif choice == "2":
                cmd_send(settings)
            elif choice == "3":
                cmd_control(settings)
            elif choice == "4":
                cmd_allow_control(settings)
            elif choice == "5":
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
