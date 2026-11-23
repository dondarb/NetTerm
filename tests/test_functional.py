#!/usr/bin/env python3
"""Pruebas funcionales de NetTerm.

Ejercita las rutas críticas sin depender del foco de la ventana:

    cd ~/netterm && .venv/bin/python tests/test_functional.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  OK    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAILED.append(name)
        print(f"  FALLO {name}" + (f"  ({detail})" if detail else ""))


def section(title: str) -> None:
    print(f"\n== {title} ==")


# ---------------------------------------------------------------------------
def test_network_layer() -> None:
    section("Capa de red (netif)")
    from netterm import netif

    ifaces = netif.list_interfaces()
    check("se enumeran interfaces", len(ifaces) >= 1, f"{len(ifaces)}")
    names = [i.name for i in ifaces]
    check("incluye loopback", "lo" in names, ", ".join(names))

    wifi = [i for i in ifaces if i.is_wireless]
    eth = [i for i in ifaces if i.kind == "ethernet"]
    check("detecta wifi", len(wifi) >= 1,
          ", ".join(f"{i.name}/{i.driver}" for i in wifi))
    check("detecta ethernet", len(eth) >= 1,
          ", ".join(f"{i.name}/{i.driver}" for i in eth))

    up = [i for i in ifaces if i.state == "up"]
    check("detecta interfaces activas", len(up) >= 1)

    with_addr = [i for i in ifaces if i.ipv4]
    check("detecta direcciones IPv4", len(with_addr) >= 1,
          ", ".join(f"{i.name}={i.primary_ipv4}" for i in with_addr))

    default = netif.default_interface()
    check("detecta interfaz por defecto", default is not None, str(default))

    routes = netif.routes_for(default) if default else []
    check("lee rutas", len(routes) >= 1, "; ".join(routes[:2]))

    neigh = netif.neighbour_table()
    check("lee tabla de vecinos", isinstance(neigh, list), f"{len(neigh)} filas")

    # Simula una tarjeta nueva: el enumeration debe ser dinámico
    check("enumeration es dinámico (sin caché)",
          netif.list_interfaces() is not netif.list_interfaces())


def test_netops() -> None:
    section("Herramientas de red (netops)")
    from netterm import netops

    runner = netops.ping("127.0.0.1", count=2, timeout=2)
    check("ping construye el comando", "ping" in runner.cmd[0], " ".join(runner.cmd))
    out = runner.read_all()
    check("ping responde", "bytes" in out or "ttl" in out.lower(),
          out.strip().splitlines()[-1] if out.strip() else "sin salida")

    r2 = netops.list_sockets()
    check("ss disponible", "ss" in " ".join(r2.cmd))

    r3 = netops.traceroute("127.0.0.1")
    check("traceroute construye comando", bool(r3.cmd))

    r4 = netops.nmap_scan("127.0.0.1", ports="22")
    check("nmap construye comando", "nmap" in r4.cmd[0] or "sh" in r4.cmd[0],
          " ".join(r4.cmd[:4]))

    rows = netops.interface_summary()
    check("resumen de interfaces", len(rows) >= 1, f"{len(rows)} filas")


def test_packages() -> None:
    section("Gestor de paquetes")
    from netterm import packages

    installed = packages.list_installed()
    check("lista instalados", len(installed) > 10, f"{len(installed)} paquetes")
    check("los paquetes tienen nombre",
          all("name" in p for p in installed[:5]))
    runner = packages.install("netterm")
    check("instalar usa pkexec", "pkexec" in runner.cmd, " ".join(runner.cmd[:3]))


def test_sessions_and_vault() -> None:
    section("Sesiones y bóveda")
    from netterm.config import CONFIG
    from netterm.secrets import VAULT
    from netterm.session import Session, SessionType

    s = Session(id="test-1", name="prueba", type=SessionType.SSH,
                host="10.0.0.1", port=2222, username="root", group="Pruebas")
    CONFIG.upsert_session(s)
    check("la sesión se guarda", CONFIG.session("test-1") is not None)
    check("aparece en su grupo",
          any(x.id == "test-1" for x in CONFIG.sessions_in("Pruebas")))

    d = s.to_dict()
    back = Session.from_dict(d)
    check("serializa y deserializa", back.host == "10.0.0.1" and
          back.type == SessionType.SSH)

    VAULT.unlock("clave-de-prueba")
    check("la bóveda se desbloquea", VAULT.unlocked)
    VAULT.set_secret("test:key", "secreto")
    check("guarda y recupera un secreto",
          VAULT.get_secret("test:key") == "secreto")
    VAULT.delete_secret("test:key")

    CONFIG.delete_session("test-1")
    check("elimina la sesión", CONFIG.session("test-1") is None)


def test_sshconfig() -> None:
    section("Parser de ~/.ssh/config")
    from netterm import sshconfig

    opts = sshconfig.resolve_host("ejemplo")
    check("resuelve un host", "HostName" in opts, str(opts.get("HostName")))
    check("hereda el puerto por defecto",
          opts.get("Port") in (None, "22"), str(opts.get("Port")))

    # El fichero real del usuario debe interpretarse con HostName y Port.
    real = sshconfig.parse_ssh_config()
    if real:
        alias = next(iter(real))
        entry = real[alias]
        check("lee HostName", "HostName" in entry, f"{alias} -> {entry.get('HostName')}")
        check("lee Port", "Port" in entry, f"{alias} -> {entry.get('Port')}")
        check("lee User", "User" in entry, f"{alias} -> {entry.get('User')}")
        imported = sshconfig.import_sessions()
        check("importa sesiones", len(imported) >= 1,
              ", ".join(f"{s.name}={s.host}:{s.port}" for s in imported))
        check("la clave se expande",
              all(not s.key_file or s.key_file.startswith("/")
                  for s in imported))


def test_serial() -> None:
    section("Consola serie")
    from netterm.dialogs import serial_ports

    ports = serial_ports()
    check("enumera puertos serie", isinstance(ports, list),
          ", ".join(p[0] for p in ports[:5]) or "ninguno conectado")

    from netterm.terminal import SerialChannel, keyval_to_bytes
    from gi.repository import Gdk

    check("mapea teclas especiales",
          keyval_to_bytes(Gdk.KEY_Return) == b"\r")
    check("mapea caracteres", keyval_to_bytes(ord("a"), "a") == b"a")


def test_mobaxterm_import() -> None:
    section("Importador de MobaXterm")
    from netterm import mobaxterm

    check("busca el ini de MobaXterm", mobaxterm.find_ini() is None or
          mobaxterm.find_ini().exists(),
          str(mobaxterm.find_ini()))
    check("el importador no revienta",
          isinstance(mobaxterm.import_mobaxterm_sessions(), list))


def test_ui() -> None:
    section("Interfaz gráfica")
    from netterm.app import NetTermApp

    app = NetTermApp(app_id="io.github.netterm.NetTermTest")
    app.register()

    results: dict[str, object] = {}

    def on_activate(a) -> bool:
        win = a.window
        results["window"] = win
        results["pages"] = len(win.pages)
        results["sidebar_panels"] = sorted(win.sidebar._panels.keys())
        results["menu_sections"] = win._build_menu().get_n_items()

        # Tabla de interfaces poblada
        tools = win.sidebar.tools_panel
        tools.refresh()
        results["iface_rows"] = tools.interfaces_panel.store.get_n_items()
        results["iface_names"] = [i.name for i in
                                  tools.interfaces_panel._rows]
        results["ping_ifaces"] = tools.ping_panel.iface_store.get_n_items()

        # Sesión guardada visible en el árbol
        from netterm.config import CONFIG
        from netterm.session import Session, SessionType
        s = Session(id="ui-1", name="HostUI", type=SessionType.SSH,
                    host="192.0.2.10", group="UI")
        CONFIG.upsert_session(s)
        win.sidebar.refresh()
        results["tree_rows"] = win.sidebar._group_store.get_n_items()
        results["session_rows"] = sum(
            1 for i in range(win.sidebar._group_store.get_n_items())
            if win.sidebar._group_store.get_item(i).kind == "session")

        # Abrir una terminal nueva
        win._open_local_terminal()
        results["pages_after"] = len(win.pages)

        a.quit()
        return False

    GLib.timeout_add(1200, on_activate, app)
    app.run([])

    if "window" not in results:
        print("  (la aplicación no llegó a activarse)")

    check("la ventana se crea", results.get("window") is not None)
    check("abre una terminal local al arrancar", results.get("pages") == 1,
          str(results.get("pages")))
    check("las 4 pestañas laterales existen",
          results.get("sidebar_panels") == ["macros", "sessions", "sftp", "tools"],
          str(results.get("sidebar_panels")))
    check("el menú tiene 9 secciones", results.get("menu_sections") == 9,
          str(results.get("menu_sections")))
    check("la tabla de interfaces se puebla", (results.get("iface_rows") or 0) >= 2,
          f"{results.get('iface_rows')} filas: {results.get('iface_names')}")
    check("el selector de interfaz lista las NIC",
          (results.get("ping_ifaces") or 0) >= 2, str(results.get("ping_ifaces")))
    check("la sesión aparece en el árbol", (results.get("session_rows") or 0) >= 1,
          f"{results.get('session_rows')} sesiones")
    check("se pueden abrir varias terminales",
          (results.get("pages_after") or 0) >= 2, str(results.get("pages_after")))

    from netterm.config import CONFIG
    CONFIG.delete_session("ui-1")


def main() -> int:
    for fn in (test_network_layer, test_netops, test_packages,
               test_sessions_and_vault, test_sshconfig, test_serial,
               test_mobaxterm_import, test_ui):
        try:
            fn()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            FAILED.append(fn.__name__)

    print(f"\n{'=' * 56}")
    print(f"  {len(PASSED)} correctas, {len(FAILED)} fallidas")
    if FAILED:
        for name in FAILED:
            print(f"   - {name}")
    print("=" * 56)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
