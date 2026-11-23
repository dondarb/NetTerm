"""Importador de sesiones de MobaXterm.

MobaXterm guarda sus sesiones en un fichero INI:

    %APPDATA%\\MobaXterm\\MobaXterm.ini   (Windows)
    ~/.mobaxttermrc  o  Documents/MobaXterm.ini (Portable)

Las claves relevantes son ``SessionX``, ``SessionXName``, ``SessionXHost``,
``SessionXPort``, ``SessionXUsername``, ``SessionXPassword``, ``SessionXType``,
``SessionXKeyFile`` y ``SessionXSerialPort``.
"""

from __future__ import annotations

import configparser
import os
import re
from pathlib import Path

from .session import Session, SessionType

# Tipos de MobaXterm -> SessionType de NetTerm
TYPE_MAP = {
    "SSH": SessionType.SSH,
    "SFTP": SessionType.SFTP,
    "FTP": SessionType.FTP,
    "TELNET": SessionType.TELNET,
    "RSH": SessionType.RSH,
    "RLOGIN": SessionType.RSH,
    "RDP": SessionType.RDP,
    "VNC": SessionType.VNC,
    "XDMCP": SessionType.XDMCPC,
    "SERIAL": SessionType.SERIAL,
    "MOSH": SessionType.MOSH,
    "SHELL": SessionType.SHELL,
    "BROWSER": SessionType.BROWSER,
    "FILE": SessionType.FILE,
}


def candidate_paths() -> list[Path]:
    """Rutas habituales donde puede estar el fichero de sesiones."""
    home = Path.home()
    paths = [
        home / ".mobaxttermrc",
        home / "Documents" / "MobaXterm.ini",
        home / ".config" / "MobaXterm" / "MobaXterm.ini",
    ]
    try:
        import winreg  # noqa: F401
    except ImportError:
        pass
    else:  # pragma: no cover - sólo en Windows
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\MobaXterm")
            value, _ = winreg.QueryValueEx(key, "Home")
            paths.insert(0, Path(value) / "MobaXterm.ini")
        except OSError:
            pass
    return paths


def find_ini() -> Path | None:
    for path in candidate_paths():
        if path.exists():
            return path
    return None


def _get(section: str, key: str, default: str = "") -> str:
    try:
        return section.get(key, default)
    except (configparser.NoOptionError, configparser.NoSectionError):
        return default


def import_mobaxterm_sessions(path: Path | None = None) -> list[Session]:
    """Lee las sesiones de un MobaXterm.ini y devuelve objetos Session."""
    path = path or find_ini()
    if path is None or not path.exists():
        return []

    parser = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        parser.read(path, encoding="utf-8", errors="replace")
    except configparser.Error:
        # Algunos ficheros de MobaXterm tienen secciones duplicadas; reintentamos
        parser = configparser.RawConfigParser(strict=False)
        try:
            parser.read(path, encoding="utf-8", errors="replace")
        except configparser.Error:
            return []

    sections = [s for s in parser.sections() if s.lower() == "sessions"]
    if not sections:
        sections = parser.sections()
    if not sections:
        return []

    section = parser[sections[0]]
    indices: set[int] = set()
    for key in section.keys():
        m = re.match(r"^Session(\d+)$", key, re.IGNORECASE)
        if m:
            indices.add(int(m.group(1)))
    if not indices:
        indices = {int(m.group(1)) for m in
                   (re.match(r"^Session(\d+)$", k, re.IGNORECASE) for k in section.keys())
                   if m}

    sessions: list[Session] = []
    for idx in sorted(indices):
        prefix = f"Session{idx}"
        name = _get(section, f"{prefix}Name", "") or _get(section, f"{prefix}Host", "")
        if not name:
            continue
        raw_type = _get(section, f"{prefix}Type", "SSH").upper()
        stype = TYPE_MAP.get(raw_type, SessionType.SSH)
        host = _get(section, f"{prefix}Host", "")
        try:
            port = int(_get(section, f"{prefix}Port", "22") or 22)
        except ValueError:
            port = 22
        session = Session(
            id=f"mbx-{idx}-{name.lower().replace(' ', '-')}",
            name=name,
            type=stype,
            group="MobaXterm",
            host=host,
            port=port,
            username=_get(section, f"{prefix}Username", ""),
            key_file=_get(section, f"{prefix}KeyFile", ""),
            serial_port=_get(section, f"{prefix}SerialPort", ""),
            notes="Importada desde MobaXterm",
        )
        try:
            baud = int(_get(section, f"{prefix}SerialBaudRate", "115200") or 115200)
            session.baudrate = baud
        except ValueError:
            pass
        sessions.append(session)
    return sessions
