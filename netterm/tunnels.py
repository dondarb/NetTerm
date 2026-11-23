"""Gestión de túneles SSH (port forwarding) de NetTerm.

Equivale a la sección "SSH tunnels (port forwarding)" de MobaXterm: tunnels
locales (``-L``), remotos (``-R``) y dinámicos SOCKS (``-D``) apoyados en el
binario ``ssh`` del sistema.

Los túneles se lanzan como procesos independientes y su salida (stdout y
stderr) se recoge en un hilo lector para poder mostrar errores típicos como
``bind: Address already in use`` o ``channel open failed``.
"""

from __future__ import annotations

import collections
import os
import shlex
import shutil
import socket
import subprocess
import threading

from .session import Session, Tunnel

LOG_LINES = 200
"""Número de líneas de log que se conservan por túnel."""


def build_ssh_args(session: Session, tunnel: Tunnel) -> list[str]:
    """Construye el argv completo de ``ssh`` para el túnel indicado."""
    args: list[str] = [
        "ssh",
        "-N",                                        # no abrir shell
        "-o", "ExitOnForwardFailure=yes",            # fallo si no puede enlazar
        "-o", "ServerAliveInterval=30",              # mantiene viva la sesión
        "-o", "StrictHostKeyChecking=accept-new",    # no pregunta por claves
        "-o", "ConnectTimeout=10",
    ]
    args += shlex.split(tunnel.spec() or "")
    args += ["-p", str(session.port or 22)]
    key_file = os.path.expanduser(session.key_file or "")
    if key_file and os.path.exists(key_file):
        args += ["-i", key_file]
    if session.jump_host:
        jump = session.jump_host
        if session.jump_user:
            jump = f"{session.jump_user}@{jump}"
        if session.jump_port and int(session.jump_port) != 22:
            jump = f"{jump}:{session.jump_port}"
        args += ["-J", jump]
    if session.compress:
        args += ["-o", "Compression=yes"]
    if session.keepalive:
        args += ["-o", f"ServerAliveCountMax={int(session.keepalive)}"]
    if session.username:
        args.append(f"{session.username}@{session.host}")
    else:
        args.append(session.host)
    return args


def short_describe(tunnel: Tunnel) -> str:
    """Descripción corta del túnel: ``local 8080->10.0.0.1:80``."""
    if tunnel.kind == "dynamic":
        return f"dynamic {tunnel.bind_port}"
    arrow = "->" if tunnel.kind == "local" else "<-"
    return f"{tunnel.kind} {tunnel.bind_port}{arrow}{tunnel.target_host}:{tunnel.target_port}"


def free_port(bind: str = "127.0.0.1") -> int:
    """Devuelve un puerto libre pedido al kernel."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((bind or "127.0.0.1", 0))
        return int(sock.getsockname()[1])


class TunnelHandle:
    """Un túnel en marcha: proceso ``ssh`` más su registro de salida."""

    def __init__(self, session_name: str, tunnel: Tunnel,
                 process: subprocess.Popen | None = None, error: str = ""):
        self.session_name = session_name
        self.tunnel = tunnel
        self.process = process
        self._logs: collections.deque[str] = collections.deque(maxlen=LOG_LINES)
        self._error = error
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None
        if error:
            self._log(error)

    # -- estado -------------------------------------------------------
    @property
    def running(self) -> bool:
        """Indica si el proceso ``ssh`` sigue vivo."""
        return self.process is not None and self.process.poll() is None

    @property
    def log(self) -> list[str]:
        """Últimas líneas de salida del túnel."""
        with self._lock:
            return list(self._logs)

    @property
    def error(self) -> str:
        """Último mensaje de error registrado."""
        with self._lock:
            return self._error

    # -- internos -----------------------------------------------------
    def _log(self, message: str) -> None:
        """Añade una línea al log del túnel."""
        text = (message or "").rstrip()
        if not text:
            return
        with self._lock:
            self._logs.append(text)

    def _set_error(self, message: str) -> None:
        """Guarda el último error conocido del túnel."""
        text = (message or "").rstrip()
        if not text:
            return
        with self._lock:
            self._error = text

    def _pump(self) -> None:
        """Lee la salida del proceso y la vuelca en el log."""
        process = self.process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                self._log(line)
        except Exception:
            pass
        finally:
            try:
                process.wait(timeout=5)
            except Exception:
                pass
            code = process.poll()
            if code:
                with self._lock:
                    last = self._logs[-1] if self._logs else ""
                self._set_error(last or f"ssh terminó con código {code}")

    # -- acciones -----------------------------------------------------
    def stop(self) -> None:
        """Detiene el túnel y termina el proceso ``ssh``."""
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            try:
                process.terminate()
            except Exception:
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except Exception:
                    pass
                try:
                    process.wait(timeout=2)
                except Exception:
                    pass
        for stream in (process.stdout, process.stderr, process.stdin):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass
        self._log("túnel detenido")

    def describe(self) -> str:
        """Descripción legible del túnel y de su estado."""
        estado = "activo" if self.running else "detenido"
        return f"{self.session_name}: {self.tunnel.describe()} [{estado}]"

    def __repr__(self) -> str:
        return f"<TunnelHandle {self.session_name} {self.tunnel.describe()}>"


class TunnelManager:
    """Administra los túneles SSH activos de la aplicación."""

    def __init__(self) -> None:
        self._handles: list[TunnelHandle] = []
        self._lock = threading.Lock()

    # -- consulta -----------------------------------------------------
    def list(self) -> list[TunnelHandle]:
        """Devuelve los túneles registrados (activos o no)."""
        with self._lock:
            return list(self._handles)

    def active(self) -> list[TunnelHandle]:
        """Devuelve únicamente los túneles que siguen en marcha."""
        return [handle for handle in self.list() if handle.running]

    def active_summary(self) -> str:
        """Resumen estilo «2 túneles activos: local 8080->10.0.0.1:80, ...»."""
        active = self.active()
        if not active:
            return "sin túneles activos"
        parts = ", ".join(short_describe(handle.tunnel) for handle in active)
        plural = "túnel activo" if len(active) == 1 else "túneles activos"
        return f"{len(active)} {plural}: {parts}"

    # -- acciones -----------------------------------------------------
    def add(self, session: Session, tunnel: Tunnel) -> TunnelHandle:
        """Levanta un túnel nuevo y devuelve su asa de control.

        Si el puerto local es 0 se asigna uno libre (y se actualiza el túnel,
        para que la interfaz pueda mostrar el puerto real).
        """
        if shutil.which("ssh") is None:
            handle = TunnelHandle(session.name, tunnel, None,
                                  "«ssh» no está instalado")
            with self._lock:
                self._handles.append(handle)
            return handle

        if not tunnel.bind_port:
            try:
                tunnel.bind_port = free_port(tunnel.bind_address or "127.0.0.1")
            except OSError:
                pass

        argv = build_ssh_args(session, tunnel)
        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            handle = TunnelHandle(session.name, tunnel, None,
                                  f"No se pudo ejecutar ssh: {exc}")
            with self._lock:
                self._handles.append(handle)
            return handle

        handle = TunnelHandle(session.name, tunnel, process)
        handle._log("ssh " + " ".join(shlex.quote(a) for a in argv))
        reader = threading.Thread(target=handle._pump, daemon=True)
        handle._reader = reader
        reader.start()
        with self._lock:
            self._handles.append(handle)
        return handle

    def remove(self, handle: TunnelHandle) -> None:
        """Detiene un túnel y lo quita de la lista."""
        if handle is None:
            return
        try:
            handle.stop()
        finally:
            with self._lock:
                if handle in self._handles:
                    self._handles.remove(handle)

    def remove_all(self) -> None:
        """Detiene y descarta todos los túneles."""
        for handle in self.list():
            try:
                handle.stop()
            except Exception:
                pass
        with self._lock:
            self._handles.clear()
