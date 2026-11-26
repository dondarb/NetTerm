"""Arnés común de las pruebas.

Aísla la configuración para que las pruebas **nunca** toquen los datos reales
del usuario (``~/.config/netterm``). Debe importarse antes que cualquier
módulo de ``netterm``, porque ``netterm.config`` crea la configuración al
importarse.
"""

from __future__ import annotations

import os
import sys
import tempfile

# El directorio de configuración debe fijarse ANTES de importar netterm.
_PRUEBAS = tempfile.mkdtemp(prefix="netterm-pruebas-")
os.environ["XDG_CONFIG_HOME"] = _PRUEBAS
os.environ["NETTERM_LANG"] = "es"

# El paquete debe estar en el path (por si se ejecuta desde otro sitio).
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

CONFIG_DIR = _PRUEBAS


def limpiar() -> None:
    """Borra las sesiones creadas por la prueba."""
    try:
        from netterm.config import CONFIG

        CONFIG.sessions.clear()
        CONFIG.save_sessions()
    except Exception:
        pass
