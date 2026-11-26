"""Inicialización temprana del entorno de NetTerm.

Este módulo se importa **antes** que ``gi`` (porque es el ``__init__`` del
paquete), de modo que las variables de entorno quedan listas antes de que la
tipografía GI las lea.

NetTerm necesita ``Vte-3.91.typelib`` (VTE para GTK4). Fedora 45 no trae el
paquete ``vte291-gtk4`` instalado por defecto, así que se admite una copia
local en ``vendor/`` que se añade al camino de búsqueda.
"""

from __future__ import annotations

import os
from pathlib import Path

__version__ = "1.2.0"
__all__ = ["__version__", "bootstrap_vendor"]


def _vendor_candidates() -> list[Path]:
    here = Path(__file__).resolve().parent
    candidates: list[Path] = []
    env_root = os.environ.get("NETTERM_VENDOR")
    if env_root:
        candidates.append(Path(env_root))
    candidates.append(here.parent / "vendor")            # ~/netterm/vendor
    candidates.append(here / "vendor")
    candidates.append(Path.home() / ".local/share/netterm/vendor")
    return candidates


def _system_has_vte() -> bool:
    """¿Está VTE (GTK4) disponible en las rutas GI del sistema?"""
    candidates = []
    env = os.environ.get("GI_TYPELIB_PATH", "")
    if env:
        candidates.extend(env.split(os.pathsep))
    candidates.extend([
        "/usr/lib64/girepository-1.0",
        "/usr/lib/girepository-1.0",
        "/usr/lib64/x86_64-linux-gnu/girepository-1.0",
    ])
    for directory in candidates:
        if not directory:
            continue
        if os.path.exists(os.path.join(directory, "Vte-3.91.typelib")):
            return True
    return False


def bootstrap_vendor() -> bool:
    """Añade las tipografías GI locales al camino de búsqueda.

    Devuelve ``True`` si encontró una copia local.

    Si el sistema ya tiene VTE para GTK4 (paquete ``vte291-gtk4``), no se
    toca nada: se prefiere siempre la versión del sistema.

    Nota: ``LD_LIBRARY_PATH`` sólo se lee al arrancar el proceso, así que
    no basta con asignarlo en caliente. Las bibliotecas compartidas se cargan
    explícitamente con ``ctypes`` (RTLD_GLOBAL) para que ``g_irepository``
    las encuentre al leer la tipografía.
    """
    import ctypes

    if _system_has_vte():
        return False

    for root in _vendor_candidates():
        typelibs = root / "usr/lib64/girepository-1.0"
        libs = root / "usr/lib64"
        if not typelibs.is_dir():
            continue
        os.environ["GI_TYPELIB_PATH"] = os.pathsep.join(
            [str(typelibs), os.environ.get("GI_TYPELIB_PATH", "")]).rstrip(os.pathsep)
        if libs.is_dir():
            os.environ["LD_LIBRARY_PATH"] = os.pathsep.join(
                [str(libs), os.environ.get("LD_LIBRARY_PATH", "")]).rstrip(os.pathsep)
            # Orden de dependencia: primero las_leaf, después las de nivel superior.
            # OJO: «libvte-2.91.so.0» es la variante GTK3 y no debe precargarse
            # (mezclar GTK3 y GTK4 en el mismo proceso aborta la aplicación).
            for name in ("libsimdutf.so.24", "libvte-2.91-gtk4.so.0"):
                candidate = libs / name
                if not candidate.exists():
                    continue
                try:
                    ctypes.CDLL(str(candidate), mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass
        return True
    return False


bootstrap_vendor()
