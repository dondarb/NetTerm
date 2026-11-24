#!/usr/bin/env python3
"""Prueba de apertura de sesión SSH en ventana nueva."""

from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk  # noqa: E402

from netterm.app import NetTermApp  # noqa: E402
from netterm.session import Session, SessionType  # noqa: E402


def main() -> int:
    app = NetTermApp(app_id="io.github.netterm.NetTermProbe2")
    app.register()

    def probe(a) -> bool:
        win = a.window
        s = Session(id="probe2", name="github", type=SessionType.SSH,
                    group="Prueba", host="ssh.github.com", port=443,
                    username="git",
                    key_file=os.path.expanduser("~/.ssh/id_ed25519"))
        before = len(win._session_windows)
        win.open_session(s)
        after = len(win._session_windows)
        print(f"ventanas de sesión: {before} -> {after}")
        print(f"pestañas en la ventana principal: {len(win.pages)}")
        if after == before:
            print("FALLO: no se creó una ventana nueva")
            a.quit()
            return False

        swin = win._session_windows[-1]
        print(f"título de la ventana: {swin.get_title()}")

        def check() -> bool:
            buf = Gtk.TextBuffer()
            start = buf.get_start_iter()
            end = buf.get_end_iter()
            try:
                swin.page.terminal.get_text(buf, start, end, False)
                text = buf.get_text(start, end, False)
            except Exception as exc:
                text = f"(no se pudo leer: {exc})"
            print("--- contenido del terminal ---")
            print(text[-500:] if text else "(vacío)")
            a.quit()
            return False

        GLib.timeout_add(7000, check)
        return False

    GLib.timeout_add(1500, probe, app)
    app.run([])
    return 0


if __name__ == "__main__":
    sys.exit(main())
