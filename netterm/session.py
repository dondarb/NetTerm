"""Definición de sesiones de NetTerm.

Replica los tipos de sesión de MobaXterm: SSH, Telnet, Rsh, Xdmcp, RDP, VNC,
FTP, SFTP, Serial, File, Shell, Browser y Mosh.
"""

from __future__ import annotations

import dataclasses
import enum
from typing import Any


class SessionType(str, enum.Enum):
    """Tipos de sesión soportados (idénticos a los iconos de MobaXterm)."""

    SSH = "ssh"
    TELNET = "telnet"
    RSH = "rsh"
    XDMCPC = "xdmcp"
    RDP = "rdp"
    VNC = "vnc"
    FTP = "ftp"
    SFTP = "sftp"
    SERIAL = "serial"
    FILE = "file"
    SHELL = "shell"
    BROWSER = "browser"
    MOSH = "mosh"

    @property
    def label(self) -> str:
        return {
            SessionType.SSH: "SSH",
            SessionType.TELNET: "Telnet",
            SessionType.RSH: "Rsh",
            SessionType.XDMCPC: "Xdmcp",
            SessionType.RDP: "RDP",
            SessionType.VNC: "VNC",
            SessionType.FTP: "FTP",
            SessionType.SFTP: "SFTP",
            SessionType.SERIAL: "Serial",
            SessionType.FILE: "File",
            SessionType.SHELL: "Shell",
            SessionType.BROWSER: "Browser",
            SessionType.MOSH: "Mosh",
        }[self]

    @property
    def icon(self) -> str:
        """Nombre del icono en el tema Adwaita (o emoji de reserva)."""
        return {
            SessionType.SSH: "network-server-symbolic",
            SessionType.TELNET: "network-wired-symbolic",
            SessionType.RSH: "network-transmit-receive-symbolic",
            SessionType.XDMCPC: "video-display-symbolic",
            SessionType.RDP: "preferences-desktop-remote-desktop-symbolic",
            SessionType.VNC: "video-display-symbolic",
            SessionType.FTP: "folder-download-symbolic",
            SessionType.SFTP: "folder-publish-symbolic",
            SessionType.SERIAL: "computer-symbolic",
            SessionType.FILE: "folder-symbolic",
            SessionType.SHELL: "utilities-terminal-symbolic",
            SessionType.BROWSER: "web-browser-symbolic",
            SessionType.MOSH: "network-wireless-symbolic",
        }[self]

    @property
    def is_graphical(self) -> bool:
        """Sesiones que se abren en una aplicación externa (no en VTE)."""
        return self in (SessionType.RDP, SessionType.VNC, SessionType.XDMCPC,
                        SessionType.BROWSER, SessionType.FILE)

    @property
    def needs_host(self) -> bool:
        return self in (SessionType.SSH, SessionType.TELNET, SessionType.RSH,
                        SessionType.XDMCPC, SessionType.RDP, SessionType.VNC,
                        SessionType.FTP, SessionType.SFTP, SessionType.MOSH)


@dataclasses.dataclass
class Tunnel:
    """Un túnel SSH (port forwarding)."""

    kind: str = "local"  # local (-L), remote (-R), dynamic (-S/-D)
    bind_address: str = "127.0.0.1"
    bind_port: int = 0
    target_host: str = ""
    target_port: int = 0

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Tunnel":
        return cls(**{k: d.get(k, getattr(cls, k, None)) for k in
                      ("kind", "bind_address", "bind_port", "target_host", "target_port")})

    def spec(self) -> str:
        """Devuelve el argumento de ssh correspondiente."""
        if self.kind == "dynamic":
            return f"-D {self.bind_address}:{self.bind_port}"
        flag = "-L" if self.kind == "local" else "-R"
        return f"{flag} {self.bind_address}:{self.bind_port}:{self.target_host}:{self.target_port}"

    def describe(self) -> str:
        if self.kind == "dynamic":
            return f"SOCKS {self.bind_address}:{self.bind_port}"
        arrow = "->" if self.kind == "local" else "<-"
        return f"{self.bind_address}:{self.bind_port} {arrow} {self.target_host}:{self.target_port}"


@dataclasses.dataclass
class Session:
    """Una sesión guardada."""

    id: str
    name: str
    type: SessionType = SessionType.SSH
    group: str = "Mis sesiones"
    host: str = ""
    port: int = 22
    username: str = ""
    password: str = ""          # referencia al almacén de la bóveda, no el secreto
    key_file: str = ""
    key_passphrase: str = ""
    jump_host: str = ""         # SSH gateway (ProxyJump)
    jump_user: str = ""
    jump_port: int = 22
    serial_port: str = ""
    baudrate: int = 115200
    databits: int = 8
    stopbits: float = 1.0
    parity: str = "N"
    x11_forward: bool = True
    xauth: bool = False
    compress: bool = False
    keepalive: int = 0
    tunnels: list[Tunnel] = dataclasses.field(default_factory=list)
    # Opciones de la sesión
    remote_command: str = ""
    local_dir: str = ""
    remote_dir: str = ""
    color: str = ""
    favorite: bool = False
    notes: str = ""
    created_at: str = ""
    last_used: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"{self.type.value}-{abs(hash((self.name, self.host)))}"

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["type"] = self.type.value
        d["tunnels"] = [t.to_dict() for t in self.tunnels]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Session":
        d = dict(d)
        raw_type = d.pop("type", "ssh")
        try:
            stype = SessionType(raw_type)
        except ValueError:
            stype = SessionType.SSH
        known = {f.name for f in dataclasses.fields(cls)}
        data = {k: v for k, v in d.items() if k in known}
        data["type"] = stype
        data["tunnels"] = [Tunnel.from_dict(t) for t in d.get("tunnels", [])]
        return cls(**data)

    def display_target(self) -> str:
        if self.type == SessionType.SERIAL:
            return f"{self.serial_port} @ {self.baudrate}"
        if self.username:
            return f"{self.username}@{self.host}:{self.port}"
        return f"{self.host}:{self.port}" if self.host else self.name
