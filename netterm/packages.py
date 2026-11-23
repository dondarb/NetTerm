"""Gestor de paquetes de Fedora (``dnf``).

Equivalente al "MobApt package manager" de MobaXterm, pero sobre el gestor de
paquetes nativo de Fedora.  Los listados (disponibles, instalados, búsqueda y
grupos) no necesitan privilegios y se parsean en memoria; las operaciones que
modifican el sistema (instalar, eliminar, actualizar) se lanzan a través de
``pkexec`` para que aparezca la ventana de autenticación delGestor de
políticas.
"""

from __future__ import annotations

import shutil

from .netops import CommandRunner, missing_command

DNF = "dnf"
PKEXEC = "pkexec"

# Cabeceras que ``dnf`` imprime y que hay que descartar al parsear.
_HEADERS = (
    "last metadata",
    "installed packages",
    "available packages",
    "available groups",
    "installed groups",
    "paquetes instalados",
    "paquetes disponibles",
    "grupos disponibles",
    "grupos instalados",
    "última metadata",
    "ultima metadata",
    "campos coincidentes",
    "coincidencias",
    "id ",
    "groups:",
    "grupos:",
)


def _is_header(line: str) -> bool:
    """¿La línea es una cabecera de ``dnf`` y no un paquete?"""
    stripped = line.strip()
    if not stripped:
        return True
    if "====" in stripped or "^" in stripped:
        return True
    lowered = stripped.lower()
    return any(lowered.startswith(marker) for marker in _HEADERS)


def _parse_list(text: str) -> list[dict[str, str]]:
    """Parsea la salida de ``dnf list``: ``nombre[.arquitectura] version repo``."""
    rows: list[dict[str, str]] = []
    for raw in text.splitlines():
        if _is_header(raw):
            continue
        parts = raw.split()
        if len(parts) < 3:
            continue
        rows.append({
            "name": parts[0],
            "version": parts[1],
            "repo": " ".join(parts[2:]),
        })
    return rows


def _parse_search(text: str) -> list[dict[str, str]]:
    """Parsea la salida de ``dnf search``: ``nombre<TAB>resumen``."""
    rows: list[dict[str, str]] = []
    for raw in text.splitlines():
        if _is_header(raw):
            continue
        if "\t" in raw:
            name, _, summary = raw.partition("\t")
            rows.append({
                "name": name.strip(),
                "version": "",
                "repo": "",
                "summary": summary.strip(),
            })
            continue
        parts = raw.split()
        if len(parts) >= 3:
            rows.append({
                "name": parts[0],
                "version": parts[1],
                "repo": " ".join(parts[2:]),
                "summary": "",
            })
        elif len(parts) == 2:
            rows.append({
                "name": parts[0],
                "version": "",
                "repo": "",
                "summary": parts[1],
            })
    return rows


def _parse_groups(text: str) -> list[dict[str, str]]:
    """Parsea la salida de ``dnf group list``: ``id nombre instalada``.

    El nombre del grupo puede contener espacios, así que la columna
    ``installed`` se localiza al final de la línea (es ``yes`` o ``no``).
    """
    rows: list[dict[str, str]] = []
    for raw in text.splitlines():
        if _is_header(raw):
            continue
        parts = raw.split()
        if len(parts) < 2:
            continue
        installed = ""
        if parts[-1].lower() in ("yes", "no", "si", "sí"):
            installed = parts[-1].lower()
            parts = parts[:-1]
        if not parts:
            continue
        rows.append({
            "id": parts[0],
            "name": " ".join(parts[1:]),
            "installed": installed,
        })
    return rows


def _dnf_text(args: list[str], timeout: float = 180.0) -> str:
    """Ejecuta ``dnf`` en modo silencioso y devuelve su salida de texto.

    Si ``dnf`` no está instalado se devuelve una cadena vacía, de modo que los
    listados devuelven listas vacías en lugar de fallar.
    """
    if not shutil.which(DNF):
        return ""
    runner = CommandRunner([DNF, "-q", *args], label=DNF)
    runner.timeout = timeout
    return runner.read_all()


# ---------------------------------------------------------------------------
# Listados
# ---------------------------------------------------------------------------


def list_available(query: str = "") -> list[dict[str, str]]:
    """Paquetes disponibles en los repositorios (``dnf list --available``)."""
    args = ["list", "--available"]
    if query:
        args.append(query)
    return _parse_list(_dnf_text(args))


def list_installed(query: str = "") -> list[dict[str, str]]:
    """Paquetes ya instalados en el sistema (``dnf list --installed``)."""
    args = ["list", "--installed"]
    if query:
        args.append(query)
    return _parse_list(_dnf_text(args))


def search(query: str) -> list[dict[str, str]]:
    """Busca paquetes por nombre o descripción (``dnf search``)."""
    if not query:
        return []
    return _parse_search(_dnf_text(["search", query]))


def groups() -> list[dict[str, str]]:
    """Grupos de paquetes disponibles (``dnf group list``)."""
    return _parse_groups(_dnf_text(["group", "list"]))


# ---------------------------------------------------------------------------
# Operaciones (algunas requieren privilegios)
# ---------------------------------------------------------------------------


def info(name: str) -> CommandRunner:
    """Información detallada de un paquete (``dnf info``)."""
    if not shutil.which(DNF):
        return missing_command(DNF)
    return CommandRunner([DNF, "info", name], label="dnf info")


def install(name: str) -> CommandRunner:
    """Instala un paquete con ``pkexec dnf install``."""
    if not shutil.which(DNF):
        return missing_command(DNF)
    if not shutil.which(PKEXEC):
        return missing_command(PKEXEC)
    return CommandRunner([PKEXEC, DNF, "install", "-y", name],
                         label="dnf install", needs_root=True)


def remove(name: str) -> CommandRunner:
    """Elimina un paquete con ``pkexec dnf remove``."""
    if not shutil.which(DNF):
        return missing_command(DNF)
    if not shutil.which(PKEXEC):
        return missing_command(PKEXEC)
    return CommandRunner([PKEXEC, DNF, "remove", "-y", name],
                         label="dnf remove", needs_root=True)


def update() -> CommandRunner:
    """Actualiza el sistema con ``pkexec dnf update``."""
    if not shutil.which(DNF):
        return missing_command(DNF)
    if not shutil.which(PKEXEC):
        return missing_command(PKEXEC)
    return CommandRunner([PKEXEC, DNF, "update", "-y"],
                         label="dnf update", needs_root=True)
