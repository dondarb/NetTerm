#!/usr/bin/env python3
"""Prueba del selector de sesiones (botón + de la cabecera)."""

from __future__ import annotations

import os
import sys

import _harness  # noqa: E402,F401  (aisla la configuración)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk  # noqa: E402

from netterm.app import NetTermApp  # noqa: E402
from netterm.session import Session, SessionType  # noqa: E402

fallos = 0


def check(nombre: str, cond: bool, detalle: str = "") -> None:
    global fallos
    if cond:
        print(f"  OK    {nombre}" + (f"  ({detalle})" if detalle else ""))
    else:
        fallos += 1
        print(f"  FALLO {nombre}" + (f"  ({detalle})" if detalle else ""))


def recorrer(widget, tipos):
    """Devuelve el primer descendiente del tipo indicado."""
    pila = [widget]
    while pila:
        w = pila.pop(0)
        if isinstance(w, tipos):
            return w
        if hasattr(w, "get_children"):
            try:
                pila.extend(w.get_children())
            except Exception:
                pass
    return None


class _Clic:
    """Sustituto de un evento de pulsación."""

    button = 1
    x = 10.0
    y = 10.0


def main() -> int:
    app = NetTermApp(app_id="io.github.netterm.NetTermChooser")
    app.register()

    def probe(a) -> bool:
        from netterm.config import CONFIG

        win = a.window
        session = Session(id="probe-chooser", name="servidor-lab",
                          type=SessionType.SSH, host="192.0.2.50", port=2222,
                          username="root", group="Mis sesiones")
        CONFIG.upsert_session(session)
        win.sidebar.refresh()

        win._show_chooser()
        popover = win._chooser
        check("el selector se abre", popover is not None)
        check("el popover está visible", popover.get_visible())

        # --- botón «›» de la sesión ----------------------------------
        filas = win._chooser_rows
        check("el selector lista las sesiones", len(filas) >= 1, f"{len(filas)}")
        boton = filas[0][1] if filas else None
        check("se encuentra el botón «›»", boton is not None)
        antes = len(win.pages)
        if boton is not None:
            boton.emit("clicked")
        check("al elegir una sesión se abre una pestaña",
              len(win.pages) == antes + 1, f"{antes} -> {len(win.pages)}")
        if len(win.pages) > antes:
            check("la pestaña es la sesión elegida",
                  win.pages[-1].title == "servidor-lab", win.pages[-1].title)

        # --- botón «Nueva sesión SSH…» --------------------------------
        win._show_chooser()
        nuevo = None
        pila = [win._chooser.get_child()] if win._chooser.get_child() else []
        while pila and nuevo is None:
            w = pila.pop(0)
            if isinstance(w, Gtk.Button) and (w.get_label() or "").startswith(
                    "Nueva sesión"):
                nuevo = w
                break
            if hasattr(w, "get_first_child"):
                hijo = w.get_first_child()
                while hijo is not None:
                    pila.append(hijo)
                    hijo = hijo.get_next_sibling()
        check("se encuentra el botón «Nueva sesión SSH…»", nuevo is not None)

        llamadas = []
        original = win.new_session

        def espia(kind):
            llamadas.append(kind)
            return original(kind)

        win.new_session = espia  # type: ignore[assignment]
        if nuevo is not None:
            nuevo.emit("clicked")
        check("el botón abre el diálogo de sesión", len(llamadas) == 1,
              f"{llamadas}")

        # --- clic único en el árbol lateral ----------------------------
        win.sidebar.refresh()
        fila = None
        hijo = win.sidebar._listbox.get_first_child()
        while hijo is not None:
            if getattr(hijo, "_netterm_session", None) is not None:
                fila = hijo
                break
            hijo = hijo.get_next_sibling()
        check("el árbol lateral lista la sesión", fila is not None)

        abiertas = []
        win.sidebar.connect("session-activated",
                            lambda _s, sess: abiertas.append(sess.name))
        win.sidebar._on_row_activated(None, fila)
        check("un clic en el árbol abre la sesión",
              len(abiertas) == 1, f"{abiertas}")

        a.quit()
        return False

    GLib.timeout_add(1500, probe, app)
    app.run([])
    print(f"\n  {'fallos: ' + str(fallos) if fallos else 'todo correcto'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
