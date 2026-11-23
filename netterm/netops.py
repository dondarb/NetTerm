"""Ejecución de herramientas de red y utilidades de diagnóstico.

Este módulo envuelve las utilidades de línea de comandos habituales en un
diagnóstico de red (``ping``, ``fping``, ``traceroute``, ``mtr``, ``nmap``,
``ss``, ``iperf3``, ``curl``...) y ofrece además algunas comprobaciones
escritas en Python puro que no dependen de ningún binario externo (escaneo de
puertos TCP/UDP, resumen de interfaces...).

Todas las funciones que lanzan un proceso devuelven un :class:`CommandRunner`
**sin ejecutar**: es el llamante quien decide cuándo arrancarlo (``start()``) y
cómo consumir su salida (``lines()`` o ``read_all()``).  Si la herramienta no
está instalada en el sistema se devuelve igualmente un ``CommandRunner``, pero
con un comando ``sh`` que informa del error, de forma que la interfaz siempre
recibe un mensaje legible en lugar de una excepción.

Para los datos que no necesitan procesos (interfaces, rutas, tabla ARP, redes
Wi-Fi) se reutiliza el módulo :mod:`netterm.netif`, que interroga al kernel.
"""

from __future__ import annotations

import ipaddress
import os
import shlex
import shutil
import subprocess
import threading
from collections.abc import Iterator

from . import netif

# ---------------------------------------------------------------------------
# Ejecución de comandos
# ---------------------------------------------------------------------------


class CommandRunner:
    """Ejecuta un comando externo y expone su salida línea a línea.

    El proceso se lanza con ``stdout`` y ``stderr`` combinados, en modo texto y
    con el búfer de una línea, de modo que las líneas llegan al consumidor en
    cuanto las produce el proceso.  Un hilo lector se encarga de ir vaciando
    el flujo para que la interfaz pueda refrescarse sin bloquearse.
    """

    def __init__(self, cmd: list[str], cwd: str = "", env: dict[str, str] | None = None,
                 label: str = "", needs_root: bool = False):
        self.cmd = cmd                 # argv completo (para mostrarlo en la UI)
        self.label = label or cmd[0]   # nombre corto legible
        self.needs_root = needs_root
        self.returncode: int | None = None
        self.output: list[str] = []    # todo lo leído, para el log
        self.cwd = cwd
        self.env = env
        # Límite de ejecución opcional (segundos).  0 significa "sin límite".
        self.timeout: float = 0.0
        self._proc: subprocess.Popen[str] | None = None
        self._cond = threading.Condition()
        self._eof = False
        self._timer: threading.Timer | None = None

    # -- ciclo de vida ------------------------------------------------
    def start(self) -> None:
        """Arranca el proceso capturando stdout y stderr juntos."""
        if self._proc is not None and self._proc.poll() is None:
            return
        environ = None
        if self.env:
            environ = {**os.environ, **self.env}
        self.output = []
        self.returncode = None
        with self._cond:
            self._eof = False
            self._cond.notify_all()
        try:
            self._proc = subprocess.Popen(
                self.cmd,
                cwd=self.cwd or None,
                env=environ,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            with self._cond:
                self.output.append(f"no se pudo ejecutar {self.label}: {exc}\n")
                self._eof = True
                self._cond.notify_all()
            return
        reader = threading.Thread(target=self._reader, daemon=True, name=f"cmd-{self.label}")
        reader.start()
        if self.timeout > 0:
            self._timer = threading.Timer(self.timeout, self.stop)
            self._timer.daemon = True
            self._timer.start()

    def _reader(self) -> None:
        """Hilo que lee el flujo del proceso y lo guarda en ``output``."""
        proc = self._proc
        stream = proc.stdout if proc is not None else None
        try:
            if stream is not None:
                for raw in stream:
                    with self._cond:
                        self.output.append(raw)
                        self._cond.notify_all()
        except (OSError, ValueError):
            pass
        finally:
            if proc is not None:
                try:
                    self.returncode = proc.wait()
                except (OSError, ValueError):
                    pass
            if self._timer is not None:
                self._timer.cancel()
            with self._cond:
                self._eof = True
                self._cond.notify_all()

    def stop(self) -> None:
        """Detiene el proceso: primero SIGTERM y, si resiste, SIGKILL."""
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
        except OSError:
            return
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass

    def wait(self, timeout: float | None = None) -> int | None:
        """Espera a que el proceso termine y devuelve su código de salida."""
        proc = self._proc
        if proc is None:
            return self.returncode
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    # -- consumo de la salida -----------------------------------------
    def lines(self) -> Iterator[str]:
        """Generador bloqueante que reproduce la salida del comando.

        Cada elemento es una línea tal cual se lee del proceso (con su salto
        de línea).  Cuando el proceso termina se emite una última línea vacía
        para marcar el final del flujo, de modo que el consumidor pueda
        distinguir "terminado" de "todavía no ha salido nada".
        """
        if self._proc is None:
            self.start()
        index = 0
        while True:
            with self._cond:
                while index >= len(self.output) and not self._eof:
                    self._cond.wait(0.2)
                if index >= len(self.output) and self._eof:
                    break
                line = self.output[index]
                index += 1
            yield line
        yield ""

    def read_all(self) -> str:
        """Ejecuta el comando y devuelve toda la salida (bloqueante)."""
        self.start()
        for _ in self.lines():
            pass
        return "".join(self.output)

    @property
    def running(self) -> bool:
        """``True`` mientras el proceso siga vivo."""
        proc = self._proc
        return proc is not None and proc.poll() is None

    @property
    def command_line(self) -> str:
        """El comando tal y como se puede copiar y pegar en una terminal."""
        return " ".join(shlex.quote(part) for part in self.cmd)

    def __repr__(self) -> str:  # pragma: no cover - ayuda en depuración
        return f"<CommandRunner {self.label}: {self.command_line}>"


def missing_command(binary: str) -> CommandRunner:
    """Devuelve un runner que informa de que una herramienta no está instalada."""
    return CommandRunner(
        ["sh", "-c", f"echo '{binary} no está instalado' >&2; exit 127"],
        label=binary,
    )


def _have(binary: str) -> bool:
    """¿Está disponible la herramienta en el ``PATH``?"""
    return bool(shutil.which(binary))


# ---------------------------------------------------------------------------
# Utilidades de red
# ---------------------------------------------------------------------------


def ping(target: str, iface: str = "", count: int = 4, size: int = 56,
         timeout: int = 2, ipv6: bool = False) -> CommandRunner:
    """Lanza ``ping`` contra un objetivo.

    En Linux moderno ``ping`` funciona sin privilegios (SOCK_DGRAM y
    ``net.ipv4.ping_group_range``), así que no hace falta ni ``sudo`` ni
    ``setcap``.  Para fijar la interfaz se usa ``-I``, que admite tanto el
    nombre de la interfaz como su dirección IP.
    """
    if not _have("ping"):
        return missing_command("ping")
    cmd = ["ping", "-c", str(max(1, count)), "-W", str(max(1, timeout)),
           "-s", str(max(8, size))]
    if ipv6:
        cmd.append("-6")
    if iface:
        cmd += ["-I", iface]
    cmd.append(target)
    return CommandRunner(cmd, label="ping")


def _cidr_hosts(cidr: str, limit: int = 1024) -> list[str]:
    """Direcciones útiles de una red CIDR (con un tope para no explode)."""
    try:
        network = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return []
    hosts: list[str] = []
    for host in network.hosts():
        hosts.append(str(host))
        if len(hosts) >= limit:
            break
    return hosts


def _range_hosts(spec: str) -> list[str]:
    """Expande un rango explícito tipo ``192.168.1.10-20`` o ``10-192.168.1.20``."""
    base, _, last = spec.partition("-")
    try:
        first = ipaddress.ip_address(base)
    except ValueError:
        return []
    end: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
    try:
        end = ipaddress.ip_address(last)
    except ValueError:
        # Forma abreviada "192.168.1.10-20": el final es el último octeto.
        prefix, _, _octet = base.rpartition(".")
        if prefix and last.isdigit():
            try:
                end = ipaddress.ip_address(f"{prefix}.{int(last)}")
            except ValueError:
                return []
    if end is None or int(end) < int(first):
        return []
    return [str(ipaddress.ip_address(i)) for i in range(int(first), int(end) + 1)]


def ping_sweep(cidr: str, iface: str = "", timeout: int = 1) -> CommandRunner:
    """Barrido de una red: comprueba qué direcciones responden.

    Acepta ``192.168.1.0/24`` o ``192.168.1.0/24,192.168.1.10-20``.  Si
    ``fping`` está instalado se usa (es mucho más rápido); si no, se recurre a
    un bucle POSIX con el ``ping`` del sistema que va imprimiendo una línea por
    host conforme va respondiendo.
    """
    parts = [part.strip() for part in cidr.split(",") if part.strip()]
    if not parts:
        return missing_command("ping")

    if _have("fping"):
        # fping espera el tiempo de espera en milisegundos.
        cmd = ["fping", "-a", "-q", "-r", "1", "-W", str(max(1, int(timeout * 1000)))]
        if len(parts) == 1 and "/" in parts[0]:
            # Una sola red: se genera el rango con -g (más rápido que listar hosts).
            cmd += ["-g", parts[0]]
        else:
            # Rangos o varias redes: se pasan los hosts uno a uno.
            for part in parts:
                if "/" in part:
                    cmd += _cidr_hosts(part)
                else:
                    cmd += _range_hosts(part) or [part]
        return CommandRunner(cmd, label="ping sweep")

    hosts: list[str] = []
    for part in parts:
        if "/" in part:
            hosts += _cidr_hosts(part)
        else:
            hosts += _range_hosts(part) or [part]
    if not hosts or not _have("ping"):
        return missing_command("ping")

    iface_arg = f" -I {shlex.quote(iface)}" if iface else ""
    host_list = " ".join(shlex.quote(host) for host in hosts)
    script = "\n".join((
        f"for ip in {host_list}; do",
        f"  ping -c 1 -W {max(1, timeout)}{iface_arg} $ip 2>/dev/null >/dev/null "
        f"&& echo $ip responde || echo $ip sin respuesta",
        "done",
    ))
    return CommandRunner(["sh", "-c", script], label="ping sweep")


def traceroute(target: str, iface: str = "", ipv6: bool = False) -> CommandRunner:
    """Lanza ``traceroute`` en modo numérico (sin resolución de nombres)."""
    if ipv6:
        if _have("traceroute6"):
            cmd = ["traceroute6", "-n"]
        elif _have("traceroute"):
            cmd = ["traceroute", "-6", "-n"]
        else:
            return missing_command("traceroute")
    else:
        if not _have("traceroute"):
            return missing_command("traceroute")
        cmd = ["traceroute", "-n"]
    if iface:
        cmd += ["-I", iface]
    cmd.append(target)
    return CommandRunner(cmd, label="traceroute")


def mtr(target: str, iface: str = "", cycles: int = 5) -> CommandRunner:
    """Lanza ``mtr`` (combo de ping y traceroute).  Si no existe, cae a traceroute."""
    if _have("mtr"):
        cmd = ["mtr", "-n", "-c", str(max(1, cycles))]
        if iface:
            cmd += ["-I", iface]
        cmd.append(target)
        return CommandRunner(cmd, label="mtr")
    return traceroute(target, iface=iface)


def nmap_scan(target: str, iface: str = "", ports: str = "",
              extra_args: str = "") -> CommandRunner:
    """Lanza ``nmap`` con la interfaz y el rango de puertos opcionales."""
    if not _have("nmap"):
        return missing_command("nmap")
    cmd = ["nmap"]
    if iface:
        cmd += ["-e", iface]
    if ports:
        cmd += ["-p", ports]
    if extra_args:
        cmd += shlex.split(extra_args)
    cmd.append(target)
    return CommandRunner(cmd, label="nmap")


# -- Escaneo de puertos en Python puro --------------------------------------

_TCP_SCAN_SCRIPT = r'''
import socket
import sys

host = sys.argv[1]
ports = sys.argv[2]
timeout = float(sys.argv[3])


def parse_ports(spec):
    result = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            low, _, high = chunk.partition("-")
            try:
                first = int(low)
                last = int(high)
            except ValueError:
                continue
            if first > last:
                first, last = last, first
            result.extend(range(first, last + 1))
        else:
            try:
                result.append(int(chunk))
            except ValueError:
                continue
    return result


print("scaneo de puertos TCP de " + host)
for port in parse_ports(ports):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        print("puerto %d abierto" % port)
    except OSError:
        print("puerto %d cerrado" % port)
    finally:
        sock.close()
'''

_UDP_SCAN_SCRIPT = r'''
import socket
import sys

host = sys.argv[1]
ports = sys.argv[2]
timeout = float(sys.argv[3])


def parse_ports(spec):
    result = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            low, _, high = chunk.partition("-")
            try:
                first = int(low)
                last = int(high)
            except ValueError:
                continue
            if first > last:
                first, last = last, first
            result.extend(range(first, last + 1))
        else:
            try:
                result.append(int(chunk))
            except ValueError:
                continue
    return result


print("scaneo de puertos UDP de " + host)
for port in parse_ports(ports):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        sock.send(b"")
        try:
            sock.recv(1)
        except ConnectionRefusedError:
            raise
        except socket.timeout:
            pass
        print("puerto %d abierto" % port)
    except OSError:
        print("puerto %d cerrado" % port)
    finally:
        sock.close()
'''


def tcp_scan(host: str, ports: str = "1-1024", timeout: float = 0.4) -> CommandRunner:
    """Escaneo de puertos TCP con sockets de Python (no depende de nmap).

    Acepta ``"1-1024"``, ``"22,80,443"`` o ``"80-90,443"`` y va informando
    ``puerto N abierto`` o ``puerto N cerrado`` según el resultado.
    """
    if not _have("python3"):
        return missing_command("python3")
    cmd = ["python3", "-c", _TCP_SCAN_SCRIPT, host, ports, str(timeout)]
    return CommandRunner(cmd, label="tcp_scan")


def udp_scan(host: str, ports: str = "1-1024", timeout: float = 0.4) -> CommandRunner:
    """Escaneo de puertos UDP: envía un datagrama vacío e informa del estado."""
    if not _have("python3"):
        return missing_command("python3")
    cmd = ["python3", "-c", _UDP_SCAN_SCRIPT, host, ports, str(timeout)]
    return CommandRunner(cmd, label="udp_scan")


# -- Consultas de nombre, sockets y rutas -----------------------------------


def dns_lookup(name: str) -> CommandRunner:
    """Resuelve un nombre con ``getent hosts`` y, si existe, con ``dig +short``."""
    if not _have("getent"):
        return missing_command("getent")
    quoted = shlex.quote(name)
    script = f"getent hosts {quoted}"
    if _have("dig"):
        script += f"; echo '--- dig +short ---'; dig +short {quoted}"
    return CommandRunner(["sh", "-c", script], label="dns")


def whois_query(name: str) -> CommandRunner:
    """Consulta WHOIS de un dominio o una dirección IP."""
    if not _have("whois"):
        return missing_command("whois")
    return CommandRunner(["whois", name], label="whois")


def list_sockets() -> CommandRunner:
    """Sockets abiertos del sistema (``ss -tulpn``)."""
    if not _have("ss"):
        return missing_command("ss")
    return CommandRunner(["ss", "-tulpn"], label="sockets")


def list_routes() -> CommandRunner:
    """Tabla de rutas del kernel (``ip route show``)."""
    if not _have("ip"):
        return missing_command("ip")
    return CommandRunner(["ip", "route", "show"], label="routes")


def arp_entries() -> list[dict[str, str]]:
    """Tabla ARP/NDP del kernel (delega en :mod:`netterm.netif`)."""
    return netif.neighbour_table()


def wifi_scan(iface: str) -> list[dict[str, str]]:
    """Redes Wi-Fi alrededor de una interfaz (delega en :mod:`netterm.netif`)."""
    return netif.wifi_networks(iface)


# -- Pruebas de rendimiento --------------------------------------------------


def _interface_address(iface: str) -> str:
    """Dirección IPv4 de una interfaz (o cadena vacía si no se conoce)."""
    try:
        for entry in netif.list_interfaces():
            if entry.name == iface:
                return entry.primary_ipv4
    except OSError:
        pass
    return ""


def bandwidth_test(target: str, iface: str = "", port: int = 5201,
                   seconds: int = 10) -> CommandRunner:
    """Prueba de ancho de banda con ``iperf3`` en modo cliente."""
    if not _have("iperf3"):
        return missing_command("iperf3")
    cmd = ["iperf3", "-c", target, "-t", str(max(1, seconds)), "-p", str(port)]
    if iface:
        address = _interface_address(iface)
        if address:
            cmd += ["-B", address]
    return CommandRunner(cmd, label="iperf3")


_CURL_FORMAT = ("Velocidad: %{speed_download} B/s\n"
                "Tiempo total: %{time_total} s\n"
                "Descargado: %{size_download} bytes\n"
                "Codigo HTTP: %{http_code}\n")


def download_test(url: str) -> CommandRunner:
    """Descarga una URL con ``curl`` midiendo la velocidad."""
    if not _have("curl"):
        return missing_command("curl")
    cmd = ["curl", "-L", "-s", "-o", "/dev/null", "-w", _CURL_FORMAT, url]
    return CommandRunner(cmd, label="descarga")


def speedtest() -> CommandRunner:
    """Medida de velocidad con el servidor público de Cloudflare."""
    if not _have("curl"):
        return missing_command("curl")
    url = "https://speed.cloudflare.com/__down?bytes=25000000"
    cmd = ["curl", "-s", "-o", "/dev/null", "-w", _CURL_FORMAT, url]
    return CommandRunner(cmd, label="speedtest")


# -- Resúmenes basados en netif ----------------------------------------------


def interface_summary() -> list[dict[str, str]]:
    """Filas planas con un resumen de cada interfaz, listas para una tabla."""
    rows: list[dict[str, str]] = []
    for entry in netif.list_interfaces():
        rows.append({
            "name": entry.name,
            "kind": entry.kind,
            "state": entry.state,
            "ipv4": entry.primary_ipv4,
            "mac": entry.mac,
            "mtu": str(entry.mtu),
            "speed": str(entry.speed),
            "driver": entry.driver,
        })
    return rows


def default_interface() -> str:
    """Nombre de la interfaz con salida por defecto (o cadena vacía)."""
    return netif.default_interface() or ""


def interface_routes(iface: str) -> list[str]:
    """Rutas conocidas de una interfaz (delega en :mod:`netterm.netif`)."""
    return netif.routes_for(iface)
