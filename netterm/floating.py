"""Ventanas flotantes internas.

En lugar de abrir una ventana del sistema, cada sesión se abre como una
**ventana flotante dentro de la propia interfaz**: tiene su barra de título,
se puede mover arrastrando, se puede maximizar, minimizar y cerrar, y varias
pueden coexistir superpuestas.

El gestor trabaja sobre un ``Gtk.Overlay`` en el que la zona principal es el
``Gtk.Notebook`` con los terminales locales.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, GObject, Gtk  # noqa: E402

from .config import CONFIG  # noqa: E402
from .i18n import tr  # noqa: E402
from .session import Session, SessionType  # noqa: E402
from .terminal import TerminalPage  # noqa: E402


class FloatingWindow(Gtk.Box):
    """Ventana interna flotante con una terminal."""

    __gsignals__ = {
        "closed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, manager: "FloatingManager", session: Session | None = None,
                 password: str = ""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.manager = manager
        self.session = session
        self._maximized = False
        self._restore_margins: tuple[int, int] | None = None

        self.add_css_class("netterm-floating")
        self.set_halign(Gtk.Align.START)
        self.set_valign(Gtk.Align.START)
        self.set_size_request(420, 260)

        # -- barra de título ---------------------------------------------
        self.titlebar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.titlebar.add_css_class("netterm-titlebar")
        self.titlebar.set_margin_top(3)
        self.titlebar.set_margin_bottom(3)
        self.titlebar.set_margin_start(6)
        self.titlebar.set_margin_end(4)

        self.icon = Gtk.Image.new_from_icon_name(
            "network-server-symbolic" if session else "utilities-terminal-symbolic")
        self.titlebar.append(self.icon)

        title_text = session.name if session else tr("Shell")
        self.title_label = Gtk.Label(label=title_text)
        self.title_label.set_ellipsize(3)
        self.title_label.set_xalign(0)
        self.titlebar.append(self.title_label)

        if session is not None:
            target = Gtk.Label(label=session.display_target())
            target.add_css_class("dim-label")
            target.add_css_class("caption")
            target.set_ellipsize(3)
            self.titlebar.append(target)

        self.minimize_btn = Gtk.Button(icon_name="minimize-symbolic",
                                       tooltip_text=tr("Minimize"))
        self.minimize_btn.add_css_class("flat")
        self.minimize_btn.connect("clicked", lambda *_: self.minimize())
        self.titlebar.append(self.minimize_btn)

        self.maximize_btn = Gtk.Button(icon_name="view-fullscreen-symbolic",
                                       tooltip_text=tr("Maximize"))
        self.maximize_btn.add_css_class("flat")
        self.maximize_btn.connect("clicked", lambda *_: self.toggle_maximize())
        self.titlebar.append(self.maximize_btn)

        self.close_btn = Gtk.Button(icon_name="window-close-symbolic",
                                    tooltip_text=tr("Close"))
        self.close_btn.add_css_class("flat")
        self.close_btn.connect("clicked", lambda *_: self.close_window())
        self.titlebar.append(self.close_btn)

        self.append(self.titlebar)

        # -- terminal ------------------------------------------------------
        self.page = TerminalPage(title=title_text,
                                 kind=session.type.value if session else "local",
                                 session=session)
        self.page.set_hexpand(True)
        self.page.set_vexpand(True)
        self.append(self.page)

        # -- arrastre -------------------------------------------------------
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag)
        self.titlebar.add_controller(drag)

        if session is not None:
            self._start(session, password)

    # ------------------------------------------------------------------
    def _start(self, session: Session, password: str) -> None:
        stype = session.type
        if stype == SessionType.SSH:
            self.page.spawn_ssh(session, password)
        elif stype == SessionType.SERIAL:
            self.page.open_serial(session)
        elif stype == SessionType.TELNET:
            self.page.spawn_telnet(session)
        elif stype == SessionType.RSH:
            self.page.spawn_rsh(session)
        elif stype == SessionType.MOSH:
            self.page.spawn_mosh(session)
        else:
            self.page.spawn_local()
        CONFIG.touch(session)

    # ------------------------------------------------------------------
    def _on_drag_begin(self, _gesture, _x: float, _y: float) -> None:
        self._origin = (self.get_margin_start(), self.get_margin_top())

    def _on_drag(self, _gesture, dx: float, dy: float) -> None:
        if self._maximized:
            return
        ox, oy = getattr(self, "_origin", (0, 0))
        self.set_margin_start(max(0, int(ox + dx)))
        self.set_margin_top(max(0, int(oy + dy)))

    # ------------------------------------------------------------------
    def minimize(self) -> None:
        self.set_visible(False)
        self.manager.minimized.append(self)
        self.manager.refresh_taskbar()

    def restore(self) -> None:
        self.set_visible(True)
        if self in self.manager.minimized:
            self.manager.minimized.remove(self)
        self.manager.refresh_taskbar()

    def toggle_maximize(self) -> None:
        self._maximized = not self._maximized
        if self._maximized:
            self._restore_margins = (self.get_margin_start(),
                                      self.get_margin_top())
            self.set_margin_start(0)
            self.set_margin_top(0)
            self.set_halign(Gtk.Align.FILL)
            self.set_valign(Gtk.Align.FILL)
            self.set_size_request(-1, -1)
        else:
            start, top = self._restore_margins or (40, 40)
            self.set_margin_start(start)
            self.set_margin_top(top)
            self.set_halign(Gtk.Align.START)
            self.set_valign(Gtk.Align.START)
            self.set_size_request(420, 260)
        self.manager.refresh_taskbar()

    def close_window(self) -> None:
        self.page.close()
        self.manager.close(self)
        self.emit("closed")

    # ------------------------------------------------------------------
    def focus(self) -> None:
        self.grab_focus()


class FloatingManager:
    """Gestiona las ventanas flotantes internas sobre un ``Gtk.Overlay``."""

    def __init__(self, overlay: Gtk.Overlay):
        self.overlay = overlay
        self.windows: list[FloatingWindow] = []
        self.minimized: list[FloatingWindow] = []
        self.taskbar = None

    # ------------------------------------------------------------------
    def open(self, session: Session | None, password: str = "") -> FloatingWindow:
        win = FloatingWindow(self, session, password)
        self.windows.append(win)
        self.overlay.add_overlay(win)
        self._cascade(win)
        win.show()
        self.refresh_taskbar()
        return win

    def _cascade(self, win: FloatingWindow) -> None:
        """Coloca la ventana en cascada para que no se solapen exactas."""
        index = len(self.windows) - 1
        step = 28
        win.set_margin_start(60 + (index % 6) * step)
        win.set_margin_top(50 + (index % 6) * step)

    def close(self, win: FloatingWindow) -> None:
        if win in self.windows:
            self.windows.remove(win)
        if win in self.minimized:
            self.minimized.remove(win)
        try:
            self.overlay.remove_overlay(win)
        except Exception:
            pass
        self.refresh_taskbar()

    # ------------------------------------------------------------------
    def build_taskbar(self) -> Gtk.Widget:
        """Barra de tareas con los botones de las ventanas abiertas."""
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        bar.set_margin_top(4)
        bar.set_margin_bottom(4)
        bar.set_margin_start(8)
        bar.set_margin_end(8)
        bar.add_css_class("netterm-taskbar")
        self.taskbar = bar
        self.refresh_taskbar()
        return bar

    def refresh_taskbar(self) -> None:
        if self.taskbar is None:
            return
        child = self.taskbar.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.taskbar.remove(child)
            child = nxt

        for win in list(self.windows):
            label = win.session.name if win.session else tr("Shell")
            btn = Gtk.Button(label=label)
            btn.add_css_class("flat")
            if win in self.minimized:
                btn.add_css_class("dim-label")
            btn.connect("clicked", lambda *_, w=win: self._activate(w))
            self.taskbar.append(btn)

        if self.windows:
            tile = Gtk.Button(label=tr("Tile"))
            tile.add_css_class("flat")
            tile.connect("clicked", lambda *_: self.tile())
            self.taskbar.append(tile)

    def _activate(self, win: FloatingWindow) -> None:
        if win in self.minimized:
            win.restore()
        else:
            for other in self.windows:
                if other is not win:
                    other.minimize()
            win.restore()

    # ------------------------------------------------------------------
    def tile(self) -> None:
        """Distribuye las ventanas flotantes en mosaico."""
        visibles = [w for w in self.windows if w not in self.minimized]
        if not visibles:
            return
        columns = 2 if len(visibles) > 1 else 1
        rows = (len(visibles) + columns - 1) // columns
        for index, win in enumerate(visibles):
            row, col = divmod(index, columns)
            win.set_halign(Gtk.Align.START)
            win.set_valign(Gtk.Align.START)
            win.set_margin_start(col * 420)
            win.set_margin_top(row * 280)
            win.set_size_request(400, 260)
            win._maximized = False
