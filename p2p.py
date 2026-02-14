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

VERSION = "1.0.0"
DEFAULT_TCP_PORT = 50506
DEFAULT_UDP_PORT = 50505
BROADCAST_INTERVAL = 1.0      # segundos entre broadcasts
CHUNK_SIZE = 65536             # 64 KB
DISCOVERY_TIMEOUT = 15         # segundos buscando peers
MAGIC = b"P2P1"                # identificador de protocolo

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
    """Muestra banner de la app."""
    banner = f"""
{Colors.bold(Colors.cyan('  ╔══════════════════════════════════════╗'))}
{Colors.bold(Colors.cyan('  ║'))}     {Colors.bold('P2P File Transfer')} {Colors.dim(f'v{VERSION}')}        {Colors.bold(Colors.cyan('║'))}
{Colors.bold(Colors.cyan('  ║'))}   {Colors.dim('Sin internet · Red local · Directo')}  {Colors.bold(Colors.cyan('║'))}
{Colors.bold(Colors.cyan('  ╚══════════════════════════════════════╝'))}
"""
    print(banner)


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
    Retorna (ruta_zip, nombre_original, cantidad_archivos).
    """
    source = Path(source_path).resolve()
    if not source.exists():
        print_error(f"No existe: {source}")
        sys.exit(1)

    original_name = source.name
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

    return zip_path, original_name, file_count


def decompress_zip(zip_path, dest_dir):
    """Descomprime ZIP en directorio destino. Retorna lista de archivos."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.namelist()
        zf.extractall(dest_dir)
    return members


# ─── Descubrimiento UDP ─────────────────────────────────────────────────────

class PeerDiscovery:
    """Maneja broadcast/descubrimiento de peers en la red local."""

    def __init__(self, udp_port=DEFAULT_UDP_PORT, tcp_port=DEFAULT_TCP_PORT):
        self.udp_port = udp_port
        self.tcp_port = tcp_port
        self._stop = threading.Event()

    def start_broadcasting(self):
        """Anuncia disponibilidad del receptor via UDP broadcast."""
        hostname = socket.gethostname()
        local_ip = get_local_ip()
        msg = json.dumps({
            "type": "P2P_READY",
            "hostname": hostname,
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

    def discover_peer(self, timeout=DISCOVERY_TIMEOUT):
        """Busca un receptor en la red local. Retorna (ip, port) o None."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError:
            pass  # Windows no soporta SO_REUSEPORT
        sock.settimeout(1.0)
        sock.bind(("", self.udp_port))

        local_ip = get_local_ip()
        deadline = time.time() + timeout
        found = None

        while time.time() < deadline and not self._stop.is_set():
            remaining = deadline - time.time()
            bar_w = 20
            pct = 1 - (remaining / timeout)
            filled = int(bar_w * pct)
            bar = "▓" * filled + "░" * (bar_w - filled)
            sys.stdout.write(
                f"\r  {Colors.yellow('◌')} Buscando receptor... "
                f"{Colors.dim(bar)} {Colors.dim(f'{int(remaining)}s')}"
            )
            sys.stdout.flush()

            try:
                data, addr = sock.recvfrom(1024)
                try:
                    info = json.loads(data.decode())
                    if info.get("type") == "P2P_READY":
                        peer_ip = info.get("ip", addr[0])
                        # No conectarse a sí mismo
                        if peer_ip != local_ip or addr[0] != local_ip:
                            found = (peer_ip, info.get("tcp_port", DEFAULT_TCP_PORT), info.get("hostname", "?"))
                            break
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
            except socket.timeout:
                continue

        sock.close()
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()
        return found

    def stop(self):
        self._stop.set()


# ─── Transferencia ───────────────────────────────────────────────────────────

def send_file(sock, zip_path, original_name, file_count):
    """Envía un archivo ZIP por socket TCP con header JSON."""
    file_size = os.path.getsize(zip_path)
    checksum = compute_checksum(zip_path)

    # Header
    header = json.dumps({
        "original_name": original_name,
        "file_count": file_count,
        "size": file_size,
        "checksum": checksum
    }).encode()

    # Enviar magic + header length + header
    sock.sendall(MAGIC)
    sock.sendall(struct.pack("!I", len(header)))
    sock.sendall(header)

    # Esperar ACK
    ack = sock.recv(2)
    if ack != b"OK":
        print_error("Receptor rechazó la transferencia")
        return False

    # Enviar datos
    print_info("Transfiriendo...")
    start_time = time.time()
    sent = 0

    with open(zip_path, "rb") as f:
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
    """Recibe un archivo ZIP por socket TCP y lo descomprime."""
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
    original_name = header["original_name"]
    file_count = header["file_count"]
    file_size = header["size"]
    expected_checksum = header["checksum"]

    print()
    print(f"  {Colors.bold(Colors.magenta('── Transferencia entrante ──'))}")
    print(f"  {Colors.dim('Nombre:')}  {Colors.bold(original_name)}")
    print(f"  {Colors.dim('Tamaño:')}  {Colors.bold(format_size(file_size))}")
    print(f"  {Colors.dim('Archivos:')} {Colors.bold(str(file_count))}")
    print()

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

    # Descomprimir
    dest_path = Path(dest_dir).resolve()
    dest_path.mkdir(parents=True, exist_ok=True)

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

def cmd_send(args):
    """Comando: enviar archivo/carpeta."""
    source = Path(args.path).resolve()
    if not source.exists():
        print_error(f"No existe: {source}")
        sys.exit(1)

    local_ip = get_local_ip()
    print_info(f"Tu IP: {Colors.bold(local_ip)}")
    print_info(f"Fuente: {Colors.bold(str(source))}")
    print()

    # Comprimir
    zip_path, original_name, file_count = compress_path(source)
    print()

    # Encontrar receptor
    target_ip = args.to
    target_port = args.port

    if not target_ip:
        print_info("Buscando receptor en la red local...")
        discovery = PeerDiscovery(tcp_port=target_port)
        peer = discovery.discover_peer()

        if peer:
            target_ip, target_port, peer_hostname = peer
            print_success(
                f"Receptor encontrado: {Colors.bold(peer_hostname)} "
                f"({Colors.cyan(target_ip)}:{target_port})"
            )
        else:
            print_warning("No se encontró receptor automáticamente")
            try:
                target_ip = input(f"  {Colors.yellow('→')} Ingresa la IP del receptor: ").strip()
                if not target_ip:
                    print_error("IP vacía, cancelando")
                    sys.exit(1)
            except (KeyboardInterrupt, EOFError):
                print("\n")
                print_info("Cancelado")
                sys.exit(0)
    else:
        print_info(f"Conectando a: {Colors.bold(target_ip)}:{target_port}")

    print()

    # Conectar y enviar
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((target_ip, target_port))
        sock.settimeout(None)
        send_file(sock, zip_path, original_name, file_count)
    except ConnectionRefusedError:
        print_error(f"Conexión rechazada en {target_ip}:{target_port}")
        print_info("Asegúrate de que el receptor esté ejecutando: python3 p2p.py receive")
    except socket.timeout:
        print_error("Timeout al conectar")
    except Exception as e:
        print_error(f"Error: {e}")
    finally:
        try:
            sock.close()
        except Exception:
            pass
        # Limpiar ZIP temporal
        shutil.rmtree(os.path.dirname(zip_path), ignore_errors=True)

    print()


# ─── Modo Receiver ───────────────────────────────────────────────────────────

def cmd_receive(args):
    """Comando: esperar y recibir archivos."""
    dest_dir = args.dir
    port = args.port
    local_ip = get_local_ip()

    print_info(f"Tu IP: {Colors.bold(local_ip)}")
    print_info(f"Puerto: {Colors.bold(str(port))}")
    print_info(f"Destino: {Colors.bold(dest_dir)}")
    print()

    # Iniciar servidor TCP
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("0.0.0.0", port))
    except OSError as e:
        print_error(f"No se pudo usar el puerto {port}: {e}")
        sys.exit(1)

    server.listen(1)

    # Iniciar broadcast de descubrimiento
    discovery = PeerDiscovery(tcp_port=port)
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

            print(f"  {Colors.dim('Esperando más conexiones... (Ctrl+C para salir)')}")

    except KeyboardInterrupt:
        print("\n")
        print_info("Receptor detenido")
    finally:
        discovery.stop()
        server.close()

    print()


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="P2P File Transfer — Transfiere archivos sin internet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  Receptor:   python3 p2p.py receive
  Emisor:     python3 p2p.py send ./mi_carpeta
  Con IP:     python3 p2p.py send archivo.pdf --to 192.168.1.50
        """
    )
    subparsers = parser.add_subparsers(dest="command", help="Modo de operación")

    # send
    send_parser = subparsers.add_parser("send", help="Enviar archivo o carpeta")
    send_parser.add_argument("path", help="Ruta del archivo o carpeta a enviar")
    send_parser.add_argument("--to", default=None, help="IP del receptor (auto-detecta si no se indica)")
    send_parser.add_argument("--port", type=int, default=DEFAULT_TCP_PORT, help=f"Puerto TCP (default: {DEFAULT_TCP_PORT})")

    # receive
    recv_parser = subparsers.add_parser("receive", help="Recibir archivos")
    recv_parser.add_argument("--dir", default=os.path.join(str(Path.home()), "Downloads"),
                             help="Directorio destino (default: ~/Downloads)")
    recv_parser.add_argument("--port", type=int, default=DEFAULT_TCP_PORT, help=f"Puerto TCP (default: {DEFAULT_TCP_PORT})")

    args = parser.parse_args()

    print_banner()

    if args.command == "send":
        cmd_send(args)
    elif args.command == "receive":
        cmd_receive(args)
    else:
        parser.print_help()
        print()


if __name__ == "__main__":
    main()
