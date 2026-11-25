"""Utilidades GObject compartidas.

``Gio.ListStore`` exige un ``GType`` real, así que cualquier dato (un
dataclass, un diccionario) se envuelve en :class:`ItemObj`, que además
delega los atributos al valor envuelto.
"""

from __future__ import annotations

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GObject  # noqa: E402


class ItemObj(GObject.Object):
    """Envoltorio genérico para insertar datos arbitrarios en un ListStore."""

    __gtype_name__ = "NetTermItem"

    def __init__(self, value=None):
        super().__init__()
        self.value = value

    def __getattr__(self, name: str):
        value = self.__dict__.get("value")
        if isinstance(value, dict):
            try:
                return value[name]
            except KeyError:
                raise AttributeError(name) from None
        try:
            return getattr(value, name)
        except AttributeError:
            raise AttributeError(name) from None

    def __repr__(self) -> str:  # pragma: no cover
        return f"ItemObj({self.value!r})"


def item_store(item_type=ItemObj) -> Gio.ListStore:
    """Crea un ``Gio.ListStore`` listo para :class:`ItemObj`."""
    return Gio.ListStore(item_type=item_type)


def clear_list(store) -> None:
    """Vacía un ``Gtk.StringList`` (no tiene ``remove_all``)."""
    while store.get_n_items() > 0:
        store.remove(0)


def spin_int(widget) -> int:
    """Valor entero de un ``Gtk.SpinButton`` o de un ``Adw.SpinRow``.

    No son la misma API: ``Gtk.SpinButton`` tiene ``get_value_as_int()``,
    mientras que ``Adw.SpinRow`` sólo expone ``get_value()`` (un double).
    """
    getter = getattr(widget, "get_value_as_int", None)
    if getter is not None:
        return int(getter())
    return int(round(widget.get_value()))
