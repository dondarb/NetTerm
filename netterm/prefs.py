"""Ventana de preferencias y al "Customizer" de MobaXterm."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .config import CONFIG, data_dir  # noqa: E402
from .i18n import tr  # noqa: E402
from .secrets import VAULT  # noqa: E402


class PreferencesWindow(Adw.PreferencesWindow):
    """Preferencias de la aplicación."""

    def __init__(self, parent=None):
        super().__init__(transient_for=parent, modal=True)
        self.set_title(tr("Preferencias"))
        self.set_default_size(620, 640)

        page = Adw.PreferencesPage()
        page.set_title(tr("General"))

        # -- Apariencia --------------------------------------------------
        group = Adw.PreferencesGroup(title=tr("Apariencia"))
        theme = Adw.ComboRow(title=tr("Tema"))
        theme.set_model(Gtk.StringList.new([tr("Oscuro"), tr("Claro"),
                                            tr("Del sistema")]))
        current = {"dark": 0, "light": 1, "system": 2}.get(
            CONFIG.get("theme", "dark"), 0)
        theme.set_selected(current)
        theme.connect("notify::selected", self._on_theme)
        group.add(theme)

        font = Adw.EntryRow(title=tr("Fuente del terminal"))
        font.set_text(str(CONFIG.get("font", "Monospace 11")))
        font.connect("changed", self._on_font)
        group.add(font)

        size = Adw.SpinRow.new_with_range(6, 32, 1)
        size.set_title(tr("Tamaño de letra"))
        size.set_value(int(CONFIG.get("font_size", 11)))
        size.connect("value-changed", self._on_font_size)
        group.add(size)

        scrollback = Adw.SpinRow.new_with_range(100, 1000000, 100)
        scrollback.set_title(tr("Historial (líneas)"))
        scrollback.set_value(int(CONFIG.get("scrollback", 10000)))
        scrollback.connect("value-changed", self._on_scrollback)
        group.add(scrollback)

        blink = Adw.SwitchRow(title=tr("Cursor parpadeante"))
        blink.set_active(bool(CONFIG.get("cursor_blink", True)))
        blink.connect("activate", self._on_blink)
        group.add(blink)

        copy_sel = Adw.SwitchRow(title=tr("Copiar al seleccionar"))
        copy_sel.set_active(bool(CONFIG.get("copy_on_select", False)))
        copy_sel.connect("activate", self._on_copy_select)
        group.add(copy_sel)
        page.add(group)

        # -- Conexión ----------------------------------------------------
        group2 = Adw.PreferencesGroup(title=tr("Conexión"))
        shell = Adw.EntryRow(title=tr("Shell por defecto"))
        shell.set_text(str(CONFIG.get("default_shell", "")))
        shell.set_tooltip_text(tr("Vacío = $SHELL del sistema"))
        shell.connect("changed", self._on_shell)
        group2.add(shell)

        ssh_opts = Adw.EntryRow(title=tr("Opciones SSH adicionales"))
        ssh_opts.set_text(str(CONFIG.get("ssh_options", "")))
        ssh_opts.set_tooltip_text(tr("Se añaden a todas las sesiones SSH"))
        ssh_opts.connect("changed", self._on_ssh_options)
        group2.add(ssh_opts)

        x11 = Adw.SwitchRow(title=tr("X11 forwarding por defecto"))
        x11.set_active(bool(CONFIG.get("x11_forward", True)))
        x11.connect("activate", self._on_x11)
        group2.add(x11)

        new_win = Adw.ComboRow(title=tr("How sessions are opened"))
        new_win.set_model(Gtk.StringList.new([
            tr("Internal tab"), tr("Floating window"), tr("System window")]))
        new_win.set_selected({"tabs": 0, "floating": 1, "window": 2}.get(
            str(CONFIG.get("session_presentation", "tabs")), 0))
        new_win.set_subtitle(tr("Like the editor you are using: a tab inside "
                                "the interface, a floating window inside it, "
                                "or a separate system window"))
        new_win.connect("notify::selected", self._on_presentation)
        group2.add(new_win)
        page.add(group2)

        # -- Seguridad ----------------------------------------------------
        group3 = Adw.PreferencesGroup(title=tr("Seguridad"))
        vault = Adw.ActionRow(title=tr("Contraseña maestra"),
                               subtitle=tr("Activa el cifrado de las contraseñas "
                                           "de sesión"))
        vault_btn = Gtk.Button(label=tr("Configurar"))
        vault_btn.connect("clicked", lambda *_: self._master_password(parent))
        vault.add_suffix(vault_btn)
        group3.add(vault)
        page.add(group3)

        # -- Personalización (Customizer) ---------------------------------
        group4 = Adw.PreferencesGroup(title=tr("Personalización"))
        banner = Adw.EntryRow(title=tr("Banner de bienvenida"))
        banner.set_text(str(CONFIG.get("banner", "")))
        banner.connect("changed", self._on_banner)
        group4.add(banner)

        logo = Adw.EntryRow(title=tr("Logotipo (ruta)"))
        logo.set_text(str(CONFIG.get("logo", "")))
        logo.connect("changed", self._on_logo)
        group4.add(logo)
        page.add(group4)

        self.add_page(page)

    # ------------------------------------------------------------------
    def _save(self) -> None:
        CONFIG.save_settings()

    def _on_theme(self, row, *_a) -> None:
        CONFIG.set("theme", ["dark", "light", "system"][row.get_selected()])
        self._save()
        from .app import NetTermApp
        app = NetTermApp.get_default()
        if app:
            app._apply_theme()

    def _on_font(self, row) -> None:
        CONFIG.set("font", row.get_text())
        self._save()
        self._apply_terminal_font()

    def _on_font_size(self, row) -> None:
        CONFIG.set("font_size", row.get_value_as_int())
        self._save()
        self._apply_terminal_font()

    def _on_scrollback(self, row) -> None:
        CONFIG.set("scrollback", row.get_value_as_int())
        self._save()

    def _on_blink(self, row, *_a) -> None:
        CONFIG.set("cursor_blink", row.get_active())
        self._save()

    def _on_copy_select(self, row, *_a) -> None:
        CONFIG.set("copy_on_select", row.get_active())
        self._save()

    def _on_shell(self, row) -> None:
        CONFIG.set("default_shell", row.get_text())
        self._save()

    def _on_ssh_options(self, row) -> None:
        CONFIG.set("ssh_options", row.get_text())
        self._save()

    def _on_x11(self, row, *_a) -> None:
        CONFIG.set("x11_forward", row.get_active())
        self._save()

    def _on_new_window(self, row, *_a) -> None:
        CONFIG.set("sessions_in_new_window", row.get_active())
        self._save()

    def _on_presentation(self, row, *_a) -> None:
        CONFIG.set("session_presentation",
                   ["tabs", "floating", "window"][row.get_selected()])
        self._save()

    def _on_banner(self, row) -> None:
        CONFIG.set("banner", row.get_text())
        self._save()

    def _on_logo(self, row) -> None:
        CONFIG.set("logo", row.get_text())
        self._save()

    def _apply_terminal_font(self) -> None:
        app = None
        for window in Gtk.Window.get_toplevels():
            if hasattr(window, "pages"):
                app = window
                break
        if app is None:
            return
        for page in getattr(app, "pages", []):
            page._apply_font()

    # ------------------------------------------------------------------
    def _master_password(self, parent) -> None:
        dialog = Adw.MessageDialog(
            transient_for=parent, modal=True,
            heading=tr("Contraseña maestra"),
            body=tr("Se usa para cifrar las contraseñas de sesión con AES. "
                    "Si la forget, las contraseñas guardadas no se podrán "
                    "recuperar."))
        entry = Gtk.PasswordEntry()
        entry.set_placeholder_text(tr("contraseña maestra"))
        dialog.set_extra_child(entry)
        dialog.add_response("cancelar", tr("Cancelar"))
        dialog.add_response("aceptar", tr("Aceptar"))
        dialog.set_response_appearance("aceptar", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("aceptar")
        dialog.set_close_response("cancelar")

        def on_response(d, response) -> None:
            if response != Gtk.ResponseType.ACCEPT:
                return
            master = entry.get_text()
            if not master:
                return
            try:
                if VAULT.has_master:
                    VAULT.change_master(VAULT._master or "", master)
                else:
                    VAULT.unlock(master)
            except Exception as exc:
                Adw.MessageDialog(transient_for=parent, heading=tr("Error"),
                                  body=str(exc)).present()
                return
            self._save()

        dialog.connect("response", on_response)
        dialog.present()
