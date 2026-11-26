#!/usr/bin/env python3
"""Reproduce: ¿aparece el diálogo de sesión SSH?"""

from __future__ import annotations

import os
import sys

import _harness  # noqa: E402,F401  (aisla la configuración)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk  # noqa: E402

from netterm.app import NetTermApp  # noqa: E402


def main() -> int:
    app = NetTermApp(app_id="io.github.netterm.NetTermDlgProbe")
    app.register()

    def probe(a) -> bool:
        win = a.window
        print("ventana principal:", win.get_visible(), win.get_title())
        try:
            win.new_session("ssh")
            print("new_session() devolvió sin error")
        except Exception as exc:
            import traceback
            traceback.print_exc()
            return False

        def check() -> bool:
            tops = [w for w in Gtk.Window.get_toplevels()
                    if w.get_visible() and w is not win]
            print("ventanas visibles aparte de la principal:", len(tops))
            for w in tops:
                print("  -", type(w).__name__, repr(w.get_title()),
                      "tamaño", w.get_width(), "x", w.get_height(),
                      "x", w.get_height(),
                      "pos", w.get_surface() is not None)
            a.quit()
            return False

        GLib.timeout_add(12000, check)
        return False

    GLib.timeout_add(1500, probe, app)
    app.run([])
    return 0


if __name__ == "__main__":
    sys.exit(main())
