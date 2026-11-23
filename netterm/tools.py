"""Panel de herramientas de NetTerm.

Equivalente a los "Embedded tools" de MobaXterm, pero nativo:

* **Interfaces**: tabla viva de *todas* las tarjetas de red del equipo, con
  detección en caliente (conectar/desconectar un dongle USB actualiza la lista).
* **Ping / Traza**: con selector de interfaz y opción de barrido de subred.
* **Escáner**: nmap y escaneo TCP/UDP de puertos.
* **Servidores**: servidores embebidos (HTTP, SFTP, SSH, FTP, Telnet).
* **Paquetes**: gestor tipo MobApt sobre ``dnf``.
* **Túneles**: gestor gráfico de port forwarding SSH.
* **CRC**: calculadora de checksum.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango  # noqa: E402

from .i18n import tr  # noqa: E402

from .config import CONFIG  # noqa: E402
from .gobj import ItemObj, clear_list, item_store  # noqa: E402
from . import netif, netops  # noqa: E402


# ---------------------------------------------------------------------------
# Consola de salida compartida
# ---------------------------------------------------------------------------
class OutputConsole(Gtk.Box):
    """Caja de texto con salida de un comando."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.view = Gtk.TextView(editable=False, monospace=True)
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.view.set_left_margin(6)
        self.view.set_right_margin(6)
        self.view.set_top_margin(4)
        self.view.set_bottom_margin(4)
        self.buffer = self.view.get_buffer()
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(self.view)
        self.append(scroller)

    def clear(self) -> None:
        self.buffer.set_text("")

    def write(self, text: str) -> None:
        end = self.buffer.get_end_iter()
        self.buffer.insert(end, text)
        self.view.scroll_to_iter(self.buffer.get_end_iter(), 0.0, False, 0.0, 0.0)


class RunnerBox(Gtk.Box):
    """Ejecuta un comando y muestra su salida en vivo."""

    def __init__(self, title: str = "") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.runner: netops.CommandRunner | None = None
        self._thread: threading.Thread | None = None

        if title:
            lbl = Gtk.Label(label=title)
            lbl.add_css_class("heading")
            self.append(lbl)

        self.console = OutputConsole()
        self.append(self.console)

    def run(self, runner: netops.CommandRunner) -> None:
        self.stop()
        self.runner = runner
        self.console.clear()
        self.console.write(f"$ {' '.join(runner.cmd)}\n\n")
        try:
            runner.start()
        except Exception as exc:
            self.console.write(f"{tr('Error')}: {exc}\n")
            return

        def _pump() -> None:
            try:
                for line in runner.lines():
                    if not line:
                        break
                    GLib.idle_add(self.console.append, line + "\n")
            except Exception as exc:
                GLib.idle_add(self.console.append, f"\n{tr('Error')}: {exc}\n")
            finally:
                GLib.idle_add(self._finish)

        self._thread = threading.Thread(target=_pump, daemon=True)
        self._thread.start()

    def _finish(self) -> None:
        rc = self.runner.returncode if self.runner else None
        if rc not in (0, None):
            self.console.write(f"\n[{tr('código de salida')} {rc}]\n")

    def stop(self) -> None:
        if self.runner:
            self.runner.stop()
            self.runner = None


# ---------------------------------------------------------------------------
# Panel de interfaces (requisito: cualquier tarjeta, detectada en caliente)
# ---------------------------------------------------------------------------
class InterfacesPanel(Gtk.Box):
    """Tabla viva de todas las interfaces de red."""

    def __init__(self, parent=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.parent = parent
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        self.set_margin_start(4)
        self.set_margin_end(4)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.search = Gtk.SearchEntry(placeholder_text=tr("Filtrar interfaces…"))
        self.search.connect("search-changed", lambda *_: self.refresh())
        header.append(self.search)
        refresh = Gtk.Button(icon_name="view-refresh-symbolic",
                             tooltip_text=tr("Actualizar ahora"))
        refresh.connect("clicked", lambda *_: self.refresh())
        header.append(refresh)
        self.append(header)

        self.store = item_store()
        self.view = Gtk.ColumnView(model=Gtk.NoSelection(model=self.store))
        self.view.set_show_column_separators(False)
        self.view.set_show_row_separators(True)

        def add_col(title: str, value: Callable[[Any], str]):
            factory = Gtk.SignalListItemFactory()
            factory.connect("setup", self._setup_cell, value)
            factory.connect("bind", self._bind_cell, value)
            col = Gtk.ColumnViewColumn()
            col.set_title(title)
            col.set_factory(factory)
            col.set_expand(True)
            self.view.append_column(col)

        add_col(tr("Interfaz"), lambda i: i.name)
        add_col(tr("Tipo"), lambda i: i.kind)
        add_col(tr("Estado"), lambda i: i.status_text())
        add_col(tr("IPv4"), lambda i: ", ".join(a.cidr() for a in i.ipv4) or tr("—"))
        add_col(tr("MAC"), lambda i: i.mac or tr("—"))
        add_col(tr("Driver"), lambda i: i.driver or tr("—"))
        add_col(tr("MTU"), lambda i: str(i.mtu))
        add_col(tr("Vel."), lambda i: f"{i.speed} Mb/s" if i.speed else tr("—"))

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(self.view)
        self.append(scroller)

        self._rows: list[Any] = []

    def _setup_cell(self, factory, list_item, value) -> None:
        cell = Gtk.Label(xalign=0)
        cell.set_ellipsize(3)
        list_item.set_child(cell)

    def _bind_cell(self, factory, list_item, value) -> None:
        row = list_item.get_item()
        cell = list_item.get_child()
        text = value(row) if row else ""
        cell.set_text(text)

    def refresh(self) -> None:
        text = (self.search.get_text() or "").lower().strip()
        self._rows = [i for i in netif.list_interfaces()
                      if not text or text in (i.name + i.kind + i.mac).lower()]
        self.store.remove_all()
        for i in self._rows:
            self.store.append(ItemObj(i))
        if self.parent:
            self.parent.emit("interfaces-changed")

    def selected(self):
        model = self.view.get_model()
        sel = model.get_selection()
        if sel is None:
            return None
        obj = sel.get_selected()
        return obj

# ---------------------------------------------------------------------------
# Ping / traza / barrido
# ---------------------------------------------------------------------------
class PingPanel(Gtk.Box):
    """Ping, traceroute y barrido de subred, con selector de interfaz."""

    def __init__(self, parent=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.parent = parent
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(6)
        self.set_margin_end(6)

        grid = Gtk.Grid(column_spacing=6, row_spacing=6)

        grid.attach(Gtk.Label(label=tr("Destino"), xalign=0), 0, 0, 1, 1)
        self.target = Gtk.Entry(placeholder_text=tr("host o dirección IP"))
        self.target.set_hexpand(True)
        grid.attach(self.target, 1, 0, 2, 1)

        grid.attach(Gtk.Label(label=tr("Interfaz"), xalign=0), 0, 1, 1, 1)
        self.iface_store = Gtk.StringList()
        self.iface = Gtk.DropDown(model=self.iface_store)
        self.iface.set_tooltip_text(tr("Interfaz de salida (–I)"))
        grid.attach(self.iface, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label=tr("Tamaño"), xalign=0), 2, 1, 1, 1)
        self.size = Gtk.SpinButton.new_with_range(8, 1472, 8)
        self.size.set_value(56)
        grid.attach(self.size, 3, 1, 1, 1)

        grid.attach(Gtk.Label(label=tr("Intentos"), xalign=0), 0, 2, 1, 1)
        self.count = Gtk.SpinButton.new_with_range(1, 100, 1)
        self.count.set_value(4)
        grid.attach(self.count, 1, 2, 1, 1)

        grid.attach(Gtk.Label(label=tr("Espera"), xalign=0), 2, 2, 1, 1)
        self.timeout = Gtk.SpinButton.new_with_range(1, 30, 1)
        self.timeout.set_value(2)
        grid.attach(self.timeout, 3, 2, 1, 1)

        self.append(grid)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.btn_ping = Gtk.Button(label=tr("Ping"))
        self.btn_ping.add_css_class("suggested-action")
        self.btn_ping.connect("clicked", lambda *_: self._ping())
        self.btn_trace = Gtk.Button(label=tr("Traceroute"))
        self.btn_trace.connect("clicked", lambda *_: self._trace())
        self.btn_sweep = Gtk.Button(label=tr("Barrido de subred"))
        self.btn_sweep.connect("clicked", lambda *_: self._sweep())
        self.btn_mtr = Gtk.Button(label=tr("MTR"))
        self.btn_mtr.connect("clicked", lambda *_: self._mtr())
        for b in (self.btn_ping, self.btn_trace, self.btn_sweep, self.btn_mtr):
            buttons.append(b)
        self.append(buttons)

        self.console = OutputConsole()
        self.append(self.console)

        self.refresh_interfaces()

    def refresh_interfaces(self) -> None:
        names = [i.name for i in netif.list_interfaces()]
        clear_list(self.iface_store)
        for n in names:
            self.iface_store.append(n)
        default = netif.default_interface()
        if default in names:
            self.iface.set_selected(names.index(default))

    def selected_iface(self) -> str:
        idx = self.iface.get_selected()
        if idx < 0:
            return ""
        return self.iface_store.get_string(idx)

    def _ping(self) -> None:
        target = self.target.get_text().strip()
        if not target:
            return
        runner = netops.ping(target, self.selected_iface(),
                             count=self.count.get_value_as_int(),
                             size=self.size.get_value_as_int(),
                             timeout=self.timeout.get_value_as_int())
        self.console.clear()
        self.console.write(f"$ {' '.join(runner.cmd)}\n\n")
        self._run(runner)

    def _trace(self) -> None:
        target = self.target.get_text().strip()
        if not target:
            return
        runner = netops.traceroute(target, self.selected_iface())
        self.console.clear()
        self.console.write(f"$ {' '.join(runner.cmd)}\n\n")
        self._run(runner)

    def _mtr(self) -> None:
        target = self.target.get_text().strip()
        if not target:
            return
        runner = netops.mtr(target, self.selected_iface())
        self.console.clear()
        self.console.write(f"$ {' '.join(runner.cmd)}\n\n")
        self._run(runner)

    def _sweep(self) -> None:
        target = self.target.get_text().strip()
        if not target:
            return
        runner = netops.ping_sweep(target, self.selected_iface(),
                                   timeout=self.timeout.get_value_as_int())
        self.console.clear()
        self.console.write(f"$ {tr('barrido de')} {target}\n\n")
        self._run(runner)

    def _run(self, runner: netops.CommandRunner) -> None:
        try:
            runner.start()
        except Exception as exc:
            self.console.write(f"{tr('Error')}: {exc}\n")
            return

        def _pump() -> None:
            try:
                for line in runner.lines():
                    if not line:
                        break
                    GLib.idle_add(self.console.append, line + "\n")
            except Exception as exc:
                GLib.idle_add(self.console.append, f"\n{tr('Error')}: {exc}\n")

        threading.Thread(target=_pump, daemon=True).start()


# ---------------------------------------------------------------------------
# Escáner
# ---------------------------------------------------------------------------
class ScanPanel(Gtk.Box):
    """Escaneo de puertos con nmap o mediante sockets puros."""

    def __init__(self, parent=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.parent = parent
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(6)
        self.set_margin_end(6)

        grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        grid.attach(Gtk.Label(label=tr("Objetivo"), xalign=0), 0, 0, 1, 1)
        self.target = Gtk.Entry(placeholder_text=tr("IP, rango o red CIDR"))
        self.target.set_hexpand(True)
        grid.attach(self.target, 1, 0, 2, 1)

        grid.attach(Gtk.Label(label=tr("Interfaz"), xalign=0), 0, 1, 1, 1)
        self.iface_store = Gtk.StringList()
        self.iface = Gtk.DropDown(model=self.iface_store)
        grid.attach(self.iface, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label=tr("Puertos"), xalign=0), 2, 1, 1, 1)
        self.ports = Gtk.Entry(placeholder_text=tr("1-1024 o 22,80,443"))
        grid.attach(self.ports, 3, 1, 1, 1)

        grid.attach(Gtk.Label(label=tr("Opciones extra"), xalign=0), 0, 2, 1, 1)
        self.extra = Gtk.Entry(placeholder_text=tr("-sV, -A, -T4 …"))
        grid.attach(self.extra, 1, 2, 3, 1)

        self.append(grid)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        b1 = Gtk.Button(label=tr("Escaneo nmap"))
        b1.add_css_class("suggested-action")
        b1.connect("clicked", lambda *_: self._nmap())
        b2 = Gtk.Button(label=tr("Puertos TCP"))
        b2.connect("clicked", lambda *_: self._tcp())
        b3 = Gtk.Button(label=tr("Tabla ARP"))
        b3.connect("clicked", lambda *_: self._arp())
        for b in (b1, b2, b3):
            buttons.append(b)
        self.append(buttons)

        self.console = OutputConsole()
        self.append(self.console)

    def _iface(self) -> str:
        idx = self.iface.get_selected()
        return self.iface_store.get_string(idx) if idx >= 0 else ""

    def _nmap(self) -> None:
        target = self.target.get_text().strip()
        if not target:
            return
        runner = netops.nmap_scan(target, self._iface(),
                                  ports=self.ports.get_text().strip(),
                                  extra_args=self.extra.get_text().strip())
        self.console.clear()
        self.console.write(f"$ {' '.join(runner.cmd)}\n\n")
        self._run(runner)

    def _tcp(self) -> None:
        target = self.target.get_text().strip()
        if not target:
            return
        runner = netops.tcp_scan(target, self.ports.get_text().strip() or "1-1024")
        self.console.clear()
        self.console.write(f"{tr('Escaneo TCP de')} {target}\n\n")
        self._run(runner)

    def _arp(self) -> None:
        rows = netif.neighbour_table()
        lines = [tr("Vecinos (ARP/NDP):"), ""]
        for r in rows:
            lines.append(f"  {r.get('address',''):<18} {r.get('ifname',''):<12} "
                         f"{r.get('state','')}")
        self.console.clear()
        self.console.write("\n".join(lines) + "\n")

    def _run(self, runner: netops.CommandRunner) -> None:
        try:
            runner.start()
        except Exception as exc:
            self.console.write(f"{tr('Error')}: {exc}\n")
            return

        def _pump() -> None:
            try:
                for line in runner.lines():
                    if not line:
                        break
                    GLib.idle_add(self.console.append, line + "\n")
            except Exception as exc:
                GLib.idle_add(self.console.append, f"\n{tr('Error')}: {exc}\n")

        threading.Thread(target=_pump, daemon=True).start()


# ---------------------------------------------------------------------------
# CRC
# ---------------------------------------------------------------------------
class CrcPanel(Gtk.Box):
    """Calculadora de CRC y checksum, como las herramientas de MobaXterm."""

    def __init__(self, parent=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.parent = parent
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(6)
        self.set_margin_end(6)

        self.entry = Gtk.Entry(placeholder_text=tr("Texto o datos hexadecimales"))
        self.append(self.entry)
        self.hex_mode = Gtk.CheckButton(label=tr("Interpretar como hexadecimal"))
        self.append(self.hex_mode)

        grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        self.result = Gtk.Label(label=tr("—"))
        self.result.set_xalign(0)
        self.result.set_selectable(True)
        grid.attach(Gtk.Label(label=tr("CRC32"), xalign=0), 0, 0, 1, 1)
        grid.attach(self.result, 1, 0, 1, 1)
        self.append(grid)

        self.entry.connect("changed", lambda *_: self._compute())
        self.hex_mode.connect("toggled", lambda *_: self._compute())

    def _compute(self) -> None:
        import binascii
        import zlib

        text = self.entry.get_text()
        if not text:
            self.result.set_text(tr("—"))
            return
        if self.hex_mode.get_active():
            try:
                data = binascii.unhexlify(text.replace(" ", ""))
            except (binascii.Error, ValueError):
                self.result.set_text(tr("hexadecimal inválido"))
                return
        else:
            data = text.encode("utf-8")
        crc = zlib.crc32(data) & 0xFFFFFFFF
        self.result.set_text(f"0x{crc:08X}  ({crc})")


# ---------------------------------------------------------------------------
# Panel principal de herramientas
# ---------------------------------------------------------------------------
class ToolsPanel(Gtk.Box):
    """Contenedor con las subpestañas de herramientas."""

    __gsignals__ = {
        "interfaces-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "status-message": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    TABS = [
        ("net", tr("Red"), "network-transmit-receive-symbolic"),
        ("interfaces", tr("Interfaces"), "network-wired-symbolic"),
        ("scan", tr("Escáner"), "network-server-symbolic"),
        ("servers", tr("Servidores"), "emblem-system-symbolic"),
        ("packages", tr("Paquetes"), "system-software-install-symbolic"),
        ("tunnels", tr("Túneles"), "network-server-symbolic"),
        ("crc", tr("CRC"), "accessories-calculator-symbolic"),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.parent = parent
        self._panels: dict[str, Gtk.Widget] = {}

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)

        switcher = Gtk.StackSwitcher(stack=self.stack)
        switcher.set_halign(Gtk.Align.CENTER)
        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        hdr.append(switcher)
        self.append(hdr)
        self.append(self.stack)

        self.interfaces_panel = InterfacesPanel(self)
        self.ping_panel = PingPanel(self)
        self.scan_panel = ScanPanel(self)
        self.servers_panel = ServersPanel(self)
        self.packages_panel = PackagesPanel(self)
        self.tunnels_panel = TunnelsPanel(self)
        self.crc_panel = CrcPanel(self)

        self._panels = {
            "net": self.ping_panel,
            "interfaces": self.interfaces_panel,
            "scan": self.scan_panel,
            "servers": self.servers_panel,
            "packages": self.packages_panel,
            "tunnels": self.tunnels_panel,
            "crc": self.crc_panel,
        }
        for key, _label, _icon in self.TABS:
            self.stack.add_named(self._panels[key], key)
        self.stack.set_visible_child_name("net")

        self._monitor = None

    def show_tab(self, name: str) -> None:
        if name in self._panels:
            self.stack.set_visible_child_name(name)
            self.refresh()

    def refresh(self) -> None:
        self.interfaces_panel.refresh()
        self.ping_panel.refresh_interfaces()

    def start_watching(self) -> None:
        """Vigila /sys/class/net para detectar tarjetas nuevas al instante."""
        if self._monitor is not None:
            return
        self._monitor = netif.interface_watch(self._on_interfaces_changed)

    def _on_interfaces_changed(self) -> bool:
        self.interfaces_panel.refresh()
        self.ping_panel.refresh_interfaces()
        self.emit("interfaces-changed")
        return False


# ---------------------------------------------------------------------------
# Importaciones tardías de los paneles que dependen de subagentes
# ---------------------------------------------------------------------------
def _late(panel_cls):
    return panel_cls


from .servers_panel import ServersPanel  # noqa: E402
from .packages_panel import PackagesPanel  # noqa: E402
from .tunnels_panel import TunnelsPanel  # noqa: E402
