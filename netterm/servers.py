"""Servidores embebidos de NetTerm.

Implementa la sección "Embedded servers" de MobaXterm: levantar daemons
locales (HTTP, SFTP, SSH, FTP, Telnet y Netcat) para que otros equipos, o
servicios externos, puedan alcanzar esta máquina.

Este módulo es puramente lógica: no importa GTK. Los servidores se controlan
desde la interfaz con :meth:`EmbeddedServer.start` y :meth:`EmbeddedServer.stop`
y su salida se consulta con :attr:`EmbeddedServer.log`.
"""

from __future__ import annotations

import collections
import os
import shlex
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .netops import CommandRunner

LOG_LINES = 200
"""Número de líneas de log que se conservan por servidor."""


# ----------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------
def _free_port(bind: str = "0.0.0.0", attempts: int = 20) -> int:
    """Devuelve un puerto libre pedido al kernel (bind en puerto 0)."""
    host = bind or "0.0.0.0"
    for _ in range(attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, 0))
            except OSError:
                continue
            return int(sock.getsockname()[1])
    raise OSError("No se ha encontrado ningún puerto libre")


def _local_ip() -> str:
    """IP de salida de la máquina (se obtiene sin enviar tráfico real)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("10.255.255.255", 1))
            return str(sock.getsockname()[0])
        except OSError:
            return "127.0.0.1"


def data_dir() -> Path:
    """Directorio de datos de NetTerm (``~/.local/share/netterm``)."""
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    path = Path(base) / "netterm"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def host_key_path() -> Path:
    """Ruta de la clave privada del host usada por los servidores SSH/SFTP."""
    return data_dir() / "ssh_host_rsa_key"


def load_host_key() -> Any:
    """Carga la clave RSA del host; si no existe, la genera y la guarda."""
    import paramiko

    path = host_key_path()
    if path.exists():
        try:
            return paramiko.RSAKey.from_private_key_file(str(path))
        except Exception:
            pass
    key = paramiko.RSAKey.generate(2048)
    try:
        key.write_private_key_file(str(path))
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def _user_shell() -> str:
    """Shell del usuario actual (``$SHELL`` o la del passwd)."""
    shell = os.environ.get("SHELL", "")
    if shell and os.path.exists(shell):
        return shell
    try:
        import pwd

        return pwd.getpwuid(os.getuid()).pw_shell or "/bin/sh"
    except Exception:
        return "/bin/sh"


# ----------------------------------------------------------------------
# Servidor Telnet mínimo (socketserver puro)
# ----------------------------------------------------------------------
class _TelnetHandler(socketserver.StreamRequestHandler):
    """Ecoda lo que recibe y muestra un banner al conectar."""

    banner = "NetTerm Telnet server\r\nEscribe Ctrl-D para salir.\r\n"

    def handle(self) -> None:
        try:
            self.wfile.write(self.banner.encode("utf-8", "replace"))
            self.wfile.flush()
        except OSError:
            return
        while True:
            try:
                reader = getattr(self.rfile, "read1", None)
                data = reader(1024) if reader else self.rfile.read(1024)
            except OSError:
                break
            if not data:
                break
            try:
                self.wfile.write(data)
                self.wfile.flush()
            except OSError:
                break


class _ThreadingTCPServer(socketserver.ThreadingTCPServer):
    """Servidor TCP con hilos demonio y reutilización de dirección."""

    allow_reuse_address = True
    daemon_threads = True


# ----------------------------------------------------------------------
# Interfaces paramiko (se crean bajo demanda para no depender de paramiko)
# ----------------------------------------------------------------------
def _make_ssh_interface(username: str, password: str, banner: str,
                        allow_sftp: bool = False) -> Any:
    """Crea una interfaz de servidor SSH con autenticación por contraseña."""
    import paramiko

    def _run_shell(channel: Any) -> None:
        """Arranca el shell del sistema y lo enlaza con el canal SSH."""
        env = dict(os.environ)
        env.setdefault("TERM", "xterm")
        try:
            proc = subprocess.Popen(
                [_user_shell()],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
            )
        except OSError as exc:
            _safe_send(channel, f"No se pudo iniciar el shell: {exc}\r\n")
            _safe_close(channel)
            return
        _pump_channel(channel, proc)

    def _run_command(channel: Any, command: str) -> None:
        """Ejecuta una orden remota y devuelve su salida por el canal."""
        try:
            proc = subprocess.run(command, shell=True, capture_output=True, timeout=120)
            _safe_send(channel, proc.stdout + proc.stderr)
            try:
                channel.send_exit_status(proc.returncode)
            except Exception:
                pass
        except Exception as exc:
            _safe_send(channel, f"Error ejecutando la orden: {exc}\r\n")
        _safe_close(channel)

    class _SSHInterface(paramiko.ServerInterface):
        """Autenticación por contraseña y shell del sistema."""

        def __init__(self) -> None:
            super().__init__()
            self._forwards: dict[int, tuple[str, int]] = {}

        def take_forward(self, chanid: int) -> tuple[str, int] | None:
            """Devuelve (y consume) el destino de un canal de reenvío."""
            return self._forwards.pop(chanid, None)

        def check_channel_direct_tcpip_request(self, chanid: int, origin: tuple,
                                               destination: tuple) -> int:
            """Admite el reenvío de puertos (lo usa ``ssh -L``)."""
            self._forwards[chanid] = (str(destination[0]), int(destination[1]))
            return paramiko.OPEN_SUCCEEDED

        def get_allowed_auths(self, user: str) -> str:
            return "password" if password else "none"

        def check_auth_none(self, user: str) -> int:
            return paramiko.AUTH_FAILED if password else paramiko.AUTH_SUCCESSFUL

        def check_auth_password(self, user: str, pwd: str) -> int:
            if username and user != username:
                return paramiko.AUTH_FAILED
            if password and pwd != password:
                return paramiko.AUTH_FAILED
            return paramiko.AUTH_SUCCESSFUL

        def get_banner(self) -> tuple[str, str]:
            """Banner de bienvenida (paramiko lo llama sin argumentos)."""
            return (banner, "en-US")
        def check_channel_request(self, kind: str, chanid: int) -> int:
            if kind == "session":
                return paramiko.OPEN_SUCCEEDED
            return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

        def check_channel_pty_request(self, channel: Any, term: str, width: int,
                                      height: int, pixelwidth: int,
                                      pixelheight: int, modes: str) -> bool:
            return True

        def check_channel_shell_request(self, channel: Any) -> bool:
            threading.Thread(target=_run_shell, args=(channel,), daemon=True).start()
            return True

        def check_channel_exec_request(self, channel: Any, command: str) -> bool:
            threading.Thread(target=_run_command, args=(channel, command),
                             daemon=True).start()
            return True

        def check_channel_subsystem_request(self, channel: Any, name: str) -> bool:
            """Delega en paramiko, que es quien activa el manejador SFTP."""
            if not allow_sftp or name != "sftp":
                return False
            return bool(super().check_channel_subsystem_request(channel, name))

    return _SSHInterface


def _make_sftp_interface(root: str) -> Any:
    """Crea una interfaz SFTP que sirve el directorio ``root`` enjaulado."""
    import paramiko
    from paramiko.sftp import (SFTP_FAILURE, SFTP_NO_SUCH_FILE, SFTP_OK,
                               SFTP_PERMISSION_DENIED)
    from paramiko.sftp_attr import SFTPAttributes

    base = Path(root or os.getcwd()).expanduser()
    try:
        base = base.resolve()
    except OSError:
        pass

    def _real(path: str) -> Path | None:
        """Traduce una ruta remota a una ruta local dentro de la raíz.

        La raíz virtual ``/`` del cliente corresponde al directorio servido;
        cualquier intento de salir de él (``..``) se rechaza.
        """
        virtual = (path or "/").strip()
        if not virtual.startswith("/"):
            virtual = "/" + virtual
        relative = virtual.lstrip("/")
        candidate = base / relative if relative else base
        try:
            resolved = candidate.resolve()
            resolved.relative_to(base)
        except (OSError, ValueError):
            return None
        return resolved

    class _SFTPInterface(paramiko.SFTPServerInterface):
        """Sirve ficheros de un único directorio, sin salir de él."""

        def list_folder(self, path: str) -> Any:
            real = _real(path)
            if real is None:
                return SFTP_PERMISSION_DENIED
            try:
                entries = []
                for entry in os.scandir(real):
                    attr = SFTPAttributes.from_stat(entry.stat(follow_symlinks=False))
                    attr.filename = entry.name
                    entries.append(attr)
                return entries
            except OSError as exc:
                return paramiko.SFTPServer.convert_errno(exc.errno) \
                    if exc.errno else SFTP_FAILURE

        def stat(self, path: str) -> Any:
            real = _real(path)
            if real is None:
                return SFTP_PERMISSION_DENIED
            try:
                return SFTPAttributes.from_stat(os.stat(real))
            except OSError as exc:
                return paramiko.SFTPServer.convert_errno(exc.errno) \
                    if exc.errno else SFTP_NO_SUCH_FILE

        def lstat(self, path: str) -> Any:
            real = _real(path)
            if real is None:
                return SFTP_PERMISSION_DENIED
            try:
                return SFTPAttributes.from_stat(os.lstat(real))
            except OSError as exc:
                return paramiko.SFTPServer.convert_errno(exc.errno) \
                    if exc.errno else SFTP_NO_SUCH_FILE

        def open(self, path: str, flags: int, attr: Any) -> Any:
            real = _real(path)
            if real is None:
                return SFTP_PERMISSION_DENIED
            try:
                mode = getattr(attr, "st_mode", None)
                if mode is not None:
                    fd = os.open(real, flags, mode)
                else:
                    fd = os.open(real, flags, 0o666)
            except OSError as exc:
                return paramiko.SFTPServer.convert_errno(exc.errno) \
                    if exc.errno else SFTP_FAILURE
            if (flags & os.O_WRONLY) == os.O_WRONLY:
                fstr = "ab" if flags & os.O_APPEND else "wb"
            elif (flags & os.O_RDWR) == os.O_RDWR:
                fstr = "a+b" if flags & os.O_APPEND else "r+b"
            else:
                fstr = "rb"
            try:
                handle = os.fdopen(fd, fstr)
            except OSError as exc:
                return paramiko.SFTPServer.convert_errno(exc.errno) \
                    if exc.errno else SFTP_FAILURE
            fobj = paramiko.SFTPHandle(flags)
            fobj.filename = str(real)
            fobj.readfile = handle
            fobj.writefile = handle
            return fobj

        def remove(self, path: str) -> int:
            real = _real(path)
            if real is None:
                return SFTP_PERMISSION_DENIED
            try:
                os.remove(real)
            except OSError as exc:
                return paramiko.SFTPServer.convert_errno(exc.errno) \
                    if exc.errno else SFTP_FAILURE
            return SFTP_OK

        def rename(self, oldpath: str, newpath: str) -> int:
            old = _real(oldpath)
            new = _real(newpath)
            if old is None or new is None:
                return SFTP_PERMISSION_DENIED
            try:
                os.rename(old, new)
            except OSError as exc:
                return paramiko.SFTPServer.convert_errno(exc.errno) \
                    if exc.errno else SFTP_FAILURE
            return SFTP_OK

        def mkdir(self, path: str, attr: Any) -> int:
            real = _real(path)
            if real is None:
                return SFTP_PERMISSION_DENIED
            try:
                os.mkdir(real)
            except OSError as exc:
                return paramiko.SFTPServer.convert_errno(exc.errno) \
                    if exc.errno else SFTP_FAILURE
            return SFTP_OK

        def rmdir(self, path: str) -> int:
            real = _real(path)
            if real is None:
                return SFTP_PERMISSION_DENIED
            try:
                os.rmdir(real)
            except OSError as exc:
                return paramiko.SFTPServer.convert_errno(exc.errno) \
                    if exc.errno else SFTP_FAILURE
            return SFTP_OK

        def chattr(self, path: str, attr: Any) -> int:
            real = _real(path)
            if real is None:
                return SFTP_PERMISSION_DENIED
            try:
                if attr._flags & attr.FLAG_PERMISSIONS:
                    os.chmod(real, attr.st_mode & 0o7777)
                if attr._flags & attr.FLAG_SIZE:
                    os.truncate(real, attr.st_size)
                if attr._flags & attr.FLAG_UIDGID:
                    os.chown(real, attr.st_uid, attr.st_gid)
            except OSError as exc:
                return paramiko.SFTPServer.convert_errno(exc.errno) \
                    if exc.errno else SFTP_FAILURE
            return SFTP_OK

        def symlink(self, target_path: str, path: str) -> int:
            real = _real(path)
            if real is None:
                return SFTP_PERMISSION_DENIED
            try:
                os.symlink(target_path, real)
            except OSError as exc:
                return paramiko.SFTPServer.convert_errno(exc.errno) \
                    if exc.errno else SFTP_FAILURE
            return SFTP_OK

        def readlink(self, path: str) -> Any:
            real = _real(path)
            if real is None:
                return SFTP_PERMISSION_DENIED
            try:
                return os.readlink(real)
            except OSError as exc:
                return paramiko.SFTPServer.convert_errno(exc.errno) \
                    if exc.errno else SFTP_FAILURE

    return _SFTPInterface


def _safe_send(channel: Any, data: bytes) -> None:
    """Envía datos al canal ignorando errores de conexión."""
    try:
        channel.sendall(data)
    except Exception:
        pass


def _safe_close(channel: Any) -> None:
    """Cierra el canal ignorando errores."""
    try:
        channel.close()
    except Exception:
        pass


def _pump_channel(channel: Any, proc: subprocess.Popen) -> None:
    """Conecta el canal SSH con un proceso local (entrada y salida)."""

    def to_process() -> None:
        try:
            while True:
                data = channel.recv(4096)
                if not data:
                    break
                proc.stdin.write(data)
                proc.stdin.flush()
        except Exception:
            pass
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass

    def from_process() -> None:
        try:
            for line in iter(proc.stdout.readline, b""):
                _safe_send(channel, line)
        except Exception:
            pass

    threads = [threading.Thread(target=to_process, daemon=True),
               threading.Thread(target=from_process, daemon=True)]
    for thread in threads:
        thread.start()
    try:
        proc.wait(timeout=300)
    except subprocess.TimeoutExpired:
        proc.kill()
    try:
        channel.send_exit_status(proc.returncode or 0)
    except Exception:
        pass
    _safe_close(channel)


# ----------------------------------------------------------------------
# Servidor embebido
# ----------------------------------------------------------------------
class EmbeddedServer:
    """Un servidor local embebido (HTTP, SFTP, SSH, FTP, Telnet o Netcat).

    Ejemplos::

        srv = EmbeddedServer("http", port=0, root_dir="/tmp")
        ok, msg = srv.start()
        print(srv.url())
        srv.stop()
    """

    KINDS: dict[str, str] = {
        "http": "Servidor HTTP",
        "sftp": "Servidor SFTP",
        "ssh": "Servidor SSH",
        "ftp": "Servidor FTP",
        "telnet": "Servidor Telnet",
        "ncat": "Netcat listener",
    }

    def __init__(self, kind: str, bind: str = "0.0.0.0", port: int = 0,
                 root_dir: str = "", username: str = "", password: str = "",
                 extra: str = ""):
        self.kind = (kind or "").strip().lower()
        self.bind = bind or "0.0.0.0"
        self.root_dir = root_dir
        self.username = username
        self.password = password
        self.extra = extra
        self._port = int(port or 0)
        self._logs: collections.deque[str] = collections.deque(maxlen=LOG_LINES)
        self._runner: CommandRunner | None = None
        self._tcp: _ThreadingTCPServer | None = None
        self._ftp_server: Any = None
        self._listener: socket.socket | None = None
        self._transports: set[Any] = set()
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # -- estado -------------------------------------------------------
    @property
    def running(self) -> bool:
        """Indica si el servidor está activo."""
        if self._runner is not None:
            return bool(self._runner.running)
        if self._tcp is not None:
            return not self._stop.is_set()
        if self._listener is not None:
            return not self._stop.is_set()
        return False

    @property
    def port(self) -> int:
        """Puerto real en el que escucha el servidor."""
        return self._port

    @property
    def log(self) -> list[str]:
        """Últimas líneas de salida del servidor."""
        with self._lock:
            return list(self._logs)

    @property
    def label(self) -> str:
        """Nombre legible del tipo de servidor."""
        return self.KINDS.get(self.kind, self.kind or "Servidor")

    # -- internos -----------------------------------------------------
    def _log(self, message: str) -> None:
        """Añade una línea al log del servidor."""
        if not message:
            return
        with self._lock:
            self._logs.append(message.rstrip())

    def _pump_runner(self, runner: CommandRunner) -> None:
        """Vuelca la salida del proceso en el log (hilo demonio)."""
        try:
            for line in runner.lines():
                text = (line or "").rstrip()
                if text:
                    self._log(text)
                elif not runner.running:
                    break
        except Exception:
            pass

    def _spawn(self, target: Callable[[], None]) -> threading.Thread:
        """Lanza una función en un hilo demonio y lo recuerda."""
        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        self._threads.append(thread)
        return thread

    # -- ciclo de vida -------------------------------------------------
    def start(self) -> tuple[bool, str]:
        """Arranca el servidor. Devuelve ``(ok, mensaje)``."""
        if self.running:
            return (False, "El servidor ya está en marcha")
        self._stop.clear()
        handlers = {
            "http": self._start_http,
            "ncat": self._start_ncat,
            "telnet": self._start_telnet,
            "sftp": self._start_sftp,
            "ssh": self._start_ssh,
            "ftp": self._start_ftp,
        }
        handler = handlers.get(self.kind)
        if handler is None:
            return (False, f"Tipo de servidor desconocido: «{self.kind}»")
        try:
            return handler()
        except Exception as exc:  # pragma: no cover - red de seguridad
            self._log(f"error: {exc}")
            return (False, f"No se pudo iniciar el servidor: {exc}")

    def stop(self) -> None:
        """Detiene el servidor y libera el puerto."""
        self._stop.set()
        if self._runner is not None:
            try:
                self._runner.stop()
            except Exception:
                pass
            self._runner = None
        if self._tcp is not None:
            try:
                self._tcp.shutdown()
            except Exception:
                pass
            try:
                self._tcp.server_close()
            except Exception:
                pass
            self._tcp = None
        if self._ftp_server is not None:
            try:
                self._ftp_server.close_all()
            except Exception:
                pass
            self._ftp_server = None
        for transport in list(self._transports):
            try:
                transport.close()
            except Exception:
                pass
        self._transports.clear()
        if self._listener is not None:
            try:
                self._listener.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._listener.close()
            except Exception:
                pass
            self._listener = None
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=1.0)
        self._threads.clear()
        self._log("servidor detenido")

    # -- implementación de cada tipo -----------------------------------
    def _start_http(self) -> tuple[bool, str]:
        """Servidor HTTP de ficheros con ``python3 -m http.server``."""
        root = os.path.abspath(os.path.expanduser(self.root_dir or os.getcwd()))
        if not os.path.isdir(root):
            return (False, f"El directorio «{root}» no existe")
        try:
            port = self._port or _free_port(self.bind)
        except OSError as exc:
            return (False, str(exc))
        cmd = [sys.executable, "-m", "http.server", str(port),
               "--bind", self.bind, "--directory", root]
        cmd += shlex.split(self.extra or "")
        runner = CommandRunner(cmd, cwd=root,
                               label=f"{self.label} en {self.bind}:{port}")
        try:
            runner.start()
        except Exception as exc:
            return (False, f"No se pudo iniciar el servidor HTTP: {exc}")
        time.sleep(0.3)
        if not runner.running:
            output = "".join(runner.output).strip()
            self._log(output or "el proceso terminó inmediatamente")
            return (False, f"El servidor HTTP se detuvo: {output or 'sin salida'}")
        self._runner = runner
        self._port = port
        self._log(f"Servidor HTTP en {self.bind}:{port} (raíz: {root})")
        self._spawn(lambda: self._pump_runner(runner))
        return (True, f"Servidor HTTP en http://{self._display_host()}:{port}")

    def _start_ncat(self) -> tuple[bool, str]:
        """Escucha Netcat que ejecuta una orden al conectar."""
        tool = shutil.which("ncat") or shutil.which("nc")
        if not tool:
            return (False, "No se ha encontrado «ncat» ni «nc» en el sistema")
        try:
            port = self._port or _free_port(self.bind)
        except OSError as exc:
            return (False, str(exc))
        command = self.extra or "echo 'NetTerm: conexión recibida'"
        if os.path.basename(tool) == "ncat":
            cmd = [tool, "-l", "-k", "--sh-exec", command, self.bind, str(port)]
        else:
            cmd = [tool, "-l", "-k", "-c", command, self.bind, str(port)]
        runner = CommandRunner(cmd, label=f"{self.label} en {self.bind}:{port}")
        try:
            runner.start()
        except Exception as exc:
            return (False, f"No se pudo iniciar Netcat: {exc}")
        time.sleep(0.3)
        if not runner.running:
            output = "".join(runner.output).strip()
            self._log(output or "el proceso terminó inmediatamente")
            return (False, f"Netcat se detuvo: {output or 'sin salida'}")
        self._runner = runner
        self._port = port
        self._log(f"Netcat escuchando en {self.bind}:{port}: {command}")
        self._spawn(lambda: self._pump_runner(runner))
        return (True, f"Netcat escuchando en {self.bind}:{port}")

    def _start_telnet(self) -> tuple[bool, str]:
        """Servidor Telnet mínimo implementado con ``socketserver``."""
        banner = self.extra or _TelnetHandler.banner
        handler = type("_Handler", (_TelnetHandler,), {"banner": banner})
        try:
            server = _ThreadingTCPServer((self.bind, self._port), handler)
        except OSError as exc:
            return (False, f"No se pudo abrir el puerto {self.bind}: "
                           f"{exc.strerror or exc}")
        self._tcp = server
        self._port = int(server.server_address[1])
        self._log(f"Servidor Telnet en {self.bind}:{self._port}")
        self._spawn(server.serve_forever)
        return (True, f"Servidor Telnet en {self.bind}:{self._port}")

    def _start_sftp(self) -> tuple[bool, str]:
        """Servidor SFTP con paramiko servido desde ``root_dir``."""
        try:
            import paramiko  # noqa: F401
        except ImportError:
            return (False, "paramiko no está instalado; no se puede el servidor SFTP")
        root = os.path.abspath(os.path.expanduser(self.root_dir or os.getcwd()))
        if not os.path.isdir(root):
            return (False, f"El directorio «{root}» no existe")
        try:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.bind, self._port))
            listener.listen(16)
        except OSError as exc:
            return (False, f"No se pudo abrir el puerto {self.bind}: "
                           f"{exc.strerror or exc}")
        self._listener = listener
        self._port = int(listener.getsockname()[1])
        try:
            host_key = load_host_key()
        except Exception as exc:
            listener.close()
            self._listener = None
            return (False, f"No se pudo preparar la clave del host: {exc}")
        self._log(f"Servidor SFTP en {self.bind}:{self._port} (raíz: {root})")
        self._spawn(lambda: self._accept_loop(listener, host_key, sftp=True, root=root))
        return (True, f"Servidor SFTP en {self.bind}:{self._port}")

    def _start_ssh(self) -> tuple[bool, str]:
        """Servidor SSH mínimo con paramiko (shell del sistema)."""
        try:
            import paramiko  # noqa: F401
        except ImportError:
            return (False, "paramiko no está instalado; no se puede el servidor SSH")
        try:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.bind, self._port))
            listener.listen(16)
        except OSError as exc:
            return (False, f"No se pudo abrir el puerto {self.bind}: "
                           f"{exc.strerror or exc}")
        self._listener = listener
        self._port = int(listener.getsockname()[1])
        try:
            host_key = load_host_key()
        except Exception as exc:
            listener.close()
            self._listener = None
            return (False, f"No se pudo preparar la clave del host: {exc}")
        self._log(f"Servidor SSH en {self.bind}:{self._port}")
        self._spawn(lambda: self._accept_loop(listener, host_key, sftp=False))
        return (True, f"Servidor SSH en {self.bind}:{self._port}")

    def _start_ftp(self) -> tuple[bool, str]:
        """Servidor FTP con pyftpdlib (si está disponible)."""
        try:
            from pyftpdlib.authorizers import DummyAuthorizer
            from pyftpdlib.handlers import FTPHandler
            from pyftpdlib.servers import FTPServer
        except ImportError:
            return (False, "pyftpdlib no está instalado; usa el servidor SFTP o HTTP")
        root = os.path.abspath(os.path.expanduser(self.root_dir or os.getcwd()))
        if not os.path.isdir(root):
            return (False, f"El directorio «{root}» no existe")
        authorizer = DummyAuthorizer()
        user = self.username or "netterm"
        authorizer.add_user(user, self.password or "", root, perm="elradfmwMT")
        handler = type("_NetTermFTPHandler", (FTPHandler,), {
            "authorizer": authorizer,
            "banner": f"{self.label} de NetTerm",
            "use_sendfile": False,
        })
        try:
            server = FTPServer((self.bind, self._port), handler)
        except OSError as exc:
            return (False, f"No se pudo abrir el puerto {self.bind}: "
                           f"{exc.strerror or exc}")
        self._port = int(server.address[1])
        self._log(f"Servidor FTP en {self.bind}:{self._port} (raíz: {root})")
        self._spawn(lambda: server.serve_forever(timeout=0.5))
        self._ftp_server = server
        return (True, f"Servidor FTP en {self.bind}:{self._port}")

    # -- paramiko ------------------------------------------------------
    def _pipe_forward(self, channel: Any, destino: tuple[str, int]) -> None:
        """Conecta un canal SSH reenviado con el destino solicitado."""
        host, port = destino
        try:
            sock = socket.create_connection((host, port), timeout=10)
        except OSError as exc:
            self._log(f"no se pudo conectar con {host}:{port}: {exc}")
            _safe_close(channel)
            return

        def to_socket() -> None:
            try:
                while True:
                    data = channel.recv(4096)
                    if not data:
                        break
                    sock.sendall(data)
            except Exception:
                pass
            finally:
                try:
                    sock.shutdown(socket.SHUT_WR)
                except Exception:
                    pass

        def from_socket() -> None:
            try:
                while True:
                    data = sock.recv(4096)
                    if not data:
                        break
                    channel.sendall(data)
            except Exception:
                pass

        hilos = [threading.Thread(target=to_socket, daemon=True),
                 threading.Thread(target=from_socket, daemon=True)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(timeout=30)
        _safe_close(channel)
        try:
            sock.close()
        except Exception:
            pass

    def _accept_loop(self, listener: socket.socket, host_key: Any,
                     sftp: bool, root: str = "") -> None:
        """Acepta conexiones y lanza un hilo por cada cliente."""
        import paramiko

        while not self._stop.is_set():
            try:
                client, addr = listener.accept()
            except OSError:
                break
            self._log(f"conexión desde {addr[0]}:{addr[1]}")
            thread = threading.Thread(
                target=self._handle_client,
                args=(client, host_key, sftp, root),
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)
        self._log("bucle de aceptación terminado")

    def _handle_client(self, client: socket.socket, host_key: Any,
                       sftp: bool, root: str) -> None:
        """Atiende una conexión entrante con paramiko."""
        import paramiko

        transport = None
        try:
            transport = paramiko.Transport(client)
            transport.add_server_key(host_key)
            if sftp:
                interface = _make_sftp_interface(root)
                server = _make_ssh_interface(self.username, self.password,
                                             f"{self.label} de NetTerm\r\n",
                                             allow_sftp=True)()
                transport.set_subsystem_handler("sftp", paramiko.SFTPServer,
                                                sftp_si=interface)
            else:
                server = _make_ssh_interface(self.username, self.password,
                                             f"{self.label} de NetTerm\r\n")()
            self._transports.add(transport)
            transport.start_server(server=server)
            while transport.is_active() and not self._stop.is_set():
                channel = transport.accept(timeout=1)
                if channel is None:
                    continue
                destino = server.take_forward(channel.chanid)
                if destino is not None:
                    self._log(f"reenvío hacia {destino[0]}:{destino[1]}")
                    threading.Thread(target=self._pipe_forward,
                                     args=(channel, destino), daemon=True).start()
                else:
                    self._log(f"canal abierto: {channel.get_name()}")
        except Exception as exc:
            self._log(f"error: {exc}")
        finally:
            self._transports.discard(transport)
            if transport is not None:
                try:
                    transport.close()
                except Exception:
                    pass
            try:
                client.close()
            except Exception:
                pass

    # -- ayudas --------------------------------------------------------
    def _display_host(self) -> str:
        """Dirección que se muestra al usuario (IP real si escucha en *)."""
        if self.bind in ("", "0.0.0.0", "::", "*"):
            return _local_ip()
        return self.bind

    def url(self) -> str:
        """URL del servidor en función del tipo."""
        host = self._display_host()
        port = self._port
        if self.kind == "http":
            return f"http://{host}:{port}"
        if self.kind in ("sftp", "ssh", "ftp"):
            user = f"{self.username}@" if self.username else ""
            scheme = "sftp" if self.kind == "sftp" else self.kind
            return f"{scheme}://{user}{host}:{port}"
        if self.kind == "telnet":
            return f"telnet://{host}:{port}"
        return f"tcp://{host}:{port}"

    def __repr__(self) -> str:
        estado = "activo" if self.running else "parado"
        return f"<EmbeddedServer {self.kind} {self.bind}:{self._port} {estado}>"
