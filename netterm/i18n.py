"""Capa de internacionalización de NetTerm.

El idioma por defecto es el español. Las traducciones viven en
``netterm/locale/`` como diccionarios ``STRINGS`` y se cargan automáticamente.

Uso típico::

    from .i18n import tr

    button = Gtk.Button(label=tr("New SSH session"))

Si una cadena no está traducida se devuelve tal cual, de modo que nunca
aparece un texto vacío. El idioma se elige con la variable de entorno
``NETTERM_LANG`` (por defecto ``es``).
"""

from __future__ import annotations

import importlib
import os
import pkgutil
from typing import Any

DEFAULT_LANG = "es"


def _load_catalog(lang: str) -> dict[str, str]:
    """Carga y fusiona los catálogos del idioma indicado."""
    catalog: dict[str, str] = {}
    try:
        from . import locale as locale_pkg
    except ImportError:  # pragma: no cover
        return catalog

    for module_info in pkgutil.iter_modules(locale_pkg.__path__):
        if module_info.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(
                f"{locale_pkg.__name__}.{module_info.name}")
        except ImportError:  # pragma: no cover
            continue
        strings: dict[str, Any] = getattr(module, "STRINGS", {}) or {}
        for key, value in strings.items():
            if isinstance(value, str):
                catalog[key] = value
    return catalog


def current_lang() -> str:
    return os.environ.get("NETTERM_LANG", DEFAULT_LANG)


_CATALOG: dict[str, str] = {}


def refresh(lang: str | None = None) -> None:
    """Recarga el catálogo (útil tras cambiar ``NETTERM_LANG``)."""
    global _CATALOG
    _CATALOG = _load_catalog(lang or current_lang())


def tr(text: str, **kwargs: Any) -> str:
    """Traduce ``text``; si no hay traducción, devuelve el original."""
    if not _CATALOG:
        refresh()
    out = _CATALOG.get(text, text)
    if kwargs:
        try:
            out = out.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return out


refresh()
