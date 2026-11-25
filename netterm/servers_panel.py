"""Panel de servidores embebidos (equivalente a "Embedded servers")."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .i18n import tr  # noqa: E402
from .gobj import spin_int  # noqa: E402

from . import servers  # noqa: E402


class ServersPanel(Gtk.Box):
    """Permite levantar servidores locales para que otros te alcancen."""

    def __init__(self, parent=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.parent = parent
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(6)
        self.set_margin_end(6)
        self._servers: list[servers.EmbeddedServer] = []

        title = Gtk.Label(label=tr("Servidores embebidos"))
        title.add_css_class("heading")
        title.set_xalign(0)
        self.append(title)

        desc = Gtk.Label(
            label=tr("Levanta un daemon local para que otras máquinas "
                     "puedan entrar en tu equipo."))
        desc.add_css_class("dim-label")
        desc.add_css_class("caption")
        desc.set_wrap(True)
        desc.set_xalign(0)
        self.append(desc)

        grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        grid.attach(Gtk.Label(label=tr("Tipo"), xalign=0), 0, 0, 1, 1)
        self.kind = Gtk.DropDown.new_from_strings(list(servers.EmbeddedServer.KINDS))
        grid.attach(self.kind, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label=tr("Interfaz"), xalign=0), 0, 1, 1, 1)
        self.bind = Gtk.Entry(text="0.0.0.0")
        grid.attach(self.bind, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label=tr("Puerto"), xalign=0), 0, 2, 1, 1)
        self.port = Gtk.SpinButton.new_with_range(0, 65535, 1)
        self.port.set_value(8022)
        self.port.set_tooltip_text(tr("0 = puerto asignado automáticamente"))
        grid.attach(self.port, 1, 2, 1, 1)

        grid.attach(Gtk.Label(label=tr("Directorio"), xalign=0), 0, 3, 1, 1)
        self.root = Gtk.Entry(placeholder_text=tr("directorio a servir"))
        grid.attach(self.root, 1, 3, 1, 1)

        grid.attach(Gtk.Label(label=tr("Usuario"), xalign=0), 0, 4, 1, 1)
        self.username = Gtk.Entry()
        grid.attach(self.username, 1, 4, 1, 1)

        grid.attach(Gtk.Label(label=tr("Contraseña"), xalign=0), 0, 5, 1, 1)
        self.password = Gtk.PasswordEntry()
        grid.attach(self.password, 1, 5, 1, 1)

        self.append(grid)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        start = Gtk.Button(label=tr("Arrancar"))
        start.add_css_class("suggested-action")
        start.connect("clicked", lambda *_: self._start())
        stop = Gtk.Button(label=tr("Parar todo"))
        stop.add_css_class("destructive-action")
        stop.connect("clicked", lambda *_: self._stop_all())
        buttons.append(start)
        buttons.append(stop)
        self.append(buttons)

        self.status = Gtk.Label(label="")
        self.status.add_css_class("dim-label")
        self.status.set_xalign(0)
        self.status.set_wrap(True)
        self.append(self.status)

        self.log_view = Gtk.TextView(editable=False, monospace=True)
        self.log_view.set_size_request(-1, 160)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(self.log_view)
        self.append(scroller)

    # ------------------------------------------------------------------
    def _selected_kind(self) -> str:
        idx = self.kind.get_selected()
        return list(servers.EmbeddedServer.KINDS)[idx] if idx >= 0 else "http"

    def _start(self) -> None:
        kind = self._selected_kind()
        srv = servers.EmbeddedServer(
            kind=kind,
            bind=self.bind.get_text().strip() or "0.0.0.0",
            port=spin_int(self.port),
            root_dir=self.root.get_text().strip(),
            username=self.username.get_text().strip(),
            password=self.password.get_text(),
        )
        ok, msg = srv.start()
        self.status.set_text(msg)
        if ok:
            self._servers.append(srv)
        self._refresh_log()

    def _stop_all(self) -> None:
        for srv in self._servers:
            srv.stop()
        self._servers.clear()
        self.status.set_text(tr("Todos los servidores detenidos"))
        self._refresh_log()

    def _refresh_log(self) -> None:
        lines: list[str] = []
        for srv in self._servers:
            lines.append(f"--- {servers.EmbeddedServer.KINDS.get(srv.kind, srv.kind)} "
                         f"{tr('activo') if srv.running else tr('parado')} "
                         f"{tr('puerto')} {srv.port} {srv.url()}")
            lines.extend(srv.log[-12:])
        self.log_view.get_buffer().set_text("\n".join(lines))
