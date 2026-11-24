"""Terminales VTE: local, SSH, Telnet, Rsh, Mosh y consola serie.

Reproduce el "MobaXterm tabbed terminal" con soporte de:
  * shell local con todas las herramientas Unix del sistema
  * SSH con pasarela (jump host), agente, X11-forwarding y túneles
  * consola serie RS-232 con acceso directo al hardware (pyserial)
  * grabación/reproducción de macros
  * modo multi-ejecución (difusión de teclado a varias terminales)
"""

from __future__ import annotations

import os
import shlex
import signal
import threading
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Vte", "3.91")
gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gdk, GObject, Gtk, Pango, PangoCairo, Vte  # noqa: E402

from .config import CONFIG  # noqa: E402
from .i18n import tr  # noqa: E402
from .session import Session, SessionType  # noqa: E402

# ---------------------------------------------------------------------------
# Utilidades de teclado para la consola serie
# ---------------------------------------------------------------------------

_SPECIAL_KEYS: dict[int, bytes] = {
    Gdk.KEY_Return: b"\r",
    Gdk.KEY_KP_Enter: b"\r",
    Gdk.KEY_BackSpace: b"\x7f",
    Gdk.KEY_Tab: b"\t",
    Gdk.KEY_Escape: b"\x1b",
    Gdk.KEY_Up: b"\x1b[A",
    Gdk.KEY_Down: b"\x1b[B",
    Gdk.KEY_Right: b"\x1b[C",
    Gdk.KEY_Left: b"\x1b[D",
    Gdk.KEY_Home: b"\x1b[H",
    Gdk.KEY_End: b"\x1b[F",
    Gdk.KEY_Page_Up: b"\x1b[5~",
    Gdk.KEY_Page_Down: b"\x1b[6~",
    Gdk.KEY_Delete: b"\x1b[3~",
    Gdk.KEY_Insert: b"\x1b[2~",
    Gdk.KEY_F1: b"\x1bOP",
    Gdk.KEY_F2: b"\x1bOQ",
    Gdk.KEY_F3: b"\x1bOR",
    Gdk.KEY_F4: b"\x1bOS",
    Gdk.KEY_F5: b"\x1b[15~",
    Gdk.KEY_F6: b"\x1b[17~",
    Gdk.KEY_F7: b"\x1b[18~",
    Gdk.KEY_F8: b"\x1b[19~",
    Gdk.KEY_F9: b"\x1b[20~",
    Gdk.KEY_F10: b"\x1b[21~",
    Gdk.KEY_F11: b"\x1b[23~",
    Gdk.KEY_F12: b"\x1b[24~",
}


def keyval_to_bytes(keyval: int, unicode_char: str = "") -> bytes:
    """Convierte una pulsación de teclado en los bytes que envía un terminal."""
    if keyval in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[keyval]
    if unicode_char and unicode_char.isprintable():
        return unicode_char.encode("utf-8")
    return b""


# ---------------------------------------------------------------------------


class SerialChannel:
    """Consola serie directa al hardware mediante pyserial.

    A diferencia de Wine/Bottles, aquí se habla con el ``termios`` del kernel:
    acceso real al puerto, sin intermediario ni emulación de Windows.
    """

    def __init__(self, port: str, baudrate: int = 115200, databits: int = 8,
                 stopbits: float = 1.0, parity: str = "N",
                 on_data: Callable[[str], None] | None = None,
                 on_error: Callable[[str], None] | None = None):
        self.port = port
        self.baudrate = baudrate
        self.databits = databits
        self.stopbits = stopbits
        self.parity = parity
        self._on_data = on_data
        self._on_error = on_error
        self._serial = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def open(self) -> bool:
        try:
            import serial  # pyserial
        except ImportError:
            self._on_error and self._on_error(tr("pyserial no está instalado"))
            return False
        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=self.databits,
                stopbits=self.stopbits,
                parity=self.parity,
                timeout=0.2,
            )
        except Exception as exc:
            self._on_error and self._on_error(
                f"{tr('No se pudo abrir')} {self.port}: {exc}")
            return False

        self._stop.clear()
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()
        return True

    def _reader(self) -> None:
        assert self._serial is not None
        while not self._stop.is_set():
            try:
                data = self._serial.read(4096)
            except Exception as exc:
                if not self._stop.is_set():
                    self._on_error and self._on_error(
                        tr("Error serie: {error}", error=exc))
                break
            if data:
                text = data.decode("utf-8", errors="replace")
                if self._on_data:
                    GLib.idle_add(self._on_data, text)

    def write(self, data: bytes) -> None:
        if not self._serial:
            return
        try:
            self._serial.write(data)
            self._serial.flush()
        except Exception as exc:
            self._on_error and self._on_error(
                tr("Error escribiendo: {error}", error=exc))

    def close(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

    @property
    def connected(self) -> bool:
        return self._serial is not None and self._serial.is_open


class TerminalPage(Gtk.Box):
    """Una pestaña de terminal."""

    __gsignals__ = {
        "closed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "title-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, title: str = tr("Terminal"), kind: str = "local",
                 session: Session | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.session = session
        self.kind = kind
        self._title = title
        self._child_pid = 0
        self._serial: SerialChannel | None = None
        self._macro_recorder = None
        self._broadcast = False
        # Las sesiones remotas dejan la pestaña abierta al terminar;
        # el shell local la cierra (como una terminal normal).
        self.close_on_exit = kind in ("local", "shell", "")

        self.set_hexpand(True)
        self.set_vexpand(True)

        # -- cabecera de la pestaña -------------------------------------
        self.header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.header.set_margin_top(4)
        self.header.set_margin_bottom(4)
        self.header.set_margin_start(8)
        self.header.set_margin_end(8)

        self.icon = Gtk.Image.new_from_icon_name("utilities-terminal-symbolic")
        self.title_label = Gtk.Label(label=title)
        self.title_label.set_ellipsize(3)  # Pango.EllipsizeMode.END
        self.title_label.set_xalign(0)
        self.subtitle_label = Gtk.Label(label="")
        self.subtitle_label.add_css_class("dim-label")
        self.subtitle_label.add_css_class("caption")
        self.subtitle_label.set_ellipsize(3)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_valign(Gtk.Align.CENTER)
        box.append(self.title_label)
        box.append(self.subtitle_label)
        self.header.append(self.icon)
        self.header.append(box)

        self.status_label = Gtk.Label(label="")
        self.status_label.add_css_class("dim-label")
        self.status_label.add_css_class("caption")
        self.header.append(self.status_label)

        self.spinner = Gtk.Spinner(spinning=False)
        self.spinner.set_size_request(18, 18)
        self.header.append(self.spinner)

        # -- terminal VTE -----------------------------------------------
        self.terminal = Vte.Terminal()
        self.terminal.set_hexpand(True)
        self.terminal.set_vexpand(True)
        self.terminal.set_scrollback_lines(int(CONFIG.get("scrollback", 10000)))
        self.terminal.set_cursor_blink_mode(
            Vte.CursorBlinkMode.ON if CONFIG.get("cursor_blink", True)
            else Vte.CursorBlinkMode.OFF)
        self.terminal.set_mouse_autohide(True)
        self.terminal.set_word_char_exceptions("-A-Za-z0-9,./?%&#:_=+@~")
        self.terminal.set_input_enabled(True)
        self._apply_font()

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_hexpand(True)
        self.scroller.set_vexpand(True)
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_child(self.terminal)

        self.append(self.header)
        self.append(self.scroller)

        self._install_shortcuts()
        self.terminal.connect("child-exited", self._on_child_exited)
        self.terminal.connect("window-title-changed", self._on_title_changed)

    # ------------------------------------------------------------------
    def _apply_font(self) -> None:
        font = CONFIG.get("font", "Monospace 11")
        desc = Pango.FontDescription(font)
        desc.set_size(int(CONFIG.get("font_size", 11)) * Pango.SCALE)
        self.terminal.set_font(desc)

    def _install_shortcuts(self) -> None:
        """Atajos de teclado del terminal (captura de Ctrl/Shift)."""
        ctrl = Gdk.ModifierType.CONTROL_MASK
        shift = Gdk.ModifierType.SHIFT_MASK

        def handler(_controller, keyval, _keycode, state) -> bool:
            if not state & ctrl:
                return False
            if keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
                self.zoom(1)
                return True
            if keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
                self.zoom(-1)
                return True
            if keyval in (Gdk.KEY_f, Gdk.KEY_F):
                self.find()
                return True
            if keyval in (Gdk.KEY_l, Gdk.KEY_L):
                self.clear()
                return True
            if keyval in (Gdk.KEY_v, Gdk.KEY_V):
                self.paste()
                return True
            if keyval in (Gdk.KEY_c, Gdk.KEY_C) and state & shift:
                # Ctrl+Shift+C copia; Ctrl+C debe llegar al proceso (SIGINT).
                self.copy()
                return True
            return False

        controller = Gtk.EventControllerKey()
        controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        controller.connect("key-pressed", handler)
        self.terminal.add_controller(controller)

    # ------------------------------------------------------------------
    # Arranque de procesos
    # ------------------------------------------------------------------
    def spawn_local(self) -> None:
        shell = CONFIG.get("default_shell") or os.environ.get("SHELL", "/bin/bash")
        argv = [shell, "-l"]
        self.spawn(argv, title=tr("Shell"), subtitle=tr("local"))

    def spawn_ssh(self, session: Session, password: str = "") -> None:
        argv = ["ssh"]
        if session.port and session.port != 22:
            argv += ["-p", str(session.port)]
        if session.key_file and os.path.exists(session.key_file):
            argv += ["-i", session.key_file]
            if session.key_passphrase:
                argv += ["-o", "IdentityAgent=none"]
        if session.jump_host:
            jump = session.jump_host
            if session.jump_user:
                jump = f"{session.jump_user}@{jump}"
            if session.jump_port and session.jump_port != 22:
                jump = f"{jump}:{session.jump_port}"
            argv += ["-J", jump]
        if session.x11_forward:
            argv.append("-X")
        if session.compress:
            argv.append("-C")
        if session.keepalive:
            argv += ["-o", f"ServerAliveInterval={session.keepalive}"]
        extra = (CONFIG.get("ssh_options") or "").strip()
        if extra:
            argv += shlex.split(extra)
        target = f"{session.username}@{session.host}" if session.username else session.host
        argv.append(target)
        if session.remote_command:
            argv += shlex.split(session.remote_command)
        title = session.name
        subtitle = f"{target}:{session.port}"
        self.spawn(argv, title=title, subtitle=subtitle,
                   env_extra={"NETTERM_SESSION_PASSWORD": password} if password else None)

    def spawn_telnet(self, session: Session) -> None:
        argv = ["telnet"]
        if session.port and session.port != 23:
            argv.append(str(session.port))
        argv.append(session.host)
        self.spawn(argv, title=session.name, subtitle=f"telnet {session.host}")

    def spawn_rsh(self, session: Session) -> None:
        argv = ["rsh", "-l", session.username or os.environ.get("USER", "root"),
                session.host]
        self.spawn(argv, title=session.name, subtitle=f"rsh {session.host}")

    def spawn_mosh(self, session: Session) -> None:
        argv = ["mosh", "--ssh", f"ssh -p {session.port}"]
        if session.jump_host:
            argv += ["-J", session.jump_host]
        argv.append(f"{session.username}@{session.host}" if session.username
                    else session.host)
        self.spawn(argv, title=session.name, subtitle=f"mosh {session.host}")

    def spawn(self, argv: list[str], title: str = "", subtitle: str = "",
              env_extra: dict[str, str] | None = None) -> None:
        env = dict(os.environ)
        if env_extra:
            env.update(env_extra)
        envv = [f"{k}={v}" for k, v in env.items()]
        self.title = title
        self.subtitle = subtitle
        self.spinner.start()
        try:
            self.terminal.spawn_async(
                Vte.PtyFlags.DEFAULT,
                None,
                argv,
                envv,
                GLib.SpawnFlags.DEFAULT,
                None,
                None,
                -1,
                None,
                self._on_spawned,
            )
        except GLib.Error as exc:
            self.spinner.stop()
            self.feed(f"\r\n\x1b[31mNo se pudo iniciar {argv[0]}: {exc.message}\x1b[0m\r\n")

    def _on_spawned(self, _terminal, pid: int, error, *_args) -> None:
        if error is not None:
            self.spinner.stop()
            self.feed(f"\r\n\x1b[31mError al iniciar: {error.message}\x1b[0m\r\n")
            return
        self._child_pid = pid
        self.spinner.stop()
        self.status_label.set_text("")

    # ------------------------------------------------------------------
    # Consola serie
    # ------------------------------------------------------------------
    def open_serial(self, session: Session) -> None:
        port = session.serial_port
        if not port:
            self.feed("\r\n\x1b[31m"
                      + tr("No se ha configurado el puerto serie.")
                      + "\x1b[0m\r\n")
            return
        self.title = session.name
        self.subtitle = f"{port} @ {session.baudrate}"
        self.icon.set_from_icon_name("computer-symbolic")
        self.terminal.set_input_enabled(False)

        channel = SerialChannel(
            port, session.baudrate, session.databits, session.stopbits,
            session.parity,
            on_data=self._on_serial_data,
            on_error=self._on_serial_error,
        )
        if not channel.open():
            self.feed(f"\r\n\x1b[31m{tr('No se pudo abrir')} {port}. "
                      f"{tr('Comprueba los permisos (grupo dialout).')}"
                      "\x1b[0m\r\n")
            return
        self._serial = channel
        self.status_label.set_text(tr("serie"))
        self._install_serial_keys()

    def _on_serial_data(self, text: str) -> bool:
        self.terminal.feed(text.encode("utf-8", errors="replace"))
        return False

    def _on_serial_error(self, message: str) -> bool:
        self.feed(f"\r\n\x1b[31m{message}\x1b[0m\r\n")
        return False

    def _install_serial_keys(self) -> None:
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_serial_key)
        self.terminal.add_controller(controller)

    def _on_serial_key(self, _controller, keyval: int, keycode: int, state) -> bool:
        if not self._serial:
            return False
        ctrl = state & Gdk.ModifierType.CONTROL_MASK
        if ctrl and keyval in (Gdk.KEY_c, Gdk.KEY_C):
            self.copy()
            return True
        if ctrl and keyval in (Gdk.KEY_v, Gdk.KEY_V):
            self.paste()
            return True
        char = chr(Gdk.keyval_to_unicode(keyval)) if Gdk.keyval_to_unicode(keyval) else ""
        data = keyval_to_bytes(keyval, char)
        if data:
            self._serial.write(data)
            return True
        return False

    # ------------------------------------------------------------------
    # Operaciones de terminal
    # ------------------------------------------------------------------
    def feed(self, text: str) -> None:
        """Escribe texto en el terminal (VTE exige bytes)."""
        self.terminal.feed(text.encode("utf-8", errors="replace"))

    def copy(self) -> None:
        self.terminal.copy_clipboard_format(Vte.Format.TEXT)

    def paste(self) -> None:
        self.terminal.paste_clipboard()

    def clear(self) -> None:
        self.terminal.reset(True, True)

    def zoom(self, delta: int) -> None:
        desc = self.terminal.get_font()
        size = desc.get_size() / Pango.SCALE + delta
        size = max(6, min(48, int(size)))
        desc.set_size(size * Pango.SCALE)
        self.terminal.set_font(desc)

    def find(self) -> None:
        dialog = Gtk.Dialog(title=tr("Buscar"), transient_for=self.get_root())
        entry = Gtk.SearchEntry()
        entry.set_placeholder_text(tr("Texto a buscar"))
        dialog.get_content_area().append(entry)
        dialog.add_button(tr("Cerrar"), Gtk.ResponseType.CLOSE)
        dialog.add_button(tr("Buscar"), Gtk.ResponseType.APPLY)

        def on_apply(_d, _r):
            text = entry.get_text()
            if text:
                self.terminal.search_set_regex(
                    __import__("re").escape(text), 0, 0)
                self.terminal.search_set_wrap_around(True)
                if not self.terminal.search_find_next():
                    self.terminal.search_set_regex(
                        __import__("re").escape(text), 0, 0)
                    self.terminal.search_find_next()

        dialog.connect("response", on_apply)
        dialog.present()

    # ------------------------------------------------------------------
    @property
    def title(self) -> str:
        return self._title

    @title.setter
    def title(self, value: str) -> None:
        self._title = value
        self.title_label.set_text(value)
        self.emit("title-changed", value)

    @property
    def subtitle(self) -> str:
        return getattr(self, "_subtitle", "")

    @subtitle.setter
    def subtitle(self, value: str) -> None:
        self._subtitle = value
        self.subtitle_label.set_text(value)

    def _on_title_changed(self, terminal) -> None:
        remote = terminal.get_window_title()
        if remote:
            self.title = remote

    def _on_child_exited(self, _terminal, status: int) -> None:
        self.spinner.stop()
        if self._serial:
            self._serial.close()
            self._serial = None
        self.status_label.set_text(tr("sesión cerrada"))
        self.feed("\r\n\x1b[33m" + tr("[sesión terminada]") + "\x1b[0m\r\n")
        if self.close_on_exit:
            # Sólo el shell local cierra su pestaña al terminar.
            # Una sesión remota terminada deja la pestaña con el aviso, para
            # poder revisarla y cerrarla a mano.
            self.emit("closed")

    def close(self) -> None:
        if self._serial:
            self._serial.close()
            self._serial = None
        if self._child_pid:
            try:
                os.kill(self._child_pid, signal.SIGHUP)
            except (OSError, ProcessLookupError):
                pass
            self._child_pid = 0

    # -- soporte multi-ejecución -----------------------------------------
    def send_text(self, text: str) -> None:
        """Envía texto como si el usuario lo escribiera (multi-ejecución)."""
        self.terminal.feed_child(text.encode("utf-8"))
