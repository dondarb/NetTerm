"""Ventana independiente para una sesión.

En MobaXterm cada sesión (SSH, serie, telnet, RDP…) se abre en una **ventana
propia**, mientras que el terminal local permanece como pestaña en la ventana
principal. NetTerm reproduce ese comportamiento: las sesiones remotas se
abren en ventanas nuevas y el shell local en pestañas.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .config import CONFIG  # noqa: E402
from .i18n import tr  # noqa: E402
from .session import Session, SessionType  # noqa: E402
from .terminal import TerminalPage  # noqa: E402


class SessionWindow(Adw.ApplicationWindow):
    """Ventana con una única sesión de terminal."""

    def __init__(self, application=None, session: Session | None = None,
                 password: str = "", title: str = ""):
        super().__init__(application=application)
        self.session = session
        self._page: TerminalPage | None = None

        self.set_title(title or (session.name if session else tr("Session")))
        self.set_default_size(920, 620)
        self.set_size_request(560, 380)

        header = Adw.HeaderBar()

        # -- menú de la ventana -----------------------------------------
        menu = Gio.Menu()
        menu.append(tr("Copy"), "win.copy")
        menu.append(tr("Paste"), "win.paste")
        menu.append(tr("Find…"), "win.find")
        menu.append(tr("Clear terminal"), "win.clear")
        menu.append(tr("Separator"), None)
        menu.append(tr("Zoom in"), "win.zoom-in")
        menu.append(tr("Zoom out"), "win.zoom-out")
        menu.append(tr("Separator"), None)
        menu.append(tr("Close session"), "win.close-session")

        button = Gtk.MenuButton(icon_name="open-menu-symbolic",
                                tooltip_text=tr("Main menu"))
        button.set_menu_model(menu)
        header.pack_start(button)

        if session is not None:
            subtitle = Gtk.Label(label=session.display_target())
            subtitle.add_css_class("dim-label")
            subtitle.add_css_class("caption")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            title_label = Gtk.Label(label=session.name)
            title_label.add_css_class("heading")
            box.append(title_label)
            box.append(subtitle)
            header.set_title_widget(box)

        stop = Gtk.Button(icon_name="process-stop-symbolic",
                          tooltip_text=tr("Close session"))
        stop.set_action_name("win.close-session")
        header.pack_end(stop)

        self.page = TerminalPage(title=session.name if session else "Terminal",
                                 kind=session.type.value if session else "local",
                                 session=session)
        self._page = self.page

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self.page)
        self.set_content(toolbar)

        self._install_actions()
        self._start(session, password)

    # ------------------------------------------------------------------
    def _install_actions(self) -> None:
        page = self._page

        def simple(name, fn):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_: fn())
            self.add_action(action)

        simple("copy", page.copy)
        simple("paste", page.paste)
        simple("find", page.find)
        simple("clear", page.clear)
        simple("zoom-in", lambda: page.zoom(1))
        simple("zoom-out", lambda: page.zoom(-1))
        simple("close-session", self._close_session)
        # Los aceleradores se registran a nivel de aplicación: GTK resuelve
        # las acciones «win.» contra la ventana activa.
        app = self.get_application()
        if app is not None:
            app.set_accels_for_action("win.copy", ["<Control><Shift>c"])
            app.set_accels_for_action("win.paste", ["<Control>v"])
            app.set_accels_for_action("win.find", ["<Control>f"])
            app.set_accels_for_action("win.clear", ["<Control>l"])
            app.set_accels_for_action("win.zoom-in", ["<Control>plus"])
            app.set_accels_for_action("win.zoom-out", ["<Control>minus"])

    # ------------------------------------------------------------------
    def _start(self, session: Session | None, password: str) -> None:
        if session is None:
            self._page.spawn_local()  # type: ignore[union-attr]
            return
        stype = session.type
        if stype == SessionType.SSH:
            self._page.spawn_ssh(session, password)  # type: ignore[union-attr]
        elif stype == SessionType.SERIAL:
            self._page.open_serial(session)  # type: ignore[union-attr]
        elif stype == SessionType.TELNET:
            self._page.spawn_telnet(session)  # type: ignore[union-attr]
        elif stype == SessionType.RSH:
            self._page.spawn_rsh(session)  # type: ignore[union-attr]
        elif stype == SessionType.MOSH:
            self._page.spawn_mosh(session)  # type: ignore[union-attr]
        else:
            self._page.spawn_local()  # type: ignore[union-attr]
        CONFIG.touch(session)

    # ------------------------------------------------------------------
    def _close_session(self) -> None:
        if self._page:
            self._page.close()
        self.close()

    def do_close_request(self) -> bool:  # type: ignore[override]
        if self._page:
            self._page.close()
        return False
