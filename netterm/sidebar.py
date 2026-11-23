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


class SessionGroupObj(GObject.Object):
    """Grupo de sesiones (nivel raíz del árbol)."""

    __gtype_name__ = "NetTermGroup"

    def __init__(self, name: str, sessions: list[Session]):
        super().__init__()
        self.name = name
        self.sessions = sessions


class SessionObj(GObject.Object):
    """Una sesión dentro de un grupo."""

    __gtype_name__ = "NetTermSession"

    def __init__(self, session: Session):
        super().__init__()
        self.session = session


class SessionRowObj(GObject.Object):
    """Fila del árbol de sesiones: un grupo (plegable) o una sesión."""

    __gtype_name__ = "NetTermRow"

    def __init__(self, kind: str, icon: str, name_markup: str,
                 target_markup: str, session: Session | None = None,
                 level: int = 0, expanded: bool = True):
        super().__init__()
        self.kind = kind
        self.icon = icon
        self.name_markup = name_markup
        self.target_markup = target_markup
        self.session = session
        self.level = level
        self.expanded = expanded


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

        # Árbol de sesiones (lista plana con encabezados de grupo plegables)
        self._group_store = Gio.ListStore(item_type=SessionRowObj)
        self._collapsed: set[str] = set()
        self._selection = Gtk.SingleSelection(model=self._group_store)
        self._selection.set_autoselect(False)
        self._selection.set_can_unselect(True)

        self.tree = Gtk.ColumnView(model=self._selection)
        self.tree.set_show_column_separators(False)
        self.tree.set_show_row_separators(True)
        self.tree.set_reorderable(False)

        def _add_column(title: str, builder: str):
            factory = Gtk.SignalListItemFactory()
            factory.connect("setup", self._setup_cell, builder)
            factory.connect("bind", self._bind_cell, builder)
            col = Gtk.ColumnViewColumn()
            col.set_title(title)
            col.set_factory(factory)
            col.set_expand(builder != "target")
            self.tree.append_column(col)

        _add_column("", "icon")
        _add_column(tr("Sesión"), "name")
        _add_column(tr("Destino"), "target")

        self.tree.connect("activate", self._on_row_activated)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(self.tree)
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

    def _setup_cell(self, factory, list_item, builder: str) -> None:
        if builder == "icon":
            widget = Gtk.Image()
        else:
            widget = Gtk.Label(xalign=0)
            widget.set_ellipsize(3)
        list_item.set_child(widget)

    def _bind_cell(self, factory, list_item, builder: str) -> None:
        row = list_item.get_item()
        widget = list_item.get_child()
        if row is None:
            return
        if builder == "icon":
            widget.set_from_icon_name(row.icon)
        elif builder == "name":
            widget.set_markup(row.name_markup)
        else:
            widget.set_markup(row.target_markup)

    def _row_at(self, path) -> SessionRowObj | None:
        model = self._group_store
        return model.get_item(model.get_path(path)) if path else None

    def _selected_row(self) -> SessionRowObj | None:
        return self._selection.get_selected_item()

    def _icon_data_func(self, _column, cell, model, iter_, _data) -> None:
        row = model.get_value(iter_, 0)
        cell.set_property("icon-name", row.icon if row else "")

    def _name_data_func(self, _column, cell, model, iter_, _data) -> None:
        row = model.get_value(iter_, 0)
        cell.set_property("markup", row.name_markup if row else "")

    def _target_data_func(self, _column, cell, model, iter_, _data) -> None:
        row = model.get_value(iter_, 0)
        cell.set_property("markup", row.target_markup if row else "")

    def _create_children(self, _model, item) -> Gio.ListStore:
        store = Gio.ListStore(item_type=SessionObj)
        for s in getattr(item, "sessions", []):
            store.append(SessionObj(s))
        return store

    def _filter_visible(self, model, iter_, *args) -> bool:
        """Reservado: el filtrado se aplica al reconstruir el modelo."""
        return True

    def refresh(self) -> None:
        """Recarga el árbol de sesiones desde la configuración."""
        text = (self.search.get_text() or "").lower().strip()
        self._group_store.remove_all()

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
            self._group_store.append(SessionRowObj(
                kind="group",
                icon="",
                name_markup=f"<b>{arrow}  {GLib.markup_escape_text(gname)}</b>",
                target_markup=f"<span size='small'>{len(sessions)}</span>",
                expanded=expanded,
            ))
            if not expanded:
                continue
            for s in sessions:
                self._group_store.append(SessionRowObj(
                    kind="session",
                    icon=s.type.icon,
                    name_markup=f"    {GLib.markup_escape_text(s.name)}",
                    target_markup=("<span size='small'>"
                                   f"{GLib.markup_escape_text(s.display_target())}"
                                   "</span>"),
                    session=s,
                    level=1,
                ))

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

    def _on_row_activated(self, _view, _position, _col) -> None:
        row = self._selected_row()
        if row is None:
            return
        if row.kind == "group":
            self._toggle_group(row.name_markup)
            return
        if row.session is not None:
            self.emit("session-activated", row.session)

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

    def _on_tree_button(self, _tree, event) -> bool:
        if event.button != 3:
            return False
        row = self._selected_row()
        if row is None or row.kind != "session" or row.session is None:
            return False
        self._show_context_menu(row.session, event)
        return True

    def _show_context_menu(self, session: Session, event) -> None:
        menu = Gio.Menu()
        menu.append(tr("Abrir"), "win.open-session")
        menu.append(tr("Abrir SFTP"), "win.open-sftp")
        menu.append(tr("Editar"), "win.edit-session")
        menu.append(tr("Duplicar"), "win.duplicate-session")
        menu.append(tr("Separador"), None)
        menu.append(tr("Eliminar"), "win.delete-session")

        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(self.tree)
        popover.set_has_arrow(False)
        popover.set_pointing_to(Gdk.Rectangle())
        popover.set_pointing_to(
            Gdk.Rectangle(x=int(event.x), y=int(event.y), width=1, height=1))
        popover.connect("closed", lambda *_: popover.unparent())
        popover.popup()

    def _new_session(self) -> None:
        if self.window:
            self.window.new_session("ssh")

    def _open_sftp(self) -> None:
        self.show_panel("sftp")

    def _delete_session(self) -> None:
        row = self._selected_row()
        if row is not None and row.kind == "session" and row.session is not None:
            CONFIG.delete_session(row.session.id)
            self.refresh()
            self.emit("status-message",
                      tr("Sesión «{name}» eliminada",
                         name=row.session.name))

    # ------------------------------------------------------------------
    def on_interface_changed(self) -> None:
        self.emit("interfaces-changed")
