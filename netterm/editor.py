"""Editor de texto remoto.

Equivalente al "MobaTextEditor" de MobaXterm: al abrir un fichero del
navegador SFTP se muestra un editor con resaltado de sintaxis que lee y
escribe directamente en el servidor por SFTP.
"""

from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .i18n import tr  # noqa: E402

from . import syntax  # noqa: E402


class RemoteEditor(Adw.ApplicationWindow):
    """Ventana de edición de un fichero remoto."""

    def __init__(self, parent=None, connection=None, path: str = "",
                 title: str = ""):
        super().__init__(application=None, transient_for=parent)
        self.connection = connection
        self.path = path
        self.language = "text"
        self.set_title(title or path)
        self.set_default_size(940, 640)

        self.buffer = Gtk.TextBuffer()
        self.view = Gtk.TextView(buffer=self.buffer)
        self.view.set_monospace(True)
        self.view.set_show_line_numbers(True)
        self.view.set_insert_line_breaks(False)
        self.view.set_tab_insert_spaces(True)
        self.view.set_auto_indent(True)
        self.view.set_left_margin(8)
        self.view.set_right_margin(8)
        self.view.set_top_margin(6)
        self.view.set_bottom_margin(6)
        self.view.set_wrap_mode(Gtk.WrapMode.NONE)

        scroller = Gtk.ScrolledWindow()
        scroller.set_child(self.view)

        self.status = Gtk.Label(label="")
        self.status.add_css_class("dim-label")
        self.status.add_css_class("caption")
        self.status.set_xalign(0)
        self.status.set_margin_start(10)
        self.status.set_margin_end(10)
        self.status.set_margin_top(2)
        self.status.set_margin_bottom(2)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(scroller)
        box.append(self.status)

        header = Adw.HeaderBar()
        header.pack_start(self._menu_button())
        save = Gtk.Button(icon_name="document-save-symbolic",
                          tooltip_text=tr("Guardar (Ctrl+S)"))
        save.set_action_name("editor.save")
        header.pack_end(save)
        reload = Gtk.Button(icon_name="view-refresh-symbolic",
                             tooltip_text=tr("Recargar del servidor"))
        reload.set_action_name("editor.reload")
        header.pack_end(reload)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(box)
        self.set_content(toolbar)

        self._install_actions()
        if path:
            self.load(path)

    # ------------------------------------------------------------------
    def _menu_button(self) -> Gtk.MenuButton:
        menu = Gio.Menu()
        menu.append(tr("Guardar"), "editor.save")
        menu.append(tr("Recargar"), "editor.reload")
        menu.append(tr("Separador"), None)
        menu.append(tr("Copiar"), "editor.copy")
        menu.append(tr("Pegar"), "editor.paste")
        menu.append(tr("Separador"), None)
        menu.append(tr("Seleccionar todo"), "editor.select-all")

        button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        button.set_menu_model(menu)
        return button

    def _install_actions(self) -> None:
        for name, cb in (("save", lambda *_: self.save()),
                         ("reload", lambda *_: self.load(self.path)),
                         ("copy", lambda *_: self.view.copy_clipboard(
                             Gtk.Clipboard.CLIPBOARD)),
                         ("paste", lambda *_: self.view.paste_clipboard(
                             Gtk.Clipboard.CLIPBOARD)),
                         ("select-all", lambda *_: self.view.select_region(
                             0, -1))):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", cb)
            self.add_action(action)
        self.set_accels_for_action("editor.save", ["<Control>s"])

    # ------------------------------------------------------------------
    def load(self, path: str) -> None:
        if not self.connection:
            return
        self.status.set_text(f"{tr('Cargando')} {path}…")

        def _worker() -> None:
            ok, content = self.connection.read(path)
            GLib.idle_add(self._loaded, ok, content, path)

        threading.Thread(target=_worker, daemon=True).start()

    def _loaded(self, ok: bool, content: str, path: str) -> None:
        if ok:
            self.buffer.set_text(content)
            self.language = syntax.language_for_path(path)
            syntax.highlight(self.buffer, self.language)
            self._update_status()
        else:
            self.status.set_text(f"{tr('Error')}: {content}")

    def save(self, path: str = "") -> None:
        target = path or self.path
        if not target or not self.connection:
            return
        content = self.buffer.get_text(self.buffer.get_start_iter(),
                                       self.buffer.get_end_iter(), False)

        def _worker() -> None:
            ok, msg = self.connection.write(target, content)
            GLib.idle_add(self._saved, ok, msg)

        threading.Thread(target=_worker, daemon=True).start()

    def _saved(self, ok: bool, msg: str) -> None:
        self.status.set_text(msg if ok else f"{tr('Error')}: {msg}")

    def _update_status(self) -> None:
        cursor = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        line = cursor.get_line() + 1
        col = cursor.get_line_offset() + 1
        nlines = self.buffer.get_line_count()
        self.status.set_text(f"{self.path} · {self.language} · {nlines} "
                             f"{tr('líneas')} · L{line} C{col}")
