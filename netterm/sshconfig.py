"""Parser de ``~/.ssh/config``.

Permite importar hosts ya configurados en el sistema (como hace MobaXterm al
detectar la configuración SSH del usuario) y reutilizar las directivas
``ProxyJump`` como *SSH gateway*.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any

# Directivas que heredan sus valores desde el bloque ``Host *``.
# El nombre de OpenSSH no distingue mayúsculas: se comparan en minúsculas.
_INHERITED = ("hostname", "user", "port", "identityfile", "proxyjump",
              "proxycommand", "forwardagent", "compression", "keepalive")

# Nombre canónico ( tal y como aparece en el fichero ) de cada directiva.
_CANONICAL = {
    "hostname": "HostName",
    "user": "User",
    "port": "Port",
    "identityfile": "IdentityFile",
    "proxyjump": "ProxyJump",
    "proxycommand": "ProxyCommand",
    "forwardagent": "ForwardAgent",
    "compression": "Compression",
    "keepalive": "KeepAlive",
}


def default_ssh_config_path() -> Path:
    override = os.environ.get("NETTERM_SSH_CONFIG")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".ssh" / "config"


def _tokens(line: str) -> list[str]:
    """Divide respetando comillas (para ``IdentityFile "con espacio"``)."""
    try:
        return shlex.split(line, comments=True)
    except ValueError:
        return line.split()


def parse_ssh_config(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Devuelve ``{patrón: {directiva: valor}}`` tal como aparece en el fichero."""
    path = path or default_ssh_config_path()
    hosts: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return hosts

    current: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return hosts

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line and not line.lower().startswith(("host",)):
            key, _, value = line.partition("=")
            key, value = key.strip().lower(), value.strip()
            if key in _INHERITED:
                for h in current:
                    hosts.setdefault(h, {}).setdefault(_CANONICAL[key], value)
            continue
        parts = _tokens(line)
        if not parts:
            continue
        key = parts[0].lower()
        value = " ".join(parts[1:])
        if key == "host":
            current = parts[1:]
            for h in current:
                hosts.setdefault(h, {})
        elif key in _INHERITED and current:
            for h in current:
                hosts[h][_CANONICAL[key]] = value
    return hosts


def _match(pattern: str, host: str) -> bool:
    """Implementa el matching de patrones de OpenSSH (``*``, ``?``, negación)."""
    import fnmatch

    if pattern.startswith("!"):
        return not _match(pattern[1:], host)
    return fnmatch.fnmatch(host, pattern)


def resolve_host(host: str, path: Path | None = None) -> dict[str, Any]:
    """Devuelve la configuración efectiva para un host concreto."""
    hosts = parse_ssh_config(path)
    resolved: dict[str, Any] = {}
    # Primero los patrones literales, luego los comodines (orden del fichero).
    for pattern, opts in hosts.items():
        if " " in pattern:
            continue
        if _match(pattern, host):
            for k, v in opts.items():
                resolved[k] = v
    for pattern, opts in hosts.items():
        if " " not in pattern:
            continue
        if any(_match(p, host) for p in pattern.split()):
            for k, v in opts.items():
                resolved.setdefault(k, v)
    resolved.setdefault("HostName", host)
    return resolved


def list_hosts(path: Path | None = None) -> list[str]:
    """Hosts concretos declarados en la configuración (sin comodines)."""
    hosts = parse_ssh_config(path)
    return [h for h in hosts if " " not in h and not h.startswith("*")
            and not h.startswith("!")]


def import_sessions(path: Path | None = None):
    """Convierte las entradas de ``~/.ssh/config`` en objetos :class:`Session`."""
    from .session import Session, SessionType

    out: list[Session] = []
    for alias in list_hosts(path):
        opts = resolve_host(alias, path)
        hostname = opts.get("HostName", alias)
        try:
            port = int(opts.get("Port", "22"))
        except ValueError:
            port = 22
        key = opts.get("IdentityFile", "")
        if key:
            key = os.path.expanduser(key.split()[0])
        out.append(Session(
            id=f"sshcfg-{alias}",
            name=alias,
            type=SessionType.SSH,
            group="Configuración SSH",
            host=hostname,
            port=port,
            username=opts.get("User", "") or os.environ.get("USER", ""),
            key_file=key,
            jump_host=opts.get("ProxyJump", "").split()[0] if opts.get("ProxyJump") else "",
        ))
    return out
