"""Enumeración dinámica de interfaces de red.

Este módulo es el corazón del requisito "que funcione con la tarjeta de red
que tenga instalada el equipo, sea cual sea, o la que se instale después".

No hay nada hardcodeado: cada vez que se llama a :func:`list_interfaces` se
interroga al kernel, de modo que aparecen automáticamente las placas Ethernet,
los adaptadores Wi-Fi, los dongles USB, los puentes, los bonds, las VLANs, los
túneles y los bridges Docker/Podman/LXC.

Fuentes de datos, en orden de enriching:

1. ``ip -j -d link show`` / ``ip -j addr show``  (información autoritativa)
2. ``/sys/class/net/<if>/``                       (driver, carrier, speed, tipo)
3. ``nmcli device``                                (estado de NetworkManager)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SYSFS_NET = Path("/sys/class/net")

_KIND_BY_NAME = {
    "lo": "loopback",
    "docker0": "bridge",
    "virbr0": "bridge",
    "veth": "veth",
    "br-": "bridge",
    "bond": "bond",
    "wl": "wifi",
    "wlp": "wifi",
    "wlan": "wifi",
    "ww": "wifi",
    "en": "ethernet",
    "eno": "ethernet",
    "enp": "ethernet",
    "ens": "ethernet",
    "enx": "ethernet",
    "eth": "ethernet",
    "em": "ethernet",
    "usb": "ethernet",
    "tun": "tun",
    "tap": "tap",
    "wg": "wireguard",
    "veth": "veth",
    "virbr": "bridge",
    "ham": "hamradio",
}

_ICON_BY_KIND = {
    "ethernet": "network-wired-symbolic",
    "wifi": "network-wireless-symbolic",
    "loopback": "network-server-symbolic",
    "bridge": "network-server-symbolic",
    "bond": "network-server-symbolic",
    "vlan": "network-server-symbolic",
    "tun": "network-server-symbolic",
    "tap": "network-server-symbolic",
    "wireguard": "network-server-symbolic",
    "veth": "network-server-symbolic",
    "hamradio": "network-server-symbolic",
    "unknown": "network-server-symbolic",
}


def _run(cmd: list[str], timeout: float = 4.0) -> str:
    if not shutil.which(cmd[0]):
        return ""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _run_json(cmd: list[str], timeout: float = 4.0) -> list[dict[str, Any]]:
    out = _run(cmd, timeout)
    if not out.strip():
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return []
    return data if isinstance(data, list) else []


@dataclass
class Addr:
    """Una dirección asignada a una interfaz."""

    family: str          # "inet" | "inet6"
    address: str
    prefix: int
    scope: str = ""

    def cidr(self) -> str:
        return f"{self.address}/{self.prefix}"


@dataclass
class NetIface:
    """Descripción completa de una interfaz de red."""

    name: str
    ifindex: int = 0
    kind: str = "unknown"
    driver: str = ""
    mac: str = ""
    mtu: int = 0
    state: str = "unknown"        # up | down | unknown
    carrier: bool = False
    speed: int = 0                # Mbps, 0 si desconocido
    duplex: str = ""
    addresses: list[Addr] = field(default_factory=list)
    gateways: list[str] = field(default_factory=list)
    dns: list[str] = field(default_factory=list)
    nm_connection: str = ""
    nm_type: str = ""
    nm_state: str = ""
    slaves: list[str] = field(default_factory=list)
    master: str = ""
    sysfs_path: str = ""

    # -- utilidades ---------------------------------------------------
    @property
    def ipv4(self) -> list[Addr]:
        return [a for a in self.addresses if a.family == "inet"]

    @property
    def ipv6(self) -> list[Addr]:
        return [a for a in self.addresses if a.family == "inet6"]

    @property
    def is_wireless(self) -> bool:
        return self.kind == "wifi"

    @property
    def is_virtual(self) -> bool:
        return self.kind in ("bridge", "bond", "vlan", "tun", "tap",
                              "wireguard", "veth", "loopback")

    @property
    def icon(self) -> str:
        return _ICON_BY_KIND.get(self.kind, "network-server-symbolic")

    @property
    def label(self) -> str:
        """Etiqueta legible: ``wlp3s0 (wifi) - 192.168.1.42/24``."""
        parts = [self.name, f"({self.kind})"]
        if self.ipv4:
            parts.append(self.ipv4[0].cidr())
        elif self.ipv6:
            parts.append(self.ipv6[0].cidr())
        elif self.state == "up":
            parts.append("sin dirección")
        return " - ".join(parts)

    @property
    def primary_ipv4(self) -> str:
        return self.ipv4[0].address if self.ipv4 else ""

    def status_text(self) -> str:
        if self.nm_state:
            return self.nm_state
        if self.carrier:
            return "activo"
        return "desconectado" if self.state == "down" else "desconocido"


def _kind_from(ip_link: dict[str, Any], name: str) -> str:
    """Deduce el tipo de interfaz combinando info_kind y el nombre."""
    info = ip_link.get("linkinfo") or {}
    info_kind = (info.get("info_kind") or "").lower()
    if info_kind:
        mapping = {
            "bridge": "bridge", "bond": "bond", "vlan": "vlan",
            "tun": "tun", "tap": "tap", "wireguard": "wireguard",
            "veth": "veth", "dummy": "dummy", "team": "bond",
            "vrf": "vrf", "macvlan": "macvlan", "ipvlan": "vlan",
        }
        if info_kind in mapping:
            return mapping[info_kind]
        if info_kind:
            return info_kind

    for prefix, kind in _KIND_BY_NAME.items():
        if name.startswith(prefix):
            return kind
    return "unknown"


def _sysfs_read(iface: str, *parts: str) -> str:
    path = SYSFS_NET / iface
    for p in parts:
        path = path / p
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _sysfs_driver(iface: str) -> str:
    """Nombre del driver; ``device/driver`` es un symlink a un directorio."""
    link = SYSFS_NET / iface / "device" / "driver"
    try:
        if not link.exists():
            return ""
        return Path(os.path.realpath(link)).name
    except OSError:
        return ""


def _nm_devices() -> dict[str, dict[str, str]]:
    """Estado de NetworkManager por dispositivo (opcional)."""
    out = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"])
    result: dict[str, dict[str, str]] = {}
    for line in out.splitlines():
        if ":" not in line:
            continue
        parts = line.split(":")
        if len(parts) < 4:
            continue
        dev, dtype, state, conn = parts[0], parts[1], parts[2], ":".join(parts[3:])
        result[dev] = {"type": dtype, "state": state, "connection": conn}
    return result


def _nm_details(iface: str) -> tuple[list[str], list[str]]:
    """Devuelve (puertas de enlace, DNS) de un dispositivo."""
    out = _run(["nmcli", "-t", "-f", "IP4.GATEWAY,IP6.GATEWAY,IP4.DNS,IP6.DNS",
                "device", "show", iface])
    gateways: list[str] = []
    dns: list[str] = []
    for line in out.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().upper()
        value = value.strip()
        if not value:
            continue
        if key.endswith("GATEWAY"):
            gateways.append(value)
        elif key.endswith("DNS"):
            dns.append(value)
    return gateways, dns


def list_interfaces(include_down: bool = True) -> list[NetIface]:
    """Devuelve **todas** las interfaces del sistema, incluidas las unplugged.

    La lista se recalcula en cada llamada, así que una tarjeta USB o un
    adaptador Thunderbolt conectado después aparece automáticamente.
    """
    links = _run_json(["ip", "-j", "-d", "link", "show"])
    addrs = _run_json(["ip", "-j", "addr", "show"])
    nm = _nm_devices()

    addr_by_if: dict[str, list[Addr]] = {}
    for entry in addrs:
        name = entry.get("ifname", "")
        bucket = addr_by_if.setdefault(name, [])
        for info in entry.get("addr_info", []):
            fam = info.get("family", "")
            if fam not in ("inet", "inet6"):
                continue
            bucket.append(Addr(family=fam,
                               address=info.get("local", ""),
                               prefix=int(info.get("prefixlen", 0) or 0),
                               scope=info.get("scope", "")))

    interfaces: list[NetIface] = []
    for link in links:
        name = link.get("ifname", "")
        if not name:
            continue

        flags = link.get("flags", []) or []
        oper = link.get("operstate", "unknown")
        state = "up" if "UP" in flags else ("down" if oper == "down" else oper)
        if not include_down and state != "up":
            continue

        kind = _kind_from(link, name)
        driver = _sysfs_driver(name)

        # Detección de Wi-Fi por sysfs (independiente del nombre)
        if (SYSFS_NET / name / "wireless").exists() or (SYSFS_NET / name / "phy80211").exists():
            kind = "wifi"
        elif kind == "unknown" and driver in ("iwlwifi", "ath9k", "ath10k_pci",
                                              "rtw88_pci", "rtw89_pci", "mt7921e",
                                              "brcmfmac", "rtl8xx8u", "iwd"):
            kind = "wifi"
        elif kind == "unknown" and driver in ("bridge", "dummy", "veth", "wireguard",
                                              "tun", "tap", "macvlan", "vrf"):
            kind = driver

        speed_raw = _sysfs_read(name, "speed")
        try:
            speed = int(speed_raw) if speed_raw and int(speed_raw) > 0 else 0
        except ValueError:
            speed = 0

        carrier_raw = _sysfs_read(name, "carrier")
        carrier = carrier_raw == "1"

        try:
            mtu = int(link.get("mtu", 0) or 0)
        except (TypeError, ValueError):
            mtu = 0

        info = link.get("linkinfo") or {}
        slaves = [s.get("ifname", "") for s in (info.get("info_slave") or []) if s.get("ifname")]

        master = ""
        for candidate in _link_masters(link):
            master = candidate

        nm_info = nm.get(name, {})
        gateways, dns = _nm_details(name) if nm_info else ([], [])

        interfaces.append(NetIface(
            name=name,
            ifindex=int(link.get("ifindex", 0) or 0),
            kind=kind,
            driver=driver,
            mac=link.get("address", "") or "",
            mtu=mtu,
            state=state,
            carrier=carrier,
            speed=speed,
            duplex=_sysfs_read(name, "duplex"),
            addresses=addr_by_if.get(name, []),
            gateways=gateways,
            dns=dns,
            nm_connection=nm_info.get("connection", ""),
            nm_type=nm_info.get("type", ""),
            nm_state=nm_info.get("state", ""),
            slaves=slaves,
            master=master,
            sysfs_path=str(SYSFS_NET / name),
        ))

    # Interfaces que sysfs conoce pero ``ip`` no reporta (raro, pero posible)
    known = {i.name for i in interfaces}
    try:
        for entry in os.listdir(SYSFS_NET):
            if entry in known:
                continue
            interfaces.append(NetIface(
                name=entry,
                kind=_kind_from({}, entry),
                driver=_sysfs_driver(entry),
                mac=_sysfs_read(entry, "address"),
                state="up" if _sysfs_read(entry, "operstate") == "up" else "down",
            ))
    except OSError:
        pass

    interfaces.sort(key=lambda i: (not i.is_virtual, i.kind != "ethernet",
                                   not i.is_wireless, i.name))
    return interfaces


def _link_masters(link: dict[str, Any]) -> list[str]:
    master = link.get("master")
    return [master] if master else []


def default_interface() -> str | None:
    """Interfaz con salida a Internet por defecto."""
    for entry in _run_json(["ip", "-j", "route", "show", "default"]):
        if entry.get("dev"):
            return entry["dev"]
    for iface in list_interfaces():
        if iface.carrier and iface.ipv4:
            return iface.name
    return None


def interface_names() -> list[str]:
    return [i.name for i in list_interfaces()]


def find_interface(name: str) -> NetIface | None:
    for iface in list_interfaces():
        if iface.name == name:
            return iface
    return None


def interface_watch(callback):
    """Observa ``/sys/class/net`` y llama a ``callback`` al cambiar.

    Devuelve el ``Gio.FileMonitor`` (o ``None`` si no se pudo crear).
    Detecta la conexión/desconexión física de adaptadores USB, Thunderbolt,
    ranuras M.2, etc.
    """
    try:
        from gi.repository import Gio, GLib
    except ImportError:
        return None

    try:
        monitor = Gio.File.new_for_path(str(SYSFS_NET)).monitor_directory(
            Gio.FileMonitorFlags.WATCH_MOVES, None)
    except GLib.Error:
        return None

    def _on_changed(_m, _f, _other, event):
        if event in (Gio.FileMonitorEvent.CREATED, Gio.FileMonitorEvent.DELETED,
                     Gio.FileMonitorEvent.CHANGED, Gio.FileMonitorEvent.MOVED_IN,
                     Gio.FileMonitorEvent.MOVED_OUT):
            GLib.idle_add(callback)

    monitor.connect("changed", _on_changed)
    return monitor


def routes_for(iface: str) -> list[str]:
    entries = []
    for entry in _run_json(["ip", "-j", "route", "show", "dev", iface]):
        entries.append(f"{entry.get('dst', 'default')} via {entry.get('gateway', '-')} "
                       f"dev {iface}")
    return entries


def neighbour_table() -> list[dict[str, str]]:
    """Tabla ARP/NDP del kernel."""
    out = _run_json(["ip", "-j", "neigh", "show"])
    rows = []
    for entry in out:
        rows.append({
            "ifname": entry.get("dev", ""),
            "address": entry.get("dst", ""),
            "type": entry.get("type", ""),
            "state": entry.get("state", ""),
            "device": entry.get("dev", ""),
        })
    return rows


def wifi_networks(iface: str) -> list[dict[str, str]]:
    """Redes Wi-Fi alrededor (usa NetworkManager)."""
    out = _run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE,CHAN,FREQ",
                "device", "wifi", "list", "ifname", iface])
    rows = []
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) < 4:
            continue
        rows.append({
            "ssid": parts[0],
            "signal": parts[1],
            "security": parts[2],
            "in_use": parts[3] == "*",
            "channel": parts[4] if len(parts) > 4 else "",
            "freq": parts[5] if len(parts) > 5 else "",
        })
    return rows
