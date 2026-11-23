"""Panel de gestión de paquetes (equivalente a "MobApt package manager")."""

from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from .i18n import tr  # noqa: E402

from . import packages  # noqa: E402
from .gobj import ItemObj, item_store  # noqa: E402


class PackagesPanel(Gtk.Box):
    """Busca, instala y elimina paquetes del sistema con dnf."""

    def __init__(self, parent=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.parent = parent
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(6)
        self.set_margin_end(6)

        tabs = Gtk.Stack()
        switcher = Gtk.StackSwitcher(stack=tabs)
        switcher.set_halign(Gtk.Align.CENTER)
        self.append(switcher)

        # -- búsqueda ---------------------------------------------------
        search_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.search_entry = Gtk.SearchEntry(placeholder_text=tr("Buscar paquetes…"))
        self.search_entry.connect("search-changed", lambda *_: self._reload())
        search_box.append(self.search_entry)

        self.store = item_store()
        self.view = Gtk.ColumnView(model=Gtk.NoSelection(model=self.store))
        self.view.set_show_column_separators(False)

        def add_col(title: str, value):
            factory = Gtk.SignalListItemFactory()
            factory.connect("setup", self._setup, value)
            factory.connect("bind", self._bind, value)
            col = Gtk.ColumnViewColumn()
            col.set_title(title)
            col.set_factory(factory)
            col.set_expand(True)
            self.view.append_column(col)

        add_col(tr("Paquete"), lambda d: d.get("name", ""))
        add_col(tr("Versión"), lambda d: d.get("version", ""))
        add_col(tr("Repositorio"), lambda d: d.get("repo", ""))

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(self.view)
        search_box.append(scroller)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        install = Gtk.Button(label=tr("Instalar"))
        install.add_css_class("suggested-action")
        install.connect("clicked", lambda *_: self._install())
        remove = Gtk.Button(label=tr("Eliminar"))
        remove.add_css_class("destructive-action")
        remove.connect("clicked", lambda *_: self._remove())
        info = Gtk.Button(label=tr("Información"))
        info.connect("clicked", lambda *_: self._info())
        for b in (install, remove, info):
            buttons.append(b)
        search_box.append(buttons)

        tabs.add_named(search_box, tr("buscar"))

        # -- instalados --------------------------------------------------
        installed_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.inst_store = item_store()
        self.inst_view = Gtk.ColumnView(model=Gtk.NoSelection(model=self.inst_store))

        factory2 = Gtk.SignalListItemFactory()
        factory2.connect("setup", self._setup, lambda d: d.get("name", ""))
        factory2.connect("bind", self._bind, lambda d: d.get("name", ""))
        col2 = Gtk.ColumnViewColumn()
        col2.set_title(tr("Instalado"))
        col2.set_factory(factory2)
        col2.set_expand(True)
        self.inst_view.append_column(col2)
        self.inst_view.set_show_column_separators(False)

        scroller2 = Gtk.ScrolledWindow()
        scroller2.set_vexpand(True)
        scroller2.set_child(self.inst_view)
        installed_box.append(scroller2)

        refresh = Gtk.Button(label=tr("Recargar lista"))
        refresh.connect("clicked", lambda *_: self._reload_installed())
        installed_box.append(refresh)
        tabs.add_named(installed_box, tr("instalados"))

        # -- consola ------------------------------------------------------
        self.console = Gtk.TextView(editable=False, monospace=True)
        self.console.set_size_request(-1, 180)
        scroller3 = Gtk.ScrolledWindow()
        scroller3.set_vexpand(True)
        scroller3.set_child(self.console)
        tabs.add_named(scroller3, tr("consola"))

        self.append(tabs)

    # ------------------------------------------------------------------
    def _setup(self, factory, list_item, value) -> None:
        cell = Gtk.Label(xalign=0)
        cell.set_ellipsize(3)
        list_item.set_child(cell)

    def _bind(self, factory, list_item, value) -> None:
        row = list_item.get_item()
        cell = list_item.get_child()
        cell.set_text(value(row) if row else "")

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self._reload()

    def _reload(self) -> None:
        query = self.search_entry.get_text().strip()
        self.store.remove_all()
        threading.Thread(target=self._load_available, args=(query,),
                         daemon=True).start()

    def _load_available(self, query: str) -> None:
        try:
            if query:
                rows = packages.search(query)
            else:
                rows = packages.list_available()
        except Exception:
            rows = []
        for r in rows:
            GLib.idle_add(self.store.append, ItemObj(r))

    def _reload_installed(self) -> None:
        self.inst_store.remove_all()
        threading.Thread(target=self._load_installed, daemon=True).start()

    def _load_installed(self) -> None:
        try:
            rows = packages.list_installed()
        except Exception:
            rows = []
        for r in rows:
            GLib.idle_add(self.inst_store.append, ItemObj(r))

    # ------------------------------------------------------------------
    def _selected(self) -> str:
        sel = self.view.get_selection()
        if sel is None:
            return ""
        obj = sel.get_selected()
        return obj.get("name", "") if obj else ""

    def _install(self) -> None:
        name = self._selected()
        if not name:
            return
        self._run(packages.install(name))

    def _remove(self) -> None:
        name = self._selected()
        if not name:
            return
        self._run(packages.remove(name))

    def _info(self) -> None:
        name = self._selected()
        if not name:
            return
        self._run(packages.info(name))

    def _run(self, runner) -> None:
        buffer = self.console.get_buffer()
        buffer.set_text(f"$ {' '.join(runner.cmd)}\n\n")
        try:
            runner.start()
        except Exception as exc:
            buffer.insert(buffer.get_end_iter(), f"{tr('Error')}: {exc}\n")
            return

        def _pump() -> None:
            try:
                for line in runner.lines():
                    if not line:
                        break
                    GLib.idle_add(buffer.insert, buffer.get_end_iter(), line + "\n")
            except Exception as exc:
                GLib.idle_add(buffer.insert, buffer.get_end_iter(), f"{tr('Error')}: {exc}\n")

        threading.Thread(target=_pump, daemon=True).start()
