#!/usr/bin/env python3
"""Prueba de la ventana flotante interna."""

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


def main() -> int:
    app = NetTermApp(app_id="io.github.netterm.NetTermProbe3")
    app.register()
    fallos = 0

    def probe(a) -> bool:
        win = a.window
        s = Session(id="probe3", name="github", type=SessionType.SSH,
                    group="Prueba", host="ssh.github.com", port=443,
                    username="git",
                    key_file=os.path.expanduser("~/.ssh/id_ed25519"))
        win.open_session(s)
        print(f"ventanas flotantes: {len(win._floating.windows)}")
        print(f"overlay children: {len(win._overlay.get_overlays())}")
        print(f"pestañas del notebook: {len(win.pages)}")
        if len(win._floating.windows) != 1:
            print("FALLO: no se creó la ventana flotante")
            nonlocal fallos
            fallos += 1

        fw = win._floating.windows[0]
        print(f"título: {fw.session.name} | tamaño min: "
              f"{fw.get_size_request()}")

        def check() -> bool:
            buf = Gtk.TextBuffer()
            start = buf.get_start_iter()
            end = buf.get_end_iter()
            try:
                fw.page.terminal.get_text(buf, start, end, False)
                text = buf.get_text(start, end, False)
            except Exception as exc:
                text = f"(error: {exc})"
            print("--- contenido del terminal ---")
            print(text[-400:] if text else "(vacío)")
            a.quit()
            return False

        GLib.timeout_add(7000, check)
        return False

    GLib.timeout_add(1500, probe, app)
    app.run([])
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
