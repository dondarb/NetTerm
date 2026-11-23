"""Modo multi-ejecución.

Equivalente a la "Multi-execution" de MobaXterm: las teclas que se escriben en
una terminal se replican en todas las demás, de modo que una misma orden se
ejecuta en varios servidores a la vez.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402


class MultiExecController:
    """Difunde la entrada de teclado entre todas las terminales abiertas."""

    def __init__(self, window) -> None:
        self.window = window
        self.enabled = False
        self._controllers: list[tuple[Gtk.EventControllerKey, object]] = []

    # ------------------------------------------------------------------
    def enable(self) -> None:
        if self.enabled:
            return
        self.enabled = True
        for page in self.window.pages:
            self._attach(page)
        self.window.connect("notify::pages", lambda *_: self._resync())
        self._banner()

    def disable(self) -> None:
        self.enabled = False
        for controller, page in self._controllers:
            try:
                page.terminal.remove_controller(controller)
            except Exception:
                pass
        self._controllers.clear()

    def _resync(self) -> None:
        if not self.enabled:
            return
        for controller, page in list(self._controllers):
            if page not in self.window.pages:
                try:
                    page.terminal.remove_controller(controller)
                except Exception:
                    pass
                self._controllers.remove((controller, page))
        for page in self.window.pages:
            if not any(p is page for _, p in self._controllers):
                self._attach(page)

    # ------------------------------------------------------------------
    def _attach(self, page) -> None:
        controller = Gtk.EventControllerKey()
        controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        controller.connect("key-pressed", self._on_key, page)
        page.terminal.add_controller(controller)
        self._controllers.append((controller, page))

    def _on_key(self, _controller, keyval: int, keycode: int, state, source) -> bool:
        if not self.enabled:
            return False
        char = chr(Gdk.keyval_to_unicode(keyval)) if Gdk.keyval_to_unicode(keyval) else ""
        from .terminal import keyval_to_bytes

        data = keyval_to_bytes(keyval, char)
        if not data:
            return False
        text = data.decode("utf-8", errors="replace")
        for page in self.window.pages:
            if page is source:
                continue
            try:
                page.send_text(text)
            except Exception:
                continue
        return False  # la terminal origen sigue procesando la tecla

    # ------------------------------------------------------------------
    def _banner(self) -> None:
        """Muestra el aviso de MobaXterm sobre el modo multi-ejecución."""
        overlay = getattr(self.window, "_toast_overlay", None)
        if overlay is None:
            return
        banner = Adw.Banner() if False else None
        toast = _toast("Multi-ejecución: las teclas se replican en todas las "
                       "terminales")
        overlay.add_toast(toast)


def _toast(message: str):
    from gi.repository import Adw

    toast = Adw.Toast.new(message)
    toast.set_timeout(4)
    return toast
