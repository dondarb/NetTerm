"""Punto de entrada: ``python -m netterm``."""

from __future__ import annotations

import os
import sys


def _bootstrap_vendor() -> None:
    """Obsoleto: la inicialización vive ahora en ``netterm.app``.

    Se mantiene por compatibilidad con versiones anteriores.
    """
    from .app import bootstrap_vendor

    bootstrap_vendor()


def main() -> int:
    from .app import bootstrap_vendor, main as app_main

    bootstrap_vendor()
    return app_main()


if __name__ == "__main__":
    sys.exit(main())
