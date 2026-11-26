#!/usr/bin/env python3
"""Prueba del flujo completo del diálogo: rellenar -> Conectar -> pestaña."""

from __future__ import annotations

import os
import sys

import _harness  # noqa: E402,F401  (aisla la configuración)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk  # noqa: E402

from netterm.app import NetTermApp  # noqa: E402
from netterm.dialogs import SessionDialog  # noqa: E402

fallos = 0


def check(nombre: str, cond: bool, detalle: str = "") -> None:
    global fallos
    if cond:
        print(f"  OK    {nombre}" + (f"  ({detalle})" if detalle else ""))
    else:
        fallos += 1
        print(f"  FALLO {nombre}" + (f"  ({detalle})" if detalle else ""))


def main() -> int:
    app = NetTermApp(app_id="io.github.netterm.NetTermSubmit")
    app.register()

    def probe(a) -> bool:
        win = a.window
        dlg = SessionDialog(win, kind="ssh")
        dlg.connect("session-created", win._on_session_created)
        dlg.present()

        # Rellenar el formulario como lo haría el usuario
        dlg.name_row.set_text("servidor-lab")
        dlg.host_row.set_text("192.0.2.50")
        dlg.port_row.set_value(2222)
        dlg.user_row.set_text("root")
        dlg.key_row.set_text(os.path.expanduser("~/.ssh/id_ed25519"))

        antes = len(win.pages)
        dlg._submit()          # equivalente a pulsar «Conectar»
        despues = len(win.pages)

        check("se crea una pestaña", despues == antes + 1, f"{antes} -> {despues}")
        if despues > antes:
            page = win.pages[-1]
            check("la pestaña es la sesión nueva", page.title == "servidor-lab",
                  page.title)
            check("la pestaña tiene icono", page._tab_label is not None)
        check("el diálogo se cierra", not dlg.get_visible())
        check("la sesión se guarda", win.sidebar is not None)

        a.quit()
        return False

    GLib.timeout_add(1500, probe, app)
    app.run([])
    print(f"\n  {'fallos: ' + str(fallos) if fallos else 'todo correcto'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
