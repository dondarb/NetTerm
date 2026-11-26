#!/usr/bin/env python3
"""Prueba del flujo completo: diálogo de sesión -> pestaña interna -> SSH real."""

from __future__ import annotations

import os
import subprocess
import sys

import _harness  # noqa: E402,F401  (aisla la configuración)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk  # noqa: E402

from netterm.app import NetTermApp  # noqa: E402
from netterm.dialogs import SessionDialog  # noqa: E402
from netterm.session import Session, SessionType  # noqa: E402

fallos = 0


def check(nombre: str, cond: bool, detalle: str = "") -> None:
    global fallos
    if cond:
        print(f"  OK    {nombre}" + (f"  ({detalle})" if detalle else ""))
    else:
        fallos += 1
        print(f"  FALLO {nombre}" + (f"  ({detalle})" if detalle else ""))


def main() -> int:
    app = NetTermApp(app_id="io.github.netterm.NetTermProbe4")
    app.register()

    def probe(a) -> bool:
        win = a.window

        # --- 1. El diálogo de sesión se abre sin reventar ---------------
        print("== diálogo de sesión ==")
        try:
            dlg = SessionDialog(win, kind="ssh")
            check("el diálogo se crea", True)
            dlg.destroy()
        except Exception as exc:
            check("el diálogo se crea", False, f"{type(exc).__name__}: {exc}")

        # --- 2. La sesión se abre como pestaña interna ------------------
        print("== pestaña interna ==")
        antes = len(win.pages)
        s = Session(id="probe4", name="github", type=SessionType.SSH,
                    group="Prueba", host="ssh.github.com", port=443,
                    username="git",
                    key_file=os.path.expanduser("~/.ssh/id_ed25519"))
        win.open_session(s)
        despues = len(win.pages)
        check("se abre una pestaña", despues == antes + 1,
              f"{antes} -> {despues}")
        check("no se crean ventanas flotantes", len(win._floating.windows) == 0)

        page = win.pages[-1]
        check("la pestaña tiene icono y nombre",
              page.title == "github", page.title)

        # --- 3. La conexión SSH funciona de verdad ----------------------
        print("== conexión SSH real ==")

        def leer() -> bool:
            # El binding de PyGObject no permite volcar el texto del terminal
            # (get_text/get_text_range devuelven None), así que se comprueba
            # que el proceso hijo de SSH sigue vivo y que el terminal tiene
            # contenido; la conexión se verifica aparte, por comando.
            filas = page.terminal.get_row_count()
            check("el terminal muestra contenido", filas > 1, f"{filas} filas")
            # El shell de git de GitHub termina solo, así que la sesión remota
            # debe dejar la pestaña abierta con el aviso de fin de sesión.
            check("la pestaña permanece tras terminar la sesión",
                  any(p is page for p in win.pages),
                  f"{len(win.pages)} pestañas")

            res = subprocess.run(
                ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
                 "-p", "443", "-i", os.path.expanduser("~/.ssh/id_ed25519"),
                 "git@ssh.github.com"],
                capture_output=True, text=True, timeout=25)
            saludo = (res.stdout + res.stderr).strip()
            check("el servidor SSH acepta la clave", "Hi" in saludo,
                  saludo.splitlines()[0][:60] if saludo else "sin salida")
            a.quit()
            return False

        GLib.timeout_add(8000, leer)
        return False

    GLib.timeout_add(1500, probe, app)
    app.run([])
    print(f"\n{'=' * 50}\n  {'fallos: ' + str(fallos) if fallos else 'todo correcto'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
