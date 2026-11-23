"""Lanzadores de sesiones remotas de NetTerm.

Prepara las órdenes de los clientes de escritorio remoto y de red que
MobaXterm ofrece (RDP, VNC, XDMCP, FTP, SFTP, Telnet, Rsh, Mosh y navegador)
y las ejecuta de forma desacoplada.

Sólo lógica: la capa visual decide cuándo lanzar cada sesión.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess

from .session import Session

# Puertos típicos de VNC: 5900 + número de display.
VNC_BASE_PORT = 5900


def _host(session: Session) -> str:
    """Host de la sesión (o cadena vacía)."""
    return (session.host or "").strip()


def _port(session: Session, default: int = 0) -> int:
    """Puerto de la sesión."""
    try:
        return int(session.port or default)
    except (TypeError, ValueError):
        return default


def _user(session: Session) -> str:
    """Usuario de la sesión."""
    return (session.username or "").strip()


def _split(extra: str) -> list[str]:
    """Divide los argumentos extra respetando comillas."""
    if not extra:
        return []
    try:
        return shlex.split(extra)
    except ValueError:
        return extra.split()


def _first_available(*names: str) -> str:
    """Devuelve el primer ejecutable disponible de la lista."""
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return ""


def rdp_command(session: Session, extra: str = "") -> list[str]:
    """Orden para abrir una sesión RDP.

    Prefiere ``xfreerdp`` (FreeRDP, instalado en Fedora) y cae en ``remmina``.
    """
    host = _host(session)
    port = _port(session, 3389)
    if _first_available("xfreerdp", "xfreerdp3"):
        cmd = ["xfreerdp", f"/v:{host}:{port}", "/cert:ignore"]
        user = _user(session)
        if user:
            cmd.append(f"/u:{user}")
        if session.password:
            cmd.append(f"/p:{session.password}")
        home = os.path.expanduser("~")
        if os.path.isdir(home):
            cmd.append(f"/drive:home,{home}")
        cmd.append("/scale:100")
        cmd += _split(extra)
        return cmd
    if _first_available("remmina"):
        cmd = ["remmina", "--protocol=rdp", f"--server={host}", f"--port={port}"]
        user = _user(session)
        if user:
            cmd.append(f"--user={user}")
        cmd += _split(extra)
        return cmd
    # Último recurso: se devuelve igualmente para que «launch» avise.
    return ["xfreerdp", f"/v:{host}:{port}", "/cert:ignore"]


def vnc_command(session: Session, extra: str = "") -> list[str]:
    """Orden para abrir una sesión VNC (``vncviewer`` o ``remmina``)."""
    host = _host(session)
    port = _port(session, VNC_BASE_PORT)
    if ":" in host:
        destino = host
    elif port >= VNC_BASE_PORT:
        destino = f"{host}::{port - VNC_BASE_PORT}"
    else:
        destino = f"{host}:{port}"
    if _first_available("vncviewer", "tigervnc-viewer", "remote-viewer"):
        tool = shutil.which("vncviewer") or shutil.which("tigervnc-viewer") \
            or shutil.which("remote-viewer")
        cmd = [tool or "vncviewer", destino]
        cmd += _split(extra)
        return cmd
    if _first_available("remmina"):
        cmd = ["remmina", "--protocol=vnc", f"--server={host}", f"--port={port}"]
        cmd += _split(extra)
        return cmd
    return ["vncviewer", destino]


def xdmcp_command(session: Session) -> list[str]:
    """Orden para abrir una sesión XDMCP."""
    host = _host(session)
    if _first_available("xdmcp"):
        return ["xdmcp", host]
    if _first_available("X", "Xorg"):
        tool = shutil.which("X") or shutil.which("Xorg") or "X"
        return [tool, "-query", host]
    if _first_available("remmina"):
        return ["remmina", "--protocol=xdmcp", f"--server={host}"]
    return ["xdmcp", host]


def ftp_command(session: Session) -> list[str]:
    """Orden para abrir una sesión FTP (``lftp`` o ``ftp``)."""
    host = _host(session)
    port = _port(session, 21)
    if _first_available("lftp"):
        cmd = ["lftp"]
        user = _user(session)
        if user:
            if session.password:
                cmd += ["-u", f"{user},{session.password}"]
            else:
                cmd += ["-u", user]
        cmd.append(f"ftp://{host}:{port}")
        return cmd
    if _first_available("ftp"):
        cmd = ["ftp"]
        user = _user(session)
        if user:
            cmd += ["-u", f"{user} {session.password}".strip()]
        cmd += [host, str(port)]
        return cmd
    return ["lftp", f"ftp://{host}:{port}"]


def sftp_command(session: Session) -> list[str]:
    """Orden para abrir una sesión SFTP (cliente ``sftp`` o ``gvfs-open``)."""
    host = _host(session)
    port = _port(session, 22)
    user = _user(session)
    destino = f"{user}@{host}" if user else host
    if _first_available("sftp"):
        return ["sftp", "-P", str(port), destino]
    if _first_available("gvfs-open"):
        url = f"sftp://{destino}:{port}" if port != 22 else f"sftp://{destino}"
        return ["gvfs-open", url]
    return ["sftp", "-P", str(port), destino]


def telnet_command(session: Session) -> list[str]:
    """Orden para abrir una sesión Telnet."""
    host = _host(session)
    port = _port(session, 23)
    return ["telnet", host, str(port)]


def rsh_command(session: Session) -> list[str]:
    """Orden para abrir una sesión Rsh (``rsh`` o ``rlogin``)."""
    host = _host(session)
    user = _user(session)
    if _first_available("rsh"):
        cmd = ["rsh"]
        if user:
            cmd += ["-l", user]
        cmd.append(host)
        return cmd
    if _first_available("rlogin"):
        cmd = ["rlogin"]
        if user:
            cmd += ["-l", user]
        cmd.append(host)
        return cmd
    return ["rsh", host]


def mosh_command(session: Session) -> list[str]:
    """Orden para abrir una sesión Mosh."""
    host = _host(session)
    port = _port(session, 22)
    user = _user(session)
    destino = f"{user}@{host}" if user else host
    return ["mosh", f"--ssh=ssh -p {port}", destino]


def browser_command(session: Session) -> list[str]:
    """Orden para abrir el navegador en la sesión."""
    host = _host(session)
    port = _port(session, 80)
    return ["xdg-open", f"http://{host}:{port}"]


def launch(cmd: list[str], cwd: str = "") -> tuple[bool, str]:
    """Ejecuta una orden desacoplada.

    Devuelve ``(True, "")`` si el proceso se ha lanzado y ``(False, mensaje)``
    si el ejecutable no está instalado o no se pudo arrancar.
    """
    if not cmd:
        return (False, "No hay ningún comando que ejecutar")
    exe = cmd[0]
    if shutil.which(exe) is None:
        return (False, f"«{exe}» no está instalado")
    try:
        subprocess.Popen(
            cmd,
            cwd=cwd or None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return (False, f"No se pudo ejecutar «{exe}»: {exc}")
    return (True, "")


def available_tools() -> dict[str, bool]:
    """Indica qué clientes de escritorio remoto hay instalados."""
    return {
        "xfreerdp": bool(shutil.which("xfreerdp")),
        "remmina": bool(shutil.which("remmina")),
        "vncviewer": bool(shutil.which("vncviewer")),
        "lftp": bool(shutil.which("lftp")),
        "sftp": bool(shutil.which("sftp")),
        "telnet": bool(shutil.which("telnet")),
        "rsh": bool(shutil.which("rsh")),
        "mosh": bool(shutil.which("mosh")),
        "xdg-open": bool(shutil.which("xdg-open")),
    }
