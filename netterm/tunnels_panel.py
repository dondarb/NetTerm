"""Panel del gestor de túneles SSH (equivalente a "SSH tunnels")."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GObject, Gtk  # noqa: E402

from .i18n import tr  # noqa: E402

from .config import CONFIG  # noqa: E402
from .gobj import clear_list, spin_int  # noqa: E402
from .session import Session, SessionType, Tunnel  # noqa: E402
from . import tunnels  # noqa: E402


class TunnelsPanel(Gtk.Box):
    """Crea y supervisa túneles de port forwarding SSH."""

    def __init__(self, parent=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.parent = parent
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(6)
        self.set_margin_end(6)
        self.manager = tunnels.TunnelManager()

        title = Gtk.Label(label=tr("Túneles SSH"))
        title.add_css_class("heading")
        title.set_xalign(0)
        self.append(title)

        grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        grid.attach(Gtk.Label(label=tr("Sesión"), xalign=0), 0, 0, 1, 1)
        self._sessions: list[Session] = []
        self.session_store = Gtk.StringList()
        self.session_combo = Gtk.DropDown(model=self.session_store)
        grid.attach(self.session_combo, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label=tr("Tipo"), xalign=0), 0, 1, 1, 1)
        self.kind = Gtk.DropDown.new_from_strings([tr("local (-L)"),
                                                   tr("remote (-R)"),
                                                   tr("dinámico (-D)")])
        grid.attach(self.kind, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label=tr("Bind"), xalign=0), 0, 2, 1, 1)
        self.bind = Gtk.Entry(text="127.0.0.1")
        grid.attach(self.bind, 1, 2, 1, 1)

        grid.attach(Gtk.Label(label=tr("Puerto local"), xalign=0), 0, 3, 1, 1)
        self.local_port = Gtk.SpinButton.new_with_range(0, 65535, 1)
        self.local_port.set_value(8080)
        grid.attach(self.local_port, 1, 3, 1, 1)

        grid.attach(Gtk.Label(label=tr("Destino"), xalign=0), 0, 4, 1, 1)
        self.target_host = Gtk.Entry(placeholder_text=tr("host remoto"))
        grid.attach(self.target_host, 1, 4, 1, 1)

        grid.attach(Gtk.Label(label=tr("Puerto remoto"), xalign=0), 0, 5, 1, 1)
        self.target_port = Gtk.SpinButton.new_with_range(0, 65535, 1)
        self.target_port.set_value(80)
        grid.attach(self.target_port, 1, 5, 1, 1)

        self.append(grid)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add = Gtk.Button(label=tr("Abrir túnel"))
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda *_: self._add())
        close = Gtk.Button(label=tr("Cerrar todos"))
        close.add_css_class("destructive-action")
        close.connect("clicked", lambda *_: self._close_all())
        buttons.append(add)
        buttons.append(close)
        self.append(buttons)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(self.listbox)
        self.append(scroller)

        self.log = Gtk.TextView(editable=False, monospace=True)
        self.log.set_size_request(-1, 120)
        scroller2 = Gtk.ScrolledWindow()
        scroller2.set_child(self.log)
        self.append(scroller2)

        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        clear_list(self.session_store)
        self._sessions = [s for s in CONFIG.sessions if s.type == SessionType.SSH]
        for s in self._sessions:
            self.session_store.append(f"{s.name} — {s.host}")
        self._reload_list()

    def _selected_session(self) -> Session | None:
        idx = self.session_combo.get_selected()
        if idx < 0 or idx >= len(self._sessions):
            return None
        return self._sessions[idx]

    def _add(self) -> None:
        session = self._selected_session()
        if not session:
            self.log.get_buffer().set_text(tr("Selecciona una sesión SSH."))
            return
        kinds = ["local", "remote", "dynamic"]
        kind = kinds[self.kind.get_selected()]
        tunnel = Tunnel(kind=kind,
                        bind_address=self.bind.get_text().strip() or "127.0.0.1",
                        bind_port=spin_int(self.local_port),
                        target_host=self.target_host.get_text().strip(),
                        target_port=spin_int(self.target_port))
        handle = self.manager.add(session, tunnel)
        self._reload_list()
        self.log.get_buffer().set_text(
            ("\n".join(handle.log[-8:]) if handle.log
             else f"{tr('Túnel creado')}: {tunnel.describe()}"))

    def _close_all(self) -> None:
        self.manager.remove_all()
        self._reload_list()

    def _reload_list(self) -> None:
        child = self.listbox.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.listbox.remove(child)
            child = nxt
        for handle in self.manager.list():
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            icon = Gtk.Image.new_from_icon_name(
                "network-server-symbolic" if handle.running else "dialog-warning-symbolic")
            row.append(icon)
            label = Gtk.Label(label=f"{handle.session_name}: {handle.tunnel.describe()}")
            label.set_xalign(0)
            label.set_hexpand(True)
            row.append(label)
            btn = Gtk.Button(icon_name="user-trash-symbolic")
            btn.add_css_class("flat")
            btn.connect("clicked", lambda _b, h=handle: self._remove(h))
            row.append(btn)
            self.listbox.append(row)

    def _remove(self, handle) -> None:
        self.manager.remove(handle)
        self._reload_list()
