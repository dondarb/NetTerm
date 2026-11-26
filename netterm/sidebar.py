"""Panel lateral de NetTerm.

Reproduce la columna de pestañas verticales de MobaXterm (Sesiones, Herramientas,
Macros, SFTP) con el árbol de sesiones agrupado, la búsqueda rápida y los
paneles de herramientas.
"""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GObject, Gio, GLib, Gtk  # noqa: E402

from .config import CONFIG  # noqa: E402
from .i18n import tr  # noqa: E402
from .session import Session, SessionType  # noqa: E402


class Sidebar(Gtk.Box):
    """Columna lateral con pestañas verticales."""

    __gsignals__ = {
        "session-activated": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "status-message": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "interfaces-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, window=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.window = window
        self._toggle_buttons: dict[str, Gtk.ToggleButton] = {}
        self._panels: dict[str, Gtk.Widget] = {}

        self.set_size_request(240, -1)

        # -- tira de pestañas verticales -------------------------------
        strip = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        strip.set_margin_top(6)
        strip.set_margin_bottom(6)
        strip.set_margin_start(4)
        strip.set_margin_end(2)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        for key, label, icon, tip in (
            ("sessions", tr("Sesiones"), "computer-symbolic",
             tr("Sesiones guardadas")),
            ("tools", tr("Herramientas"), "applications-utilities-symbolic",
             tr("Herramientas de red")),
            ("macros", tr("Macros"), "document-edit-symbolic",
             tr("Macros grabadas")),
            ("sftp", tr("SFTP"), "folder-publish-symbolic",
             tr("Explorador SFTP")),
        ):
            btn = Gtk.ToggleButton(icon_name=icon, tooltip_text=tip)
            btn.set_active(key == "sessions")
            btn.add_css_class("flat")
            btn.connect("toggled", self._on_toggle, key)
            strip.append(btn)
            self._toggle_buttons[key] = btn

        self.append(strip)
        self.append(self.stack)

        # -- panel de sesiones ------------------------------------------
        self._build_sessions_panel()
        self._build_tools_panel()
        self._build_macros_panel()
        self._build_sftp_panel()

    def _on_toggle(self, button: Gtk.ToggleButton, key: str) -> None:
        """Cambia la pestaña vertical activa."""
        if button.get_active():
            self.stack.set_visible_child_name(key)
            for other, btn in self._toggle_buttons.items():
                if other != key:
                    btn.set_active(False)
        elif self.stack.get_visible_child_name() == key:
            # No se puede dejar la columna sin ninguna pestaña activa.
            for other, btn in self._toggle_buttons.items():
                if other != key:
                    btn.set_active(True)
                    self.stack.set_visible_child_name(other)
                    break

    # ------------------------------------------------------------------
    # Panel de sesiones
    # ------------------------------------------------------------------
    def _build_sessions_panel(self) -> None:
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        panel.set_margin_top(4)
        panel.set_margin_bottom(4)
        panel.set_margin_start(2)
        panel.set_margin_end(6)

        # Búsqueda / filtro
        self.search = Gtk.SearchEntry(placeholder_text=tr("Filtrar sesiones…"))
        self.search.connect("search-changed", lambda *_: self.refresh())
        panel.append(self.search)

        # Árbol de sesiones: GtkListBox con activación de un solo clic, que
        # es la forma idiomática en GTK4 (un ColumnView sólo avisa con doble
        # clic). Las cabeceras de grupo son filas no activables.
        self._listbox = Gtk.ListBox()
        self._listbox.set_activate_on_single_click(True)
        self._listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._listbox.add_css_class("navigation-sidebar")
        self._listbox.connect("row-activated", self._on_row_activated)
        self._collapsed: set[str] = set()

        # Menú contextual con el botón derecho.
        right = Gtk.GestureClick()
        right.set_button(3)
        right.connect("pressed", self._on_tree_button)
        self._listbox.add_controller(right)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(self._listbox)
        panel.append(scroller)

        # Botonera
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        for icon, tip, callback in (
            ("list-add-symbolic", tr("Nueva sesión SSH"), self._new_session),
            ("folder-open-symbolic", tr("Explorador SFTP"), self._open_sftp),
            ("user-trash-symbolic", tr("Eliminar sesión"), self._delete_session),
        ):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip)
            b.connect("clicked", lambda *_, cb=callback: cb())
            buttons.append(b)
        panel.append(buttons)

        self.stack.add_named(panel, "sessions")
        self._panels["sessions"] = panel
        self.refresh()

    def _icon_data_func(self, _column, cell, model, iter_, _data) -> None:
        row = model.get_value(iter_, 0)
        cell.set_property("icon-name", row.icon if row else "")

    def _name_data_func(self, _column, cell, model, iter_, _data) -> None:
        row = model.get_value(iter_, 0)
        cell.set_property("markup", row.name_markup if row else "")

    def _target_data_func(self, _column, cell, model, iter_, _data) -> None:
        row = model.get_value(iter_, 0)
        cell.set_property("markup", row.target_markup if row else "")

    def refresh(self) -> None:
        """Recarga el árbol de sesiones desde la configuración."""
        text = (self.search.get_text() or "").lower().strip()
        hijo = self._listbox.get_first_child()
        while hijo is not None:
            siguiente = hijo.get_next_sibling()
            self._listbox.remove(hijo)
            hijo = siguiente

        groups: dict[str, list[Session]] = {}
        for s in CONFIG.sessions:
            if text and text not in (s.name + " " + s.host + " " +
                                     s.username + " " + s.group).lower():
                continue
            groups.setdefault(s.group or tr("Mis sesiones"), []).append(s)

        for gname in sorted(groups, key=lambda g: (g == tr("Mis sesiones"), g)):
            sessions = groups[gname]
            expanded = gname not in self._collapsed
            arrow = "▾" if expanded else "▸"
            cabecera = Gtk.ListBoxRow()
            cabecera.set_activatable(True)
            caja = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            etiqueta = Gtk.Label(label=f"{arrow}  {gname}")
            etiqueta.set_xalign(0)
            etiqueta.set_hexpand(True)
            etiqueta.add_css_class("heading")
            caja.append(etiqueta)
            contador = Gtk.Label(label=str(len(sessions)))
            contador.add_css_class("dim-label")
            contador.add_css_class("caption")
            caja.append(contador)
            cabecera.set_child(caja)
            cabecera._netterm_group = gname  # type: ignore[attr-defined]
            self._listbox.append(cabecera)

            if not expanded:
                continue
            for s in sessions:
                fila = Gtk.ListBoxRow()
                fila.set_activatable(True)
                fila._netterm_session = s  # type: ignore[attr-defined]
                contenido = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                contenido.set_margin_top(3)
                contenido.set_margin_bottom(3)
                contenido.set_margin_start(18)
                icono = Gtk.Image.new_from_icon_name(s.type.icon)
                contenido.append(icono)
                textos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                nombre = Gtk.Label(label=s.name)
                nombre.set_xalign(0)
                destino = Gtk.Label(label=s.display_target())
                destino.add_css_class("dim-label")
                destino.add_css_class("caption")
                destino.set_xalign(0)
                textos.append(nombre)
                textos.append(destino)
                contenido.append(textos)
                fila.set_child(contenido)
                self._listbox.append(fila)

        for panel in self._panels.values():
            if hasattr(panel, "refresh"):
                try:
                    panel.refresh()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Paneles auxiliares
    # ------------------------------------------------------------------
    def _build_tools_panel(self) -> None:
        from .tools import ToolsPanel

        self.tools_panel = ToolsPanel(self)
        self.stack.add_named(self.tools_panel, "tools")
        self._panels["tools"] = self.tools_panel

    def _build_macros_panel(self) -> None:
        from .macro import MacrosPanel

        self.macros_panel = MacrosPanel(self)
        self.stack.add_named(self.macros_panel, "macros")
        self._panels["macros"] = self.macros_panel

    def _build_sftp_panel(self) -> None:
        from .sftp import SftpPanel

        self.sftp_panel = SftpPanel(self)
        self.stack.add_named(self.sftp_panel, "sftp")
        self._panels["sftp"] = self.sftp_panel

    def show_panel(self, name: str, sub: str = "") -> None:
        """Muestra una pestaña del panel lateral (``sub`` = subpestaña)."""
        if name in self._toggle_buttons:
            self._toggle_buttons[name].set_active(True)
            self.stack.set_visible_child_name(name)
        if sub and name == "tools" and hasattr(self.tools_panel, "show_tab"):
            self.tools_panel.show_tab(sub)
        self._fit_width(sub)

    def _fit_width(self, sub: str = "") -> None:
        """Amplía la columna cuando el panel necesita más espacio."""
        if self.window is None:
            return
        wide = sub in ("interfaces", "packages", "servers")
        target = 560 if wide else int(CONFIG.get("sidebar_width", 280))
        try:
            self.window._paned.set_position(target)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------
    def _on_quick_activate(self, entry: Gtk.Entry) -> None:
        text = (entry.get_text() or "").strip()
        if not text:
            return
        if self.window:
            self.window._quick_connect(text)
            entry.set_text("")

    def _on_tree_release(self, _view, event) -> bool:
        """Abre la sesión con un único clic."""
        if event.button != 1:
            return False
        row = self._listbox.get_selected_row()
        session = self._row_session(row) if row is not None else None
        if session is None:
            return False
        self.emit("session-activated", session)
        return False

    def _row_session(self, row) -> Session | None:
        return getattr(row, "_netterm_session", None)

    def _row_group(self, row) -> str | None:
        return getattr(row, "_netterm_group", None)

    def _on_tree_button(self, _gesture, _n_press, x: float, y: float) -> None:
        """Menú contextual con el botón derecho."""
        row = self._listbox.get_selected_row()
        session = self._row_session(row) if row is not None else None
        if session is None:
            return
        self._show_context_menu(session, x, y)

    def _on_row_activated(self, _listbox, row) -> None:
        """Un clic en una fila: si es un grupo, se pliega; si es sesión, se abre."""
        if row is None:
            return
        grupo = self._row_group(row)
        if grupo:
            if grupo in self._collapsed:
                self._collapsed.discard(grupo)
            else:
                self._collapsed.add(grupo)
            self.refresh()
            return
        session = self._row_session(row)
        if session is not None:
            self.emit("session-activated", session)

    def _toggle_group(self, name_markup: str) -> None:
        """Plega o despliega un grupo (por su nombre de encabezado)."""
        plain = name_markup.replace("<b>", "").replace("</b>", "")
        for prefix in ("▾  ", "▸  "):
            if plain.startswith(prefix):
                plain = plain[len(prefix):]
                break
        if plain in self._collapsed:
            self._collapsed.discard(plain)
        else:
            self._collapsed.add(plain)
        self.refresh()

    def _on_tree_button(self, _gesture, _n_press, x: float, y: float) -> None:
        """Menú contextual con el botón derecho."""
        row = self._listbox.get_selected_row()
        session = self._row_session(row) if row is not None else None
        if session is None:
            return
        self._show_context_menu(session, x, y)

    def _show_context_menu(self, session: Session, x: float, y: float) -> None:
        menu = Gio.Menu()
        menu.append(tr("Abrir"), "win.open-session")
        menu.append(tr("Abrir SFTP"), "win.open-sftp")
        menu.append(tr("Editar"), "win.edit-session")
        menu.append(tr("Duplicar"), "win.duplicate-session")
        menu.append(tr("Separador"), None)
        menu.append(tr("Eliminar"), "win.delete-session")

        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(self._listbox)
        popover.set_has_arrow(False)
        popover.set_pointing_to(Gdk.Rectangle(x=int(x), y=int(y),
                                              width=1, height=1))
        popover.connect("closed", lambda *_: popover.unparent())
        popover.popup()

    def _new_session(self) -> None:
        if self.window:
            self.window.new_session("ssh")

    def _open_sftp(self) -> None:
        self.show_panel("sftp")

    def _delete_session(self) -> None:
        row = self._listbox.get_selected_row()
        session = self._row_session(row) if row is not None else None
        if session is not None:
            CONFIG.delete_session(session.id)
            self.refresh()
            self.emit("status-message",
                      tr("Sesión «{name}» eliminada", name=session.name))

    # ------------------------------------------------------------------
    def on_interface_changed(self) -> None:
        self.emit("interfaces-changed")
