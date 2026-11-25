"""Aplicación NetTerm: punto de entrada y acciones globales.

Terminal avanzada, alternativa nativa a MobaXterm en Linux. Cliente open
source de terminal, SSH, SFTP y consola serie.
"""

from __future__ import annotations

import os
import signal
import sys

from . import bootstrap_vendor as _bootstrap

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .config import APP_ID, APP_NAME, CONFIG  # noqa: E402
from .version import VERSION  # noqa: E402
from .i18n import tr  # noqa: E402



class NetTermApp(Adw.Application):
    """Aplicación principal de NetTerm."""

    def __init__(self, app_id: str | None = None) -> None:
        super().__init__(application_id=app_id or APP_ID,
                         flags=Gio.ApplicationFlags.FLAGS_NONE,
                         resource_base_path="/io/github/netterm/netterm")
        self.window = None
        self._add_actions()

    # ------------------------------------------------------------------
    def do_activate(self) -> None:
        if self.window is None:
            from .window import MainWindow

            self.window = MainWindow(application=self)
        self.window.present()
        self._apply_theme()
        self._maybe_snapshot()

    def _maybe_snapshot(self) -> None:
        """Guarda un PNG de la ventana (útil para depurar sin captura de pantalla).

        Se activa con ``NETTERM_SNAPSHOT=/ruta/foto.png``.
        """
        target = os.environ.get("NETTERM_SNAPSHOT")
        if not target or self.window is None:
            return

        def _snap() -> bool:
            try:
                self.window.snapshot_to_png(target)
            except Exception as exc:  # pragma: no cover
                print(f"No se pudo guardar la captura: {exc}", flush=True)
            return False

        GLib.timeout_add(2500, _snap)

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self._install_accels()
        if CONFIG.get("custom_banner") is None:
            CONFIG.set("custom_banner", "")
            CONFIG.save_settings()

    # ------------------------------------------------------------------
    def _apply_theme(self) -> None:
        style = Adw.StyleManager.get_default()
        theme = CONFIG.get("theme", "dark")
        if theme == "light":
            style.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        elif theme == "system":
            style.set_color_scheme(Adw.ColorScheme.DEFAULT)
        else:
            style.set_color_scheme(Adw.ColorScheme.FORCE_DARK)

    def _install_accels(self) -> None:
        accels = {
            "<Control>t": "win.new-local",
            "<Control><Shift>t": "win.new-ssh",
            "<Control><Shift>s": "win.new-serial",
            "<Control><Shift>b": "win.new-sftp",
            "<Control>w": "win.close-tab",
            "<Control>q": "app.quit",
            "<Control>plus": "win.zoom-in",
            "<Control>minus": "win.zoom-out",
            "<Control>f": "win.find",
            "<Control><Shift>f": "win.find",
            "<Control>c": "win.copy",
            "<Control>v": "win.paste",
        }
        for accel, action in accels.items():
            self.set_accels_for_action(action, [accel])

    # ------------------------------------------------------------------
    def _add_actions(self) -> None:
        actions = {
            "quit": (self._on_quit, "<Control>q"),
            "about": (self._on_about, None),
            "preferences": (self._on_preferences, None),
            "new-local": (lambda *_: self._new("local"), None),
            "new-ssh": (lambda *_: self._new("ssh"), None),
            "new-serial": (lambda *_: self._new("serial"), None),
            "new-sftp": (lambda *_: self._new("sftp"), None),
            "new-telnet": (lambda *_: self._new("telnet"), None),
            "new-mosh": (lambda *_: self._new("mosh"), None),
            "new-rdp": (lambda *_: self._new("rdp"), None),
            "new-vnc": (lambda *_: self._new("vnc"), None),
            "new-browser": (lambda *_: self._new("browser"), None),
            "close-tab": (lambda *_: self._close_tab(), None),
            "split": (lambda *_: self._split(), None),
            "multi-exec": (lambda *_: self._toggle_multi_exec(), None),
            "zoom-in": (lambda *_: self._zoom(1), None),
            "zoom-out": (lambda *_: self._zoom(-1), None),
            "find": (lambda *_: self._find(), None),
            "copy": (lambda *_: self._copy(), None),
            "paste": (lambda *_: self._paste(), None),
            "clear": (lambda *_: self._clear(), None),
            "focus-search": (lambda *_: self._focus_search(), None),
            "refresh-interfaces": (lambda *_: self._refresh_interfaces(), None),
        }
        for name, (callback, accel) in actions.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
            if accel:
                self.set_accels_for_action(f"app.{name}", [accel])

    # ------------------------------------------------------------------
    def _on_quit(self, *_args) -> None:
        if self.window:
            self.window.confirm_quit()
        else:
            self.quit()

    def _on_about(self, *_args) -> None:
        about = Adw.AboutWindow(
            transient_for=self.window,
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=VERSION,
            developer_name="NetTerm",
            comments=tr("Terminal avanzada, alternativa nativa a MobaXterm "
                       "en Linux"),
            license_type=Gtk.License.GPL_3_0,
        )
        about.add_link(tr("Documentación de GTK4"),
                       "https://docs.gtk.org/gtk4/")
        about.present()

    def _on_preferences(self, *_args) -> None:
        if self.window:
            self.window.show_preferences()

    # ------------------------------------------------------------------
    def _new(self, kind: str) -> None:
        if self.window:
            self.window.new_session(kind)

    def _close_tab(self) -> None:
        if self.window:
            self.window.close_current_tab()

    def _split(self) -> None:
        if self.window:
            self.window.split_view()

    def _toggle_multi_exec(self) -> None:
        if self.window:
            self.window.toggle_multi_exec()

    def _zoom(self, delta: int) -> None:
        if self.window:
            page = self.window.current_page()
            if page:
                page.zoom(delta)

    def _find(self) -> None:
        if self.window:
            page = self.window.current_page()
            if page:
                page.find()

    def _copy(self) -> None:
        if self.window:
            page = self.window.current_page()
            if page:
                page.copy()

    def _paste(self) -> None:
        if self.window:
            page = self.window.current_page()
            if page:
                page.paste()

    def _clear(self) -> None:
        if self.window:
            page = self.window.current_page()
            if page:
                page.clear()

    def _focus_search(self) -> None:
        if self.window:
            self.window.focus_quick_connect()

    def _refresh_interfaces(self) -> None:
        if self.window:
            self.window.refresh_interfaces()


def bootstrap_vendor() -> bool:
    """Añade las tipografías GI locales (VTE) si el sistema no las trae.

    Delegates to :func:`netterm.bootstrap_vendor`, which already ran when the
    package was imported (before ``gi`` was loaded).
    """
    return _bootstrap()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--version" in argv or "-V" in argv:
        print(f"{APP_NAME} {VERSION}")
        return 0
    GLib.set_application_name(APP_NAME)
    GLib.set_prgname(APP_ID)
    bootstrap_vendor()
    app = NetTermApp()
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    return app.run([])
