"""Grabación y reproducción de macros.

Equivalente a la función "Macros support" de MobaXterm: se graba todo lo que
se escribe en un terminal y luego se reproduce en otros servidores.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, GObject, Gtk  # noqa: E402

from .config import config_dir, CONFIG  # noqa: E402
from .i18n import tr  # noqa: E402
from .terminal import keyval_to_bytes  # noqa: E402

MACRO_FILE = config_dir() / "macros.json"


def _load() -> list[dict[str, Any]]:
    try:
        data = json.loads(MACRO_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(items: list[dict[str, Any]]) -> None:
    MACRO_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False),
                          encoding="utf-8")


def list_macros() -> list[dict[str, Any]]:
    return _load()


def save_macro(name: str, keys: list[str], description: str = "") -> dict[str, Any]:
    items = _load()
    macro = {
        "id": f"macro-{int(time.time())}",
        "name": name,
        "description": description,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "keys": keys,
    }
    items.append(macro)
    _save(items)
    return macro


def delete_macro(macro_id: str) -> None:
    _save([m for m in _load() if m.get("id") != macro_id])


class MacroRecorder:
    """Graba la entrada del teclado de una terminal."""

    def __init__(self) -> None:
        self._page = None
        self._keys: list[str] = []
        self._controller = None

    @property
    def is_recording(self) -> bool:
        return self._page is not None

    def start(self, page) -> None:
        self.stop()
        self._page = page
        self._keys = []
        ctrl = Gtk.EventControllerKey()
        ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        ctrl.connect("key-pressed", self._on_key)
        page.terminal.add_controller(ctrl)
        self._controller = ctrl

    def stop(self) -> list[str]:
        keys = list(self._keys)
        if self._controller and self._page:
            try:
                self._page.terminal.remove_controller(self._controller)
            except Exception:
                pass
        self._controller = None
        self._page = None
        self._keys = []
        return keys

    def _on_key(self, _controller, keyval: int, keycode: int, state) -> bool:
        char = chr(Gdk.keyval_to_unicode(keyval)) if Gdk.keyval_to_unicode(keyval) else ""
        data = keyval_to_bytes(keyval, char)
        if data:
            try:
                self._keys.append(data.decode("utf-8", errors="replace"))
            except Exception:
                self._keys.append(repr(data))
        return False  # no interferimos con la terminal

    def save(self, name: str, description: str = "") -> dict[str, Any] | None:
        keys = self.stop()
        if not keys:
            return None
        return save_macro(name, keys, description)


_recorder = MacroRecorder()


def recorder() -> MacroRecorder:
    return _recorder


def play(page, macro: dict[str, Any], delay: float = 0.02) -> None:
    """Reproduce un macro en una terminal."""
    keys = macro.get("keys", [])
    if not keys:
        return

    def _step(i: int) -> bool:
        if i >= len(keys):
            return False
        try:
            page.send_text(keys[i])
        except Exception:
            return False
        return GLib.timeout_add(int(delay * 1000), _step, i + 1)

    GLib.idle_add(_step, 0)


class MacrosPanel(Gtk.Box):
    """Panel lateral con la lista de macros."""

    __gsignals__ = {
        "status-message": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, sidebar=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.sidebar = sidebar
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(6)
        self.set_margin_end(6)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label=tr("Macros"))
        title.add_css_class("heading")
        header.append(title)

        rec_btn = Gtk.Button(icon_name="media-record-symbolic",
                             tooltip_text=tr("Grabar macro en la terminal actual"))
        rec_btn.connect("clicked", lambda *_: self._record())
        header.append(rec_btn)
        self.append(header)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-activated", self._on_activate)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(self.listbox)
        self.append(scroller)

        self.refresh()

    def refresh(self) -> None:
        child = self.listbox.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.listbox.remove(child)
            child = nxt
        macros = list_macros()
        if not macros:
            label = Gtk.Label(label=tr("Sin macros.\nUsa el botón de grabación."))
            label.add_css_class("dim-label")
            label.set_wrap(True)
            self.listbox.append(label)
            return
        for m in macros:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            icon = Gtk.Image.new_from_icon_name("document-edit-symbolic")
            row.append(icon)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            name = Gtk.Label(label=m.get("name", tr("macro")))
            name.set_xalign(0)
            info = Gtk.Label(label=f"{m.get('created_at', '')} · "
                                  f"{tr('{n} teclas', n=len(m.get('keys', [])))}")
            info.add_css_class("caption")
            info.add_css_class("dim-label")
            info.set_xalign(0)
            box.append(name)
            box.append(info)
            row.append(box)
            del_btn = Gtk.Button(icon_name="user-trash-symbolic")
            del_btn.add_css_class("flat")
            del_btn.connect("clicked", lambda _b, mid=m.get("id"): self._delete(mid))
            row.append(del_btn)
            self.listbox.append(row)

    def _record(self) -> None:
        if self.sidebar and self.sidebar.window:
            self.sidebar.window._macro_record()

    def _on_activate(self, _listbox, row) -> None:
        idx = self.listbox.get_row_index(row)
        macros = list_macros()
        if 0 <= idx < len(macros) and self.sidebar and self.sidebar.window:
            page = self.sidebar.window.current_page()
            if page:
                play(page, macros[idx])

    def _delete(self, macro_id: str) -> None:
        delete_macro(macro_id)
        self.refresh()
        self.emit("status-message", tr("Macro eliminado"))
