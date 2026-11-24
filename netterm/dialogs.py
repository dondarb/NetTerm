"""Diálogo de creación/edición de sesiones.

Cubre todos los tipos de sesión de MobaXterm: SSH, Telnet, Rsh, Xdmcp, RDP,
VNC, FTP, SFTP, Serial, File, Shell, Browser y Mosh.
"""

from __future__ import annotations

import os
import uuid

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, GObject, Gtk  # noqa: E402

from .config import CONFIG  # noqa: E402
from .i18n import tr  # noqa: E402
from .secrets import VAULT  # noqa: E402
from .session import Session, SessionType, Tunnel  # noqa: E402

# Iconos en el mismo orden que la barra de sesión de MobaXterm
SESSION_ICONS = [
    (SessionType.SSH, "SSH", "network-server-symbolic"),
    (SessionType.TELNET, "Telnet", "network-wired-symbolic"),
    (SessionType.RSH, "Rsh", "network-transmit-receive-symbolic"),
    (SessionType.XDMCPC, "Xdmcp", "video-display-symbolic"),
    (SessionType.RDP, "RDP", "preferences-desktop-remote-desktop-symbolic"),
    (SessionType.VNC, "VNC", "video-display-symbolic"),
    (SessionType.FTP, "FTP", "folder-download-symbolic"),
    (SessionType.SFTP, "SFTP", "folder-publish-symbolic"),
    (SessionType.SERIAL, "Serial", "computer-symbolic"),
    (SessionType.FILE, "File", "folder-symbolic"),
    (SessionType.SHELL, "Shell", "utilities-terminal-symbolic"),
    (SessionType.BROWSER, "Browser", "web-browser-symbolic"),
    (SessionType.MOSH, "Mosh", "network-wireless-symbolic"),
]


def serial_ports() -> list[tuple[str, str]]:
    """Detecta los puertos serie disponibles (incluye los recién conectados)."""
    found: list[tuple[str, str]] = []
    for base in ("/dev/serial/by-id", "/dev"):
        if not os.path.isdir(base):
            continue
        try:
            entries = sorted(os.listdir(base))
        except OSError:
            continue
        for entry in entries:
            if base == "/dev":
                if not (entry.startswith("ttyUSB") or entry.startswith("ttyACM")
                        or entry.startswith("ttyS")):
                    continue
                label = entry
            else:
                if not entry.startswith("."):
                    continue
                label = entry
            path = os.path.join(base, entry)
            if path in [p for p, _ in found]:
                continue
            try:
                real = os.path.realpath(path)
            except OSError:
                real = path
            found.append((path, f"{label} → {os.path.basename(real)}"))
    return found


class SessionDialog(Adw.Window):
    """Formulario de sesión."""

    __gsignals__ = {
        "session-created": (GObject.SignalFlags.RUN_FIRST, None, (object, str)),
    }

    def __init__(self, parent, kind: str = "ssh", session: Session | None = None):
        super().__init__(transient_for=parent, modal=True)
        self.set_title(tr("Nueva sesión") if session is None
                      else tr("Editar sesión"))
        self.set_default_size(560, 640)
        self.existing = session
        self.kind = SessionType(kind) if kind else SessionType.SSH

        self.page = Adw.PreferencesPage()
        self._build_type_group()
        self._build_general_group()
        self._build_connection_group()
        self._build_auth_group()
        self._build_serial_group()
        self._build_advanced_group()

        header = Adw.HeaderBar()
        cancel = Gtk.Button(label=tr("Cancelar"))
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)
        save = Gtk.Button(label=tr("Guardar") if session else tr("Conectar"))
        save.add_css_class("suggested-action")
        save.connect("clicked", lambda *_: self._submit())
        header.pack_end(save)
        self.set_content(Adw.ToolbarView())
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self.page)
        self.set_content(toolbar)

        self._sync_visibility()

    # ------------------------------------------------------------------
    def _build_type_group(self) -> None:
        group = Adw.PreferencesGroup(title=tr("Tipo de sesión"))
        self.type_row = Adw.ComboRow(title=tr("Protocolo"))
        model = Gtk.StringList()
        for stype, label, _icon in SESSION_ICONS:
            model.append(label)
        self.type_row.set_model(model)
        self.type_row.set_selected([s[0] for s in SESSION_ICONS].index(self.kind))
        self.type_row.connect("notify::selected", lambda *_: self._sync_visibility())
        group.add(self.type_row)
        self.page.add(group)

    def _build_general_group(self) -> None:
        group = Adw.PreferencesGroup(title=tr("General"))
        self.name_row = Adw.EntryRow(title=tr("Nombre"))
        self.name_row.set_text(self.existing.name if self.existing else "")
        group.add(self.name_row)

        self.group_row = Adw.EntryRow(title=tr("Grupo"))
        self.group_row.set_text(self.existing.group if self.existing
                                else tr("Mis sesiones"))
        group.add(self.group_row)

        self.user_row = Adw.EntryRow(title=tr("Usuario"))
        self.user_row.set_text(self.existing.username if self.existing
                               else os.environ.get("USER", ""))
        group.add(self.user_row)
        self.page.add(group)

    def _build_connection_group(self) -> None:
        group = Adw.PreferencesGroup(title=tr("Conexión"))
        self.host_row = Adw.EntryRow(title=tr("Host"))
        self.host_row.set_text(self.existing.host if self.existing else "")
        group.add(self.host_row)

        self.port_row = Adw.SpinRow.new_with_range(1, 65535, 1)
        self.port_row.set_title(tr("Puerto"))
        self.port_row.set_value(self.existing.port if self.existing else 22)
        group.add(self.port_row)

        self.jump_row = Adw.EntryRow(title=tr("SSH gateway (jump host)"))
        self.jump_row.set_text(self.existing.jump_host if self.existing else "")
        self.jump_row.set_tooltip_text(tr("ProxyJump: primero conecta a este host"))
        group.add(self.jump_row)

        self.url_row = Adw.EntryRow(title=tr("URL / archivo"))
        group.add(self.url_row)
        self.page.add(group)

    def _build_auth_group(self) -> None:
        group = Adw.PreferencesGroup(title=tr("Autenticación"))
        self.password_row = Adw.PasswordEntryRow(title=tr("Contraseña"))
        group.add(self.password_row)

        self.key_row = Adw.EntryRow(title=tr("Clave privada"))
        self.key_row.set_text(self.existing.key_file if self.existing else "")
        self.key_row.set_tooltip_text(tr("Ruta a la clave (id_rsa, id_ed25519…)"))
        group.add(self.key_row)

        self.x11_row = Adw.SwitchRow(title=tr("X11 forwarding"))
        self.x11_row.set_active(self.existing.x11_forward if self.existing else True)
        group.add(self.x11_row)
        self.page.add(group)

    def _build_serial_group(self) -> None:
        group = Adw.PreferencesGroup(title=tr("Consola serie"))
        self.port_combo = Adw.ComboRow(title=tr("Puerto"))
        ports = serial_ports()
        model = Gtk.StringList()
        for _path, label in ports:
            model.append(label)
        self.port_combo.set_model(model)
        group.add(self.port_combo)

        self.baud_row = Adw.SpinRow.new_with_range(1200, 115200, 1)
        self.baud_row.set_title(tr("Velocidad"))
        self.baud_row.set_value(self.existing.baudrate if self.existing else 115200)
        group.add(self.baud_row)

        self.bits_row = Adw.ComboRow(title=tr("Bits de datos"))
        self.bits_row.set_model(Gtk.StringList.new(["5", "6", "7", "8"]))
        self.bits_row.set_selected(3)
        group.add(self.bits_row)

        self.stop_row = Adw.ComboRow(title=tr("Bits de parada"))
        self.stop_row.set_model(Gtk.StringList.new(["1", "1.5", "2"]))
        group.add(self.stop_row)

        self.parity_row = Adw.ComboRow(title=tr("Paridad"))
        self.parity_row.set_model(Gtk.StringList.new([tr("Ninguna"), tr("Par"),
                                                       tr("Impar"), tr("Marca"),
                                                       tr("Espacio")]))
        group.add(self.parity_row)
        self.page.add(group)

    def _build_advanced_group(self) -> None:
        group = Adw.PreferencesGroup(title=tr("Avanzado"))
        self.cmd_row = Adw.EntryRow(title=tr("Comando remoto"))
        group.add(self.cmd_row)

        self.local_row = Adw.EntryRow(title=tr("Directorio local"))
        group.add(self.local_row)

        self.remote_row = Adw.EntryRow(title=tr("Directorio remoto"))
        group.add(self.remote_row)

        self.fav_row = Adw.SwitchRow(title=tr("Favorita"))
        self.fav_row.set_active(self.existing.favorite if self.existing else False)
        group.add(self.fav_row)
        self.page.add(group)

    # ------------------------------------------------------------------
    def _sync_visibility(self) -> None:
        idx = self.type_row.get_selected()
        stype = SESSION_ICONS[idx][0] if 0 <= idx < len(SESSION_ICONS) else self.kind
        self.kind = stype
        is_serial = stype == SessionType.SERIAL
        is_net = stype in (SessionType.SSH, SessionType.TELNET, SessionType.RSH,
                            SessionType.FTP, SessionType.SFTP, SessionType.MOSH,
                            SessionType.RDP, SessionType.VNC, SessionType.XDMCPC)
        self.host_row.set_visible(is_net)
        self.port_row.set_visible(is_net)
        self.user_row.set_visible(stype not in (SessionType.FILE,
                                                SessionType.BROWSER))
        self.jump_row.set_visible(stype in (SessionType.SSH, SessionType.MOSH))
        self.url_row.set_visible(stype in (SessionType.FILE, SessionType.BROWSER))
        self.group_serial = self.port_combo.get_parent()
        self._serial_visible(is_serial)

    def _serial_visible(self, visible: bool) -> None:
        for widget in (self.port_combo, self.baud_row, self.bits_row,
                       self.stop_row, self.parity_row):
            try:
                widget.set_visible(visible)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _submit(self) -> None:
        idx = self.type_row.get_selected()
        stype = SESSION_ICONS[idx][0] if 0 <= idx < len(SESSION_ICONS) else self.kind

        session = self.existing or Session(id=f"{stype.value}-{uuid.uuid4().hex[:8]}",
                                           name="")
        session.type = stype
        session.name = self.name_row.get_text().strip() or (
            self.host_row.get_text().strip() or stype.label)
        session.group = self.group_row.get_text().strip() or tr("Mis sesiones")
        session.username = self.user_row.get_text().strip()
        session.host = self.host_row.get_text().strip()
        session.port = self.port_row.get_value_as_int()
        session.jump_host = self.jump_row.get_text().strip()
        session.key_file = os.path.expanduser(self.key_row.get_text().strip())
        session.x11_forward = self.x11_row.get_active()
        session.favorite = self.fav_row.get_active()
        session.remote_command = self.cmd_row.get_text().strip()
        session.local_dir = self.local_row.get_text().strip()
        session.remote_dir = self.remote_row.get_text().strip()

        if stype == SessionType.SERIAL:
            ports = serial_ports()
            sel = self.port_combo.get_selected()
            if 0 <= sel < len(ports):
                session.serial_port = ports[sel][0]
            session.baudrate = self.baud_row.get_value_as_int()
            session.databits = int(self.bits_row.get_selected()) + 5
            stop_text = self.stop_row.get_selected_item() or "1"
            session.stopbits = float(stop_text)
            parity_text = self.parity_row.get_selected_item() or tr("Ninguna")
            session.parity = {tr("Ninguna"): "N", tr("Par"): "E",
                              tr("Impar"): "O", tr("Marca"): "M",
                              tr("Espacio"): "S"}.get(parity_text, "N")

        password = self.password_row.get_text()
        if password:
            key = f"session:{session.id}"
            try:
                if VAULT.unlocked:
                    VAULT.set_secret(key, password)
                    session.password = key
                else:
                    session.password = password
            except Exception:
                session.password = password
        elif self.existing is None:
            session.password = ""

        self.emit("session-created", session, password)
        self.close()
