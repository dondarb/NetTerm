"""Explorador SFTP gráfico.

Equivalente al "Graphical SFTP browser" de MobaXterm: un árbol de archivos
remoto con arrastrar-y-soltar para subir y bajar ficheros de forma segura
(SFTP sobre la conexión SSH).

Usa paramiko para hablar SFTP, de modo que la conexión se comparte con la
terminal SSH de la misma sesión.
"""

from __future__ import annotations

import os
import posixpath
import threading
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, GObject, Gtk  # noqa: E402

from .i18n import tr  # noqa: E402

from .config import CONFIG  # noqa: E402
from .gobj import ItemObj, clear_list, item_store  # noqa: E402
from .session import Session, SessionType  # noqa: E402


class SftpConnection:
    """Conexión SFTP con paramiko."""

    def __init__(self, host: str, port: int = 22, username: str = "",
                 password: str = "", key_file: str = "",
                 jump_host: str = "", jump_user: str = "", jump_port: int = 22):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.key_file = key_file
        self.jump_host = jump_host
        self.jump_user = jump_user
        self.jump_port = jump_port
        self.ssh = None
        self.sftp = None

    def connect(self) -> tuple[bool, str]:
        try:
            import paramiko
        except ImportError:
            return False, tr("paramiko no está instalado (pip install paramiko)")
        try:
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            kwargs: dict[str, Any] = {
                "hostname": self.host,
                "port": self.port,
                "username": self.username or os.environ.get("USER", "root"),
                "timeout": 15,
            }
            if self.key_file and os.path.exists(self.key_file):
                kwargs["key_filename"] = self.key_file
            elif self.password:
                kwargs["password"] = self.password
            if self.jump_host:
                kwargs["sock"] = self._jump_socket(paramiko)
            self.ssh.connect(**kwargs)
            self.sftp = self.ssh.open_sftp()
            return True, tr("conectado")
        except Exception as exc:
            return False, str(exc)

    def _jump_socket(self, paramiko) -> Any:
        import socket

        transport = paramiko.Transport((self.jump_host, self.jump_port))
        transport.open_channel("direct-tcpip",
                               (self.host, self.port),
                               ("127.0.0.1", 0))
        return transport

    def close(self) -> None:
        for obj in (self.sftp, self.ssh):
            try:
                if obj:
                    obj.close()
            except Exception:
                pass
        self.sftp = None
        self.ssh = None

    def listdir(self, path: str) -> list[tuple[str, list[str], int]]:
        """Devuelve ``[(nombre, attrs_long, size)]`` ordenados."""
        assert self.sftp is not None
        entries = []
        for attr in self.sftp.listdir_attr(path):
            size = attr.st_size or 0
            longname = attr.longname
            entries.append((attr.filename, longname, size))
        entries.sort(key=lambda e: (not e[1].startswith("d"), e[0].lower()))
        return entries

    def download(self, remote: str, local: str) -> tuple[bool, str]:
        assert self.sftp is not None
        try:
            self.sftp.get(remote, local)
            return True, f"{tr('Descargado')} {remote}"
        except Exception as exc:
            return False, str(exc)

    def upload(self, local: str, remote: str) -> tuple[bool, str]:
        assert self.sftp is not None
        try:
            self.sftp.put(local, remote)
            return True, f"{tr('Subido')} {local}"
        except Exception as exc:
            return False, str(exc)

    def mkdir(self, path: str) -> tuple[bool, str]:
        assert self.sftp is not None
        try:
            self.sftp.mkdir(path)
            return True, f"{tr('Directorio creado')}: {path}"
        except Exception as exc:
            return False, str(exc)

    def remove(self, path: str) -> tuple[bool, str]:
        assert self.sftp is not None
        try:
            attr = self.sftp.stat(path)
            if attr.st_mode & 0o40000:
                self.sftp.rmdir(path)
            else:
                self.sftp.remove(path)
            return True, f"{tr('Eliminado')}: {path}"
        except Exception as exc:
            return False, str(exc)

    def read(self, path: str) -> tuple[bool, str]:
        assert self.sftp is not None
        try:
            with self.sftp.open(path, "r") as fh:
                return True, fh.read().decode("utf-8", errors="replace")
        except Exception as exc:
            return False, str(exc)

    def write(self, path: str, content: str) -> tuple[bool, str]:
        assert self.sftp is not None
        try:
            with self.sftp.open(path, "w") as fh:
                fh.write(content.encode("utf-8"))
            return True, f"{tr('Guardado')}: {path}"
        except Exception as exc:
            return False, str(exc)


class SftpPanel(Gtk.Box):
    """Panel lateral con el explorador de archivos remoto."""

    __gsignals__ = {
        "status-message": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "open-editor": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
    }

    def __init__(self, parent=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.parent = parent
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        self.set_margin_start(4)
        self.set_margin_end(6)
        self.conn: SftpConnection | None = None
        self.current_path = "."

        # -- selector de sesión -----------------------------------------
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.session_store = Gtk.StringList()
        self.session_combo = Gtk.DropDown(model=self.session_store)
        self.session_combo.set_tooltip_text(tr("Sesión SSH a explorar"))
        top.append(self.session_combo)
        self.connect_btn = Gtk.Button(icon_name="network-server-symbolic",
                                      tooltip_text=tr("Conectar"))
        self.connect_btn.connect("clicked", lambda *_: self._connect())
        top.append(self.connect_btn)
        self.append(top)

        # -- ruta actual -------------------------------------------------
        path_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.path_entry = Gtk.Entry(text="/")
        self.path_entry.connect("activate", lambda *_: self._goto(self.path_entry.get_text()))
        path_box.append(self.path_entry)
        up = Gtk.Button(icon_name="go-up-symbolic", tooltip_text=tr("Subir"))
        up.connect("clicked", lambda *_: self._go_up())
        path_box.append(up)
        self.append(path_box)

        # -- toolbar -----------------------------------------------------
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        for icon, tip, cb in (
            ("folder-new-symbolic", tr("Crear directorio"), self._mkdir),
            ("document-save-symbolic", tr("Subir fichero"), self._upload_dialog),
            ("folder-download-symbolic", tr("Descargar fichero"), self._download),
            ("view-refresh-symbolic", tr("Actualizar"), self._reload),
            ("user-trash-symbolic", tr("Eliminar"), self._delete),
            ("document-edit-symbolic", tr("Editar"), self._edit),
        ):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip)
            b.connect("clicked", lambda *_a, f=cb: f())
            bar.append(b)
        self.append(bar)

        # -- árbol de ficheros ---------------------------------------------
        self.store = item_store()
        self._selection = Gtk.SingleSelection(model=self.store)
        self.view = Gtk.ColumnView(model=self._selection)
        self.view.set_show_column_separators(False)

        def add_col(title, value):
            factory = Gtk.SignalListItemFactory()
            factory.connect("setup", self._setup, value)
            factory.connect("bind", self._bind, value)
            col = Gtk.ColumnViewColumn()
            col.set_title(title)
            col.set_factory(factory)
            col.set_expand(True)
            self.view.append_column(col)

        add_col(tr("Nombre"), lambda e: e["name"])
        add_col(tr("Tamaño"), lambda e: e["size"])
        add_col(tr("Permisos"), lambda e: e["mode"])

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(self.view)
        self.append(scroller)

        self.follow = Gtk.CheckButton(label=tr("Seguir la carpeta del terminal"))
        self.follow.set_active(bool(CONFIG.get("sftp_follow_terminal", True)))
        self.append(self.follow)

        self.status = Gtk.Label(label=tr("Sin conexión"))
        self.status.add_css_class("dim-label")
        self.status.add_css_class("caption")
        self.status.set_xalign(0)
        self.status.set_ellipsize(3)
        self.append(self.status)

        self.refresh_sessions()

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
    def refresh_sessions(self) -> None:
        clear_list(self.session_store)
        for s in CONFIG.sessions:
            if s.type in (SessionType.SSH, SessionType.SFTP):
                self.session_store.append(s.name)

    def refresh(self) -> None:
        self.refresh_sessions()
        if self.conn:
            self._reload()

    # ------------------------------------------------------------------
    def _connect(self) -> None:
        idx = self.session_combo.get_selected()
        if idx < 0:
            self._set_status(tr("Selecciona una sesión"))
            return
        sessions = [s for s in CONFIG.sessions
                    if s.type in (SessionType.SSH, SessionType.SFTP)]
        if idx >= len(sessions):
            return
        session = sessions[idx]
        from .secrets import VAULT

        password = VAULT.get_secret(session.password) or ""
        self.conn = SftpConnection(session.host, session.port, session.username,
                                   password, session.key_file,
                                   session.jump_host, session.jump_user,
                                   session.jump_port)
        self._set_status(tr("Conectando…"))
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self) -> None:
        assert self.conn is not None
        ok, msg = self.conn.connect()
        GLib.idle_add(self._connected, ok, msg)

    def _connected(self, ok: bool, msg: str) -> None:
        if ok:
            self._set_status(f"{tr('Conectado a')} {self.conn.host}")  # type: ignore[union-attr]
            self._reload()
        else:
            self._set_status(f"{tr('Error')}: {msg}")

    def _set_status(self, text: str) -> None:
        self.status.set_text(text)
        self.emit("status-message", text)

    # ------------------------------------------------------------------
    def _reload(self) -> None:
        if not self.conn or not self.conn.sftp:
            return
        path = self.path_entry.get_text().strip() or "/"
        self.current_path = path

        def _worker() -> None:
            assert self.conn is not None
            try:
                entries = self.conn.listdir(path)
            except Exception as exc:
                GLib.idle_add(self._set_status, f"{tr('Error')}: {exc}")
                return
            rows = []
            for name, longname, size in entries:
                if name in (".", ".."):
                    continue
                mode = longname[0:10] if len(longname) >= 10 else ""
                is_dir = longname.startswith("d")
                rows.append({
                    "name": ("📁 " if is_dir else "📄 ") + name,
                    "size": "" if is_dir else _human(size),
                    "mode": mode,
                    "path": posixpath.join(path, name),
                    "dir": is_dir,
                    "raw": name,
                })
            GLib.idle_add(self._fill, rows)

        threading.Thread(target=_worker, daemon=True).start()

    def _fill(self, rows: list[dict[str, Any]]) -> None:
        self.store.remove_all()
        for r in rows:
            self.store.append(ItemObj(r))

    def _selected(self) -> dict[str, Any] | None:
        item = self._selection.get_selected_item()
        if item is None:
            return None
        value = item.value
        return value if isinstance(value, dict) else None

    def _goto(self, path: str) -> None:
        self.path_entry.set_text(path)
        self._reload()

    def _go_up(self) -> None:
        current = self.path_entry.get_text().strip() or "/"
        parent = posixpath.dirname(current.rstrip("/")) or "/"
        self._goto(parent)

    # ------------------------------------------------------------------
    def _mkdir(self) -> None:
        if not self.conn:
            return
        dialog = TextInputDialog(self.get_root(), tr("Nuevo directorio"),
                                 tr("nombre del directorio"))
        dialog.connect("response", self._do_mkdir)
        dialog.present()

    def _do_mkdir(self, dialog, response) -> None:
        if response != Gtk.ResponseType.OK:
            return
        name = dialog.entry.get_text().strip()
        if not self.conn or not name:
            return
        path = posixpath.join(self.path_entry.get_text().strip() or "/", name)
        threading.Thread(target=self._mkdir_worker, args=(path,),
                         daemon=True).start()

    def _mkdir_worker(self, path: str) -> None:
        assert self.conn is not None
        ok, msg = self.conn.mkdir(path)
        GLib.idle_add(self._set_status, msg)
        if ok:
            GLib.idle_add(self._reload)

    def _download(self) -> None:
        row = self._selected()
        if not row or not self.conn:
            return
        path = row["path"]

        def _worker() -> None:
            assert self.conn is not None
            local = os.path.join(os.path.expanduser("~"), os.path.basename(path))
            ok, msg = self.conn.download(path, local)
            GLib.idle_add(self._set_status, msg)

        threading.Thread(target=_worker, daemon=True).start()

    def _upload_dialog(self) -> None:
        if not self.conn:
            return
        file_chooser = Gtk.FileChooserNative(
            title=tr("Subir fichero al servidor"),
            transient_for=self.get_root() if self.get_root() else None,
            action=Gtk.FileChooserAction.OPEN,
            accept_label=tr("Subir"),
            cancel_label=tr("Cancelar"),
        )
        file_chooser.connect("response", self._on_upload_chosen)
        file_chooser.show()

    def _on_upload_chosen(self, chooser, response) -> None:
        if response != Gtk.ResponseType.ACCEPT:
            chooser.destroy()
            return
        file = chooser.get_file()
        chooser.destroy()
        if not file:
            return
        remote = posixpath.join(self.path_entry.get_text().strip() or "/",
                                os.path.basename(file.get_path()))

        def _worker() -> None:
            assert self.conn is not None
            ok, msg = self.conn.upload(file.get_path(), remote)
            GLib.idle_add(self._set_status, msg)
            if ok:
                GLib.idle_add(self._reload)

        threading.Thread(target=_worker, daemon=True).start()

    def _delete(self) -> None:
        row = self._selected()
        if not row or not self.conn:
            return
        path = row["path"]

        def _worker() -> None:
            assert self.conn is not None
            ok, msg = self.conn.remove(path)
            GLib.idle_add(self._set_status, msg)
            if ok:
                GLib.idle_add(self._reload)

        threading.Thread(target=_worker, daemon=True).start()

    def _edit(self) -> None:
        row = self._selected()
        if not row or not self.conn:
            return
        path = row["path"]
        self.emit("open-editor", path, "")


def _human(size: int) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024:
            return f"{size}{unit}"
        size /= 1024.0
    return f"{size:.1f}P"


class TextInputDialog(Adw.MessageDialog):
    """Diálogo modal con un único campo de texto."""

    def __init__(self, parent, heading: str, placeholder: str = ""):
        super().__init__(transient_for=parent, heading=heading, body="")
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text(placeholder)
        self.entry.set_activates_default(True)
        self.set_extra_child(self.entry)
        self.add_response("cancelar", tr("Cancelar"))
        self.add_response("aceptar", tr("Aceptar"))
        self.set_response_appearance("aceptar", Adw.ResponseAppearance.SUGGESTED)
        self.set_default_response("aceptar")
        self.set_close_response("cancelar")
