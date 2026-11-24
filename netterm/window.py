"""Ventana principal de NetTerm.

Reproduce la disposición de MobaXterm: barra de menús, barra de pestañas con
terminales, panel lateral con pestañas verticales (Sesiones / Herramientas /
Macros / SFTP) y barra de estado inferior.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .config import APP_NAME, CONFIG  # noqa: E402
from .i18n import tr  # noqa: E402
from .session import Session, SessionType  # noqa: E402
from .terminal import TerminalPage  # noqa: E402


class MainWindow(Adw.ApplicationWindow):
    """Ventana principal."""

    def __init__(self, application=None, **kwargs):
        super().__init__(application=application, **kwargs)
        self.set_title(APP_NAME)
        self.set_default_size(1100, 720)
        self.set_size_request(880, 520)

        self.pages: list[TerminalPage] = []
        self._session_windows: list = []
        self._quitting = False
        self.multi_exec = False
        self._paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self._notebook = Gtk.Notebook()
        self._notebook.set_tab_pos(Gtk.PositionType.TOP)
        self._notebook.set_show_border(False)
        self._notebook.set_scrollable(True)
        self._notebook.connect("switch-page", self._on_switch_page)
        self._notebook.connect("page-reordered", self._on_reorder)

        # -- panel lateral ----------------------------------------------
        from .sidebar import Sidebar

        self.sidebar = Sidebar(self)
        self._paned.set_start_child(self.sidebar)
        self._paned.set_end_child(self._notebook)
        self._paned.set_position(int(CONFIG.get("sidebar_width", 280)))
        self._paned.set_resize_start_child(False)
        self._paned.set_shrink_start_child(False)

        # -- overlay con las ventanas flotantes internas -----------------
        # Cada sesión remota se abre como una ventana flotante DENTRO de esta
        # misma interfaz, al estilo del gestor de ventanas del navegador wave.
        from .floating import FloatingManager

        self._overlay = Gtk.Overlay()
        self._overlay.set_child(self._paned)
        self._floating = FloatingManager(self._overlay)
        self._taskbar = self._floating.build_taskbar()

        # -- barra de estado ---------------------------------------------
        self.status_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.status_bar.set_margin_top(3)
        self.status_bar.set_margin_bottom(3)
        self.status_bar.set_margin_start(10)
        self.status_bar.set_margin_end(10)
        self.status_iface = Gtk.Label(label="")
        self.status_iface.add_css_class("dim-label")
        self.status_iface.add_css_class("caption")
        self.status_session = Gtk.Label(label="")
        self.status_session.add_css_class("dim-label")
        self.status_session.add_css_class("caption")
        self.status_bar.append(self.status_iface)
        self.status_bar.append(self.status_session)
        self.status_revealer = Gtk.Revealer()
        self.status_revealer.set_reveal_child(True)
        self.status_revealer.set_child(self.status_bar)

        # -- toolbar ------------------------------------------------------
        self.toolbar = Adw.ToolbarView()
        self.toolbar.add_top_bar(self._build_header())
        self._content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._content_box.append(self._overlay)
        self._content_box.append(self._taskbar)
        self.toolbar.set_content(self._content_box)
        self.toolbar.add_bottom_bar(self.status_revealer)

        self._install_window_actions()
        self._build_menubar()
        self._toast_overlay = Adw.ToastOverlay()
        self._toast_overlay.set_child(self._build_body())
        self.set_content(self._toast_overlay)

        self._apply_css()

        self.sidebar.connect("session-activated", self._on_session_activated)
        self.sidebar.connect("status-message", self._on_status_message)
        self.sidebar.connect("interfaces-changed", lambda *_: self.refresh_interfaces())

        self.connect("close-request", self._on_close_request)
        GLib.timeout_add(1500, self._poll_interfaces)
        self.refresh_interfaces()
        # MobaXterm abre una terminal local al arrancar.
        self._open_local_terminal()

    def _open_local_terminal(self) -> None:
        page = TerminalPage(title=tr("Shell"), kind="local")
        page.spawn_local()
        self.add_page(page)

    # ------------------------------------------------------------------
    # Cabecera
    # ------------------------------------------------------------------
    def _build_header(self) -> Adw.HeaderBar:
        header = Adw.HeaderBar()

        # -- menú principal (hamburguesa) --------------------------------
        self.menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic",
                                          tooltip_text=tr("Menú principal"))
        self.menu_button.set_menu_model(self._build_menu())
        header.pack_start(self.menu_button)

        # -- botón de conexión rápida -----------------------------------
        self.quick = Gtk.SearchEntry(placeholder_text=tr("Quick connect…"))
        self.quick.set_hexpand(False)
        self.quick.set_width_chars(24)
        self.quick.set_tooltip_text(tr("Conexión rápida a un host"))
        self.quick.connect("activate", lambda e: self._quick_connect(e.get_text()))
        header.pack_start(self.quick)

        # -- botón de apertura de sesión (estilo OpenCode) ---------------
        self.new_session_btn = Gtk.Button(icon_name="list-add-symbolic",
                                          tooltip_text=tr("Open a session"))
        self.new_session_btn.connect("clicked", lambda *_: self._show_chooser())
        header.pack_end(self.new_session_btn)

        # -- pestañas de terminal ----------------------------------------
        self.tab_label = Gtk.Box()
        header.set_title_widget(self.tab_label)
        header.set_title_widget(None)

        # -- botones de la derecha ---------------------------------------
        add_btn = Gtk.Button(icon_name="tab-new-symbolic",
                             tooltip_text=tr("Nueva terminal local (Ctrl+T)"))
        add_btn.set_action_name("app.new-local")
        header.pack_end(add_btn)

        ssh_btn = Gtk.Button(
            icon_name="network-server-symbolic",
            tooltip_text=tr("Nueva sesión SSH (Ctrl+Shift+T)"))
        ssh_btn.set_action_name("app.new-ssh")
        header.pack_end(ssh_btn)

        split_btn = Gtk.Button(icon_name="view-dual-symbolic",
                               tooltip_text=tr("Dividir vista"))
        split_btn.set_action_name("app.split")
        header.pack_end(split_btn)

        multi_btn = Gtk.Button(icon_name="preferences-system-run-symbolic",
                               tooltip_text=tr("Modo multi-ejecución"))
        multi_btn.set_action_name("app.multi-exec")
        header.pack_end(multi_btn)

        return header

    # ------------------------------------------------------------------
    # Menú principal (Terminal, Sessions, View, X server, Tools, ...)
    # ------------------------------------------------------------------
    def _build_menu(self) -> Gio.Menu:
        menu = Gio.Menu()

        terminal = Gio.Menu()
        terminal.append(tr("Terminal local"), "app.new-local")
        terminal.append(tr("Sesión SSH…"), "app.new-ssh")
        terminal.append(tr("Consola serie…"), "app.new-serial")
        terminal.append(tr("SFTP…"), "app.new-sftp")
        terminal.append(tr("Telnet…"), "app.new-telnet")
        terminal.append(tr("Mosh…"), "app.new-mosh")
        terminal.append(tr("Separador"), None)
        terminal.append(tr("Cerrar pestaña"), "app.close-tab")
        terminal.append(tr("Dividir vista"), "app.split")
        terminal.append(tr("Multi-ejecución"), "app.multi-exec")
        menu.append_section(None, terminal)

        sessions = Gio.Menu()
        sessions.append(tr("Nueva sesión…"), "app.new-ssh")
        sessions.append(tr("Importar desde ~/.ssh/config"),
                        "win.import-ssh-config")
        sessions.append(tr("Importar sesiones de MobaXterm"),
                        "win.import-mobaxterm")
        sessions.append(tr("Separador"), None)
        sessions.append(tr("Abrir carpeta SFTP"), "app.new-sftp")
        sessions.append(tr("Gestor de túneles SSH"), "win.tunnels")
        menu.append_section(None, sessions)

        view = Gio.Menu()
        view.append(tr("Buscar…"), "app.find")
        view.append(tr("Copiar"), "app.copy")
        view.append(tr("Pegar"), "app.paste")
        view.append(tr("Limpiar terminal"), "app.clear")
        view.append(tr("Separador"), None)
        view.append(tr("Acercar"), "app.zoom-in")
        view.append(tr("Alejar"), "app.zoom-out")
        view.append(tr("Separador"), None)
        view.append(tr("Barra lateral"), "win.toggle-sidebar")
        view.append(tr("Pantalla completa"), "win.fullscreen")
        menu.append_section(None, view)

        xserver = Gio.Menu()
        xserver.append(tr("Información del servidor X"), "win.x-server-info")
        xserver.append(tr("Reiniciar servidor X"), "win.x-server-restart")
        xserver.append(tr("Separador"), None)
        xserver.append(tr("Abrir X11 forwarding"), "win.x-forward-toggle")
        menu.append_section(None, xserver)

        tools = Gio.Menu()
        tools.append(tr("Panel de red"), "win.show-tools")
        tools.append(tr("Interfaces de red"), "win.show-interfaces")
        tools.append(tr("Escáner de puertos"), "win.show-scanner")
        tools.append(tr("Separador"), None)
        tools.append(tr("Servidores embebidos"), "win.show-servers")
        tools.append(tr("Gestor de paquetes"), "win.show-packages")
        tools.append(tr("Separador"), None)
        tools.append(tr("Calculadora de CRC"), "win.show-crc")
        menu.append_section(None, tools)

        games = Gio.Menu()
        games.append(tr("glxgears (demo X11)"), "win.glxgears")
        games.append(tr("Terminal con eco remoto"), "win.echo-demo")
        menu.append_section(None, games)

        settings = Gio.Menu()
        settings.append(tr("Preferencias"), "app.preferences")
        settings.append(tr("Personalizar (banner/logo)"), "win.customize")
        settings.append(tr("Contraseña maestra"), "win.master-password")
        menu.append_section(None, settings)

        macros = Gio.Menu()
        macros.append(tr("Grabar macro"), "win.macro-record")
        macros.append(tr("Reproducir macro"), "win.macro-play")
        macros.append(tr("Separador"), None)
        macros.append(tr("Administrar macros"), "win.macro-manager")
        menu.append_section(None, macros)

        help = Gio.Menu()
        help.append(tr("Documentación"), "win.docs")
        help.append(tr("Acerca de"), "app.about")
        menu.append_section(None, help)

        return menu

    # ------------------------------------------------------------------
    def _build_menubar(self) -> None:
        """Barra de menús clásica al estilo MobaXterm (arriba del todo)."""
        model = Gio.Menu()
        model.append_submenu(tr("Terminal"), self._menu_terminal())
        model.append_submenu(tr("Sessions"), self._menu_sessions())
        model.append_submenu(tr("View"), self._menu_view())
        model.append_submenu(tr("X server"), self._menu_xserver())
        model.append_submenu(tr("Tools"), self._menu_tools())
        model.append_submenu(tr("Games"), self._menu_games())
        model.append_submenu(tr("Settings"), self._menu_settings())
        model.append_submenu(tr("Macros"), self._menu_macros())
        model.append_submenu(tr("Help"), self._menu_help())

        bar = Gtk.PopoverMenuBar.new_from_model(model)
        self.menubar = bar

    def _build_body(self) -> Gtk.Box:
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.append(self.menubar)
        body.append(self.toolbar)
        return body

    # -- modelos de menú de la menubar ---------------------------------
    def _menu_terminal(self) -> Gio.Menu:
        m = Gio.Menu()
        m.append(tr("Nuevo terminal local"), "app.new-local")
        m.append(tr("Nueva sesión SSH…"), "app.new-ssh")
        m.append(tr("Consola serie…"), "app.new-serial")
        m.append(tr("SFTP…"), "app.new-sftp")
        m.append(tr("Telnet…"), "app.new-telnet")
        m.append(tr("Separador"), None)
        m.append(tr("Cerrar pestaña"), "app.close-tab")
        m.append(tr("Separador"), None)
        m.append(tr("Salir"), "app.quit")
        return m

    def _menu_sessions(self) -> Gio.Menu:
        m = Gio.Menu()
        m.append(tr("Nueva sesión…"), "app.new-ssh")
        m.append(tr("Importar de ~/.ssh/config"), "win.import-ssh-config")
        m.append(tr("Importar de MobaXterm"), "win.import-mobaxterm")
        m.append(tr("Separador"), None)
        m.append(tr("Gestor de túneles SSH"), "win.tunnels")
        m.append(tr("Sincronización de archivos (SFTP)"), "app.new-sftp")
        return m

    def _menu_view(self) -> Gio.Menu:
        m = Gio.Menu()
        m.append(tr("Barra lateral"), "win.toggle-sidebar")
        m.append(tr("Pantalla completa"), "win.fullscreen")
        m.append(tr("Separador"), None)
        m.append(tr("Buscar…"), "app.find")
        m.append(tr("Limpiar"), "app.clear")
        return m

    def _menu_xserver(self) -> Gio.Menu:
        m = Gio.Menu()
        m.append(tr("Información del servidor X"), "win.x-server-info")
        m.append(tr("Reiniciar servidor X"), "win.x-server-restart")
        return m

    def _menu_tools(self) -> Gio.Menu:
        m = Gio.Menu()
        m.append(tr("Panel de red"), "win.show-tools")
        m.append(tr("Interfaces"), "win.show-interfaces")
        m.append(tr("Escáner"), "win.show-scanner")
        m.append(tr("Servidores embebidos"), "win.show-servers")
        m.append(tr("Paquetes"), "win.show-packages")
        return m

    def _menu_games(self) -> Gio.Menu:
        m = Gio.Menu()
        m.append("glxgears", "win.glxgears")
        m.append(tr("Echo remoto"), "win.echo-demo")
        return m

    def _menu_settings(self) -> Gio.Menu:
        m = Gio.Menu()
        m.append(tr("Preferencias"), "app.preferences")
        m.append(tr("Personalizar"), "win.customize")
        m.append(tr("Contraseña maestra"), "win.master-password")
        return m

    def _menu_macros(self) -> Gio.Menu:
        m = Gio.Menu()
        m.append(tr("Grabar"), "win.macro-record")
        m.append(tr("Reproducir"), "win.macro-play")
        m.append(tr("Administrar"), "win.macro-manager")
        return m

    def _menu_help(self) -> Gio.Menu:
        m = Gio.Menu()
        m.append(tr("Documentación"), "win.docs")
        m.append(tr("Acerca de"), "app.about")
        return m

    # ------------------------------------------------------------------
    def _apply_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(b"""
        .netterm-sidebar { background: alpha(currentColor, 0.04); }
        .netterm-status { border-top: 1px solid alpha(currentColor, 0.12); }
        .netterm-tab-title { font-weight: 500; }

        /* Ventanas flotantes internas */
        .netterm-floating {
            background: @theme_bg_color;
            border: 1px solid alpha(currentColor, 0.25);
            border-radius: 8px;
            box-shadow: 0 4px 18px alpha(black, 0.45);
        }
        .netterm-titlebar {
            background: alpha(currentColor, 0.10);
            border-bottom: 1px solid alpha(currentColor, 0.18);
            border-radius: 8px;
        }
        .netterm-taskbar {
            border-top: 1px solid alpha(currentColor, 0.12);
            background: alpha(currentColor, 0.04);
        }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    # ------------------------------------------------------------------
    # Terminales
    # ------------------------------------------------------------------
    def add_page(self, page: TerminalPage) -> TerminalPage:
        self.pages.append(page)
        page.connect("closed", self._on_page_closed)
        label = self._make_tab_label(page)
        page._tab_label = label  # type: ignore[attr-defined]
        page.connect("title-changed",
                     lambda p, t, lbl=label: self._update_tab_label(lbl, p))
        self._notebook.append_page(page, label)
        self._notebook.set_current_page(self._notebook.get_n_pages() - 1)
        self._update_status()
        return page

    def _make_tab_label(self, page: TerminalPage) -> Gtk.Widget:
        """Pestaña interna: icono del protocolo + nombre de la sesión."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_margin_top(2)
        box.set_margin_bottom(2)
        session = page.session
        icon = Gtk.Image.new_from_icon_name(
            session.type.icon if session else "utilities-terminal-symbolic")
        box.append(icon)
        label = Gtk.Label(label=page.title)
        label.set_ellipsize(3)
        box.append(label)
        return box

    def _update_tab_label(self, widget: Gtk.Widget, page: TerminalPage) -> None:
        child = widget.get_first_child()
        if child is None:
            return
        label = child.get_next_sibling()
        if label is not None:
            label.set_text(page.title)

    def current_page(self) -> TerminalPage | None:
        idx = self._notebook.get_current_page()
        if idx < 0:
            return None
        return self.pages[idx] if idx < len(self.pages) else None

    def close_current_tab(self) -> None:
        page = self.current_page()
        if page:
            page.close()

    def _on_page_closed(self, page: TerminalPage) -> None:
        if page in self.pages:
            self.pages.remove(page)
            try:
                self._notebook.remove(page)
            except Exception:
                pass
        self._update_status()
        if not self.pages and not self._quitting:
            # La ventana no puede quedarse sin terminales: si se cierra el
            # último, se abre un shell local nuevo. Si no, Gtk.Application
            # cerraría la ventana y la aplicación moriría.
            self._open_local_terminal()

    def _on_switch_page(self, *_args) -> None:
        self._update_status()

    def _on_reorder(self, *_args) -> None:
        order = []
        for i in range(self._notebook.get_n_pages()):
            lbl = self._notebook.get_tab_label_text(i)
            order.append(lbl)
        self.pages.sort(key=lambda p: order.index(p.title)
                        if p.title in order else 999)
        self._update_status()

    def _update_status(self) -> None:
        page = self.current_page()
        if page and page.session:
            self.status_session.set_text(page.subtitle or page.session.name)
        else:
            self.status_session.set_text("")

    # ------------------------------------------------------------------
    # Multi-ejecución
    # ------------------------------------------------------------------
    def toggle_multi_exec(self) -> None:
        from .multiexec import MultiExecController

        self.multi_exec = not self.multi_exec
        if self.multi_exec:
            if not hasattr(self, "_multiexec"):
                self._multiexec = MultiExecController(self)
            self._multiexec.enable()
            self.status_session.set_text(tr("modo multi-ejecución activo"))
        else:
            if hasattr(self, "_multiexec"):
                self._multiexec.disable()
            self._update_status()

    # ------------------------------------------------------------------
    # Diálogo de nueva sesión
    # ------------------------------------------------------------------
    def new_session(self, kind: str) -> None:
        from .dialogs import SessionDialog

        dlg = SessionDialog(self, kind=kind)
        dlg.connect("session-created", self._on_session_created)
        dlg.present()

    def _on_session_created(self, _dlg, session: Session, password: str) -> None:
        CONFIG.upsert_session(session)
        self.sidebar.refresh()
        self.open_session(session, password)

    def open_session(self, session: Session, password: str = "") -> TerminalPage:
        """Abre una sesión.

        Por defecto la sesión se abre como **pestaña interna** de esta misma
        interfaz (con su icono y su nombre), igual que las pestañas de sesión
        del propio editor. Las preferencias permiten alternar entre ventanas
        flotantes internas o ventanas del sistema.
        """
        if self._use_new_window(session):
            self._open_in_new_window(session, password)
            return self.current_page() or TerminalPage(title=session.name)

        page = TerminalPage(title=session.name, kind=session.type.value,
                            session=session)
        stype = session.type
        if stype == SessionType.SSH:
            page.spawn_ssh(session, password)
        elif stype == SessionType.SERIAL:
            page.open_serial(session)
        elif stype == SessionType.TELNET:
            page.spawn_telnet(session)
        elif stype == SessionType.RSH:
            page.spawn_rsh(session)
        elif stype == SessionType.MOSH:
            page.spawn_mosh(session)
        elif stype == SessionType.SHELL:
            page.spawn_local()
        elif stype in (SessionType.RDP, SessionType.VNC, SessionType.XDMCPC,
                       SessionType.BROWSER, SessionType.FILE):
            self._open_graphical(session)
            return page
        else:
            page.spawn_local()
        CONFIG.touch(session)
        return self.add_page(page)

    def _use_new_window(self, session: Session) -> bool:
        """¿Cómo se abre esta sesión?

        * ``tabs``    -> pestaña interna en esta misma ventana (por defecto,
                         como las pestañas de sesión del propio editor)
        * ``floating``-> ventana flotante dentro de la interfaz
        * ``window``  -> ventana del sistema
        """
        mode = CONFIG.get("session_presentation", "tabs")
        if mode == "tabs":
            return False
        if mode == "floating":
            return session.type != SessionType.SHELL
        return session.type != SessionType.SHELL

    def _open_in_new_window(self, session: Session, password: str = "") -> None:
        """Abre la sesión como ventana flotante dentro de esta misma interfaz."""
        win = self._floating.open(session, password)
        self._toast(tr("Session «{name}» opened in a new window",
                       name=session.name))
        return win

    def _forget_window(self, win) -> None:
        if win in self._session_windows:
            self._session_windows.remove(win)

    def _open_graphical(self, session: Session) -> None:
        from . import remote

        stype = session.type
        if stype == SessionType.RDP:
            cmd = remote.rdp_command(session)
        elif stype == SessionType.VNC:
            cmd = remote.vnc_command(session)
        elif stype == SessionType.XDMCPC:
            cmd = remote.xdmcp_command(session)
        elif stype == SessionType.BROWSER:
            cmd = remote.browser_command(session)
        else:
            cmd = remote.sftp_command(session)
        ok, msg = remote.launch(cmd)
        if not ok:
            self._toast(msg, "error")

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Selector de sesiones (estilo OpenCode)
    # ------------------------------------------------------------------
    def _show_chooser(self) -> None:
        """Popover para abrir una sesión: guardadas, recientes o nuevas."""
        popover = Gtk.Popover()
        popover.set_parent(self.new_session_btn)
        popover.set_has_arrow(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)

        search = Gtk.SearchEntry(placeholder_text=tr("Search sessions…"))
        search.connect("activate", lambda e: self._chooser_quick(search, popover))
        box.append(search)

        scroller = Gtk.ScrolledWindow()
        scroller.set_min_content_height(220)
        scroller.set_min_content_width(320)
        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.add_css_class("navigation-sidebar")

        sessions = sorted(CONFIG.sessions, key=lambda s: s.group)
        for session in sessions:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.set_margin_top(3)
            row.set_margin_bottom(3)
            icon = Gtk.Image.new_from_icon_name(session.type.icon)
            row.append(icon)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            name = Gtk.Label(label=session.name)
            name.set_xalign(0)
            target = Gtk.Label(label=session.display_target())
            target.add_css_class("dim-label")
            target.add_css_class("caption")
            target.set_xalign(0)
            text.append(name)
            text.append(target)
            row.append(text)
            btn = Gtk.Button(icon_name="go-next-symbolic",
                             tooltip_text=tr("Open"))
            btn.add_css_class("flat")
            btn.connect("clicked",
                        lambda *_, s=session, p=popover: self._open_from_chooser(s, p))
            row.append(btn)
            listbox.append(row)

        if not sessions:
            empty = Gtk.Label(label=tr("No saved sessions"))
            empty.add_css_class("dim-label")
            empty.set_margin_top(12)
            listbox.append(empty)

        scroller.set_child(listbox)
        box.append(scroller)

        box.append(Gtk.Separator())
        for label, kind in ((tr("New SSH session…"), "ssh"),
                            (tr("Serial console…"), "serial"),
                            (tr("SFTP…"), "sftp"),
                            (tr("Local shell"), "shell")):
            btn = Gtk.Button(label=label)
            btn.set_halign(Gtk.Align.START)
            btn.connect("clicked",
                        lambda *_, k=kind, p=popover: self._new_from_chooser(k, p))
            box.append(btn)

        popover.set_child(box)
        popover.show()

    def _open_from_chooser(self, session: Session, popover) -> None:
        popover.popdown()
        self.open_session(session)

    def _new_from_chooser(self, kind: str, popover) -> None:
        popover.popdown()
        self.new_session(kind)

    def _chooser_quick(self, entry: Gtk.SearchEntry, popover) -> None:
        text = (entry.get_text() or "").strip()
        if not text:
            return
        popover.popdown()
        self._quick_connect(text)

    # ------------------------------------------------------------------
    def _on_session_activated(self, _sidebar, session: Session) -> None:
        if session.type in (SessionType.RDP, SessionType.VNC,
                            SessionType.XDMCPC, SessionType.BROWSER):
            self.open_session(session)
            return
        self.open_session(session)

    def _on_status_message(self, _sidebar, message: str) -> None:
        self._toast(message)

    def _toast(self, message: str, kind: str = "info") -> None:
        toast = Adw.Toast.new(message)
        toast.set_timeout(3)
        overlay = self._find_toast_overlay()
        if overlay:
            overlay.add_toast(toast)

    def _find_toast_overlay(self):
        return getattr(self, "_toast_overlay", None)

    # ------------------------------------------------------------------
    def focus_quick_connect(self) -> None:
        self.quick.grab_focus()

    def _quick_connect(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        host = text
        port = 22
        user = ""
        if "@" in host:
            user, _, host = host.partition("@")
        if ":" in host:
            host, _, p = host.rpartition(":")
            if p.isdigit():
                port = int(p)
        session = Session(id=f"quick-{uuid.uuid4().hex[:8]}", name=host,
                          type=SessionType.SSH, host=host, port=port,
                          username=user, group=tr("Conexión rápida"))
        CONFIG.add_recent_host(host, user, port)
        self.open_session(session)

    # ------------------------------------------------------------------
    def refresh_interfaces(self) -> None:
        from . import netif

        try:
            iface = netif.default_interface()
            if iface:
                found = netif.find_interface(iface)
                if found:
                    self.status_iface.set_text(
                        f"{found.name} ({found.kind}) {found.primary_ipv4}")
                else:
                    self.status_iface.set_text(iface)
            else:
                self.status_iface.set_text(tr("sin red"))
        except Exception:
            self.status_iface.set_text("")

    def _poll_interfaces(self) -> bool:
        self.refresh_interfaces()
        return True

    # ------------------------------------------------------------------
    def split_view(self) -> None:
        page = self.current_page()
        if not page:
            return
        pane = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        pane.set_position(500)
        idx = self._notebook.get_current_page()
        self._notebook.remove_page(idx)
        pane.set_start_child(page)
        new_page = TerminalPage(title=tr("Terminal"))
        new_page.spawn_local()
        pane.set_end_child(new_page)
        self.add_page_to_notebook(pane)

    def add_page_to_notebook(self, widget: Gtk.Widget) -> None:
        label = Gtk.Label(label=tr("Dividido"))
        self._notebook.append_page(widget, label)

    # ------------------------------------------------------------------
    def show_preferences(self) -> None:
        from .prefs import PreferencesWindow

        prefs = PreferencesWindow(self)
        prefs.present()

    def confirm_quit(self) -> None:
        self._quitting = True
        self.close()

    def snapshot_to_png(self, path: str) -> None:
        """Renderiza la ventana a un PNG (herramienta de depuración)."""
        paintable = Gtk.WidgetPaintable.new(self)
        snapshot = Gtk.Snapshot()
        width = self.get_width()
        height = self.get_height()
        if width <= 0 or height <= 0:
            width, height = 1100, 720
        paintable.snapshot(snapshot, width, height)
        snapshot.save(path, "png", -1)

    def _on_close_request(self, *_args) -> bool:
        for page in list(self.pages):
            page.close()
        self.pages.clear()
        return False

    # -- atajos de la ventana -------------------------------------------
    def _install_window_actions(self) -> None:
        def act(name, cb):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", cb)
            self.add_action(a)

        act("toggle-sidebar", lambda *_: self._paned.set_show_start_child(
            not self._paned.get_show_start_child()))
        act("show-sessions", lambda *_: self.sidebar.show_panel("sessions"))
        act("show-macros", lambda *_: self.sidebar.show_panel("macros"))
        act("show-sftp", lambda *_: self.sidebar.show_panel("sftp"))
        act("fullscreen", lambda *_: self.set_fullscreen(
            not self.is_fullscreen()))
        act("import-ssh-config", lambda *_: self._import_ssh_config())
        act("import-mobaxterm", lambda *_: self._import_mobaxterm())
        act("tunnels", lambda *_: self.sidebar.show_panel("tools", "tunnels"))
        act("show-tools", lambda *_: self.sidebar.show_panel("tools", "net"))
        act("show-interfaces", lambda *_: self.sidebar.show_panel("tools", "interfaces"))
        act("show-scanner", lambda *_: self.sidebar.show_panel("tools", "scan"))
        act("show-servers", lambda *_: self.sidebar.show_panel("tools", "servers"))
        act("show-packages", lambda *_: self.sidebar.show_panel("tools", "packages"))
        act("show-crc", lambda *_: self.sidebar.show_panel("tools", "crc"))
        act("x-server-info", lambda *_: self._x_server_info())
        act("x-server-restart", lambda *_: self._x_server_restart())
        act("x-forward-toggle", lambda *_: self._toggle_x11())
        act("glxgears", lambda *_: self._glxgears())
        act("echo-demo", lambda *_: self._echo_demo())
        act("customize", lambda *_: self.sidebar.show_panel("sessions", "customizer"))
        act("master-password", lambda *_: self.sidebar.show_panel("sessions", "vault"))
        act("macro-record", lambda *_: self._macro_record())
        act("macro-play", lambda *_: self._macro_play())
        act("macro-manager", lambda *_: self.sidebar.show_panel("macros"))
        act("docs", lambda *_: self._open_docs())
        act("refresh-interfaces", lambda *_: self.refresh_interfaces())

    # -- acciones auxiliares --------------------------------------------
    def _import_ssh_config(self) -> None:
        from . import sshconfig

        sessions = sshconfig.import_sessions()
        if not sessions:
            self._toast(tr("No se encontraron hosts en ~/.ssh/config"))
            return
        for s in sessions:
            CONFIG.upsert_session(s)
        self.sidebar.refresh()
        self._toast(tr("{n} sesiones importadas de ~/.ssh/config",
                       n=len(sessions)))

    def _import_mobaxterm(self) -> None:
        """Importa las sesiones guardadas por MobaXterm (archivo .ini)."""
        from .mobaxterm import import_mobaxterm_sessions

        found = import_mobaxterm_sessions()
        for s in found:
            CONFIG.upsert_session(s)
        self.sidebar.refresh()
        self._toast(tr("{n} sesiones importadas de MobaXterm", n=len(found)))

    def _x_server_info(self) -> None:
        info = []
        info.append(tr("Servidor X en Linux: Xwayland / Xorg nativo "
                       "del sistema"))
        info.append(f"DISPLAY={os.environ.get('DISPLAY', '(sin definir)')}")
        info.append(f"WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY', '(sin definir)')}")
        info.append(f"XAUTHORITY={os.environ.get('XAUTHORITY', '(sin definir)')}")
        info.append("")
        info.append(tr("Extensiones X disponibles en tu sistema:"))
        for line in os.popen("xdpyinfo 2>/dev/null | sed -n '/number of extensions/,/^default screen/p'"
                             ).read().splitlines():
            if line.strip():
                info.append("  " + line.strip())
        dlg = Adw.MessageDialog(transient_for=self, heading=tr("Servidor X"),
                                body="\n".join(info))
        dlg.add_response("cerrar", tr("Cerrar"))
        dlg.present()

    def _x_server_restart(self) -> None:
        self._toast(tr("En Linux el servidor X lo gestiona la sesión gráfica "
                       "(Xwayland). No hay un X embebido que reiniciar."))

    def _toggle_x11(self) -> None:
        cfg = CONFIG.get("x11_forward", True)
        CONFIG.set("x11_forward", not cfg)
        CONFIG.save_settings()
        self._toast(tr("X11-forwarding {estado}",
                       estado="activado" if not cfg else "desactivado"))

    def _glxgears(self) -> None:
        import shutil
        import subprocess

        exe = shutil.which("glxgears")
        if not exe:
            self._toast(tr("glxgears no está instalado "
                           "(dnf install glx-utils)"), "error")
            return
        env = dict(os.environ)
        env["LIBGL_ALWAYS_SOFTWARE"] = "1"
        subprocess.Popen([exe], env=env)

    def _echo_demo(self) -> None:
        page = TerminalPage(title=tr("Eco remoto"))
        page.spawn_local()
        self.add_page(page)

    def _macro_record(self) -> None:
        from . import macro

        page = self.current_page()
        if not page:
            return
        if macro.recorder().is_recording():
            macro.recorder().stop()
            self._toast(tr("Macro detenido"))
            self.sidebar.refresh()
        else:
            macro.recorder().start(page)
            self._toast(tr("Grabando macro…"))

    def _macro_play(self) -> None:
        from . import macro

        macros = macro.list_macros()
        if not macros:
            self._toast(tr("No hay macros grabadas"))
            return
        page = self.current_page()
        if page:
            macro.play(page, macros[-1])

    def _open_docs(self) -> None:
        import subprocess
        import webbrowser

        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "README.md")
        if os.path.exists(path):
            webbrowser.open(f"file://{path}")
        else:
            webbrowser.open("https://github.com/")
