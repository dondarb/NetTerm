# NetTerm

**Terminal avanzada, alternativa nativa a MobaXterm en Linux.**

Cliente open source de terminal, SSH, SFTP y consola serie.

![NetTerm](docs/netterm.png)

---

## Por qué existe

MobaXterm es un *bundle* propietario de Cygwin + OpenSSH + PuTTY + PuTTYgen +
un servidor X. Todo eso ya existe en Linux de forma nativa y mejor. NetTerm
reproduce **las mismas funciones** apoyándose en las herramientas del sistema
(`ssh`, `openssh`, `dnf`, `nmap`, `pyserial`…), sin emulación de Windows y sin
capas de compatibilidad.

Dos problemas concretos de MobaXterm bajo Wine/Bottles quedan resueltos aquí:

| Problema en Bottles | Causa real | Solución en NetTerm |
|---|---|---|
| El ping no funciona | MobaXterm lo implementa en Delphi con sockets **SOCK_RAW**, que exigen `CAP_NET_RAW`; dentro del Flatpak es imposible | Se usa el `ping` nativo (SOCK_DGRAM ICMP) y un panel de red propio |
| Sin acceso «directo» al dispositivo | Wine emula el puerto serie y el sandbox bloquea los puertos | pyserial habla **termios** del kernel: acceso real a `/dev/ttyUSB*` |

---

## Funciones

### Terminal
* Terminales con pestañas VTE, con shell local (`bash`, `zsh`, `fish`…).
* SSH con **SSH gateway** (ProxyJump), X11-forwarding, compresión, keepalive y
  claves privadas.
* **Telnet**, **Rsh/Rlogin** y **Mosh**.
* **Consola serie RS-232** directa al hardware: baudios, bits de datos, paridad
  y bits de parada configurables.
* Atajos: `Ctrl+Shift+C` copiar, `Ctrl+V` pegar, `Ctrl+F` buscar, `Ctrl+L`
  limpiar, `Ctrl+±` zoom.

### Sesiones
* Árbol de sesiones agrupado y plegable, con filtro de búsqueda.
* Tipos: SSH, Telnet, Rsh, Xdmcp, RDP, VNC, FTP, SFTP, Serial, File, Shell,
  Browser y Mosh (los mismos iconos que MobaXterm).
* Importación desde `~/.ssh/config` y desde el `MobaXterm.ini` de Windows.
* Bóveda de contraseñas con **contraseña maestra** (PBKDF2-HMAC-SHA256 +
  AES/Fernet).

### SFTP
* Navegador gráfico remoto con **arrastrar y soltar** para subir y bajar.
* Creación de directorios, borrado, y editor remoto con **resaltado de
  sintaxis** (shell, Python, C/C++, JSON, YAML, XML, Markdown, JavaScript).

### Herramientas de red
* **Tabla viva de todas las tarjetas de red**: Ethernet, Wi-Fi, bridges,
  bonds, VLANs, túneles, USB… Se recalcula al instante y detecta tarjetas
  conectadas/desconectadas en caliente (monitor de `/sys/class/net`).
  Muestra tipo, estado, IPv4/IPv6, MAC, driver, MTU y velocidad.
* **Ping**, *barrido de subred*, **traceroute**, **mtr**.
* **Escáner** de puertos: nmap y escaneo TCP/UDP propio.
* Tabla ARP/NDP, sockets, rutas, redes Wi-Fi alrededor.

### Extras
* **Multi-ejecución**: la misma orden se escribe en varias terminales a la vez.
* **Macros**: grabación y reproducción de pulsaciones.
* **Servidores embebidos**: HTTP, SFTP, SSH, FTP y Telnet locales.
* **Gestor de paquetes** (tipo MobApt) sobre `dnf`, con `pkexec` para instalar.
* **Gestor de túneles SSH** (local, remoto y SOCKS dinámico).
* Calculadora de **CRC32**.
* Lanzadores para **RDP** (`xfreerdp`), **VNC** (`vncviewer`), **XDMCP**,
  FTP, SFTP y navegador.
* Menú completo al estilo MobaXterm: *Terminal, Sessions, View, X server,
  Tools, Games, Settings, Macros, Help*.

---

## Instalación

### Opción A — RPM (instalación global del sistema)

```bash
cd ~/netterm
./packaging/build-rpm.sh
sudo dnf install ~/rpmbuild/RPMS/noarch/netterm-*.rpm
```

`dnf` resolverá automáticamente las dependencias: `vte291-gtk4` (VTE para
GTK4), `python3-paramiko`, `python3-pyserial` y `python3-cryptography`.
También quedan disponibles los *Recommends*: `nmap`, `traceroute`, `mtr`,
`iperf3`, `mosh`, `tigervnc-viewer` y `xfreerdp`.

Tras instalarlo, NetTerm aparece en el menú de KDE Plasma dentro de
*Sistema* y *Terminal Emulator*, con su icono propio.

El RPM instala:

| Ruta | Contenido |
|---|---|
| `/usr/lib/python3.15/site-packages/netterm/` | el módulo Python |
| `/usr/bin/netterm` | el lanzador |
| `/usr/share/applications/netterm.desktop` | la entrada del menú |
| `/usr/share/icons/hicolor/scalable/apps/netterm.svg` | el icono |
| `/usr/share/doc/netterm/` | la documentación |

### Opción B — instalación por usuario (sin root)

```bash
cd ~/netterm
./packaging/install-user.sh
```

Deja todo en `~/.local/` (`~/.local/bin/netterm`,
`~/.local/lib/python3.15/site-packages/netterm`,
`~/.local/share/applications/`) e incluye una copia local de las tipografías
GI de VTE en `~/.local/share/netterm/vendor/`, para que funcione aunque no
installes nada más. KDE lo ve igualmente en el menú.

Para desinstalar:

```bash
rm -rf ~/.local/lib/python3.15/site-packages/netterm ~/.local/bin/netterm \
       ~/.local/share/applications/netterm.desktop \
       ~/.local/share/icons/hicolor/scalable/apps/netterm.svg \
       ~/.local/share/netterm
```

### Opción C — desde el código

```bash
cd ~/netterm
./netterm.sh
```

El script `netterm.sh` prepara las rutas GI/LD de las tipografías guardadas en
`vendor/` y usa el intérprete del entorno virtual `.venv`.

### Dependencias

Ya vienen resueltas en este equipo:

| Componente | Estado |
|---|---|
| GTK4 4.24 · libadwaita 1.10 | del sistema |
| VTE 3.91 (GTK4) | `vendor/` (RPM extraído localmente, sin root) |
| paramiko · pyserial · cryptography | `.venv` (`pip install --user`) |

Para instalar VTE como paquete del sistema (si tienes permisos):

```bash
sudo dnf install vte291-gtk4
sudo dnf install python3-paramiko python3-pyserial python3-cryptography
```

---

## Uso

| Acción | Atajo |
|---|---|
| Terminal local | `Ctrl+T` |
| Sesión SSH | `Ctrl+Shift+T` |
| Consola serie | `Ctrl+Shift+S` |
| SFTP | `Ctrl+Shift+B` |
| Cerrar pestaña | `Ctrl+W` |
| Buscar en terminal | `Ctrl+F` |

* **Conexión rápida**: escribe `host`, `usuario@host` o `host:puerto` en el
  campo superior y pulsa Intro.
* **Barra lateral**: cuatro pestañas verticales — *Sesiones*, *Herramientas*,
  *Macros* y *SFTP*.

---

## Consola serie

Para hablar con un switch o router por RS-232 hace falta un adaptador
USB-serie (FTDI, CH340 o CP210x):

```bash
# 1. Permisos: añade el grupo dialout y vuelve a iniciar sesión
sudo usermod -aG dialout $USER

# 2. Comprueba que aparece
ls -l /dev/ttyUSB* /dev/ttyACM*
dmesg | tail -5

# 3. Conéctate (9600 8N1 es lo habitual en Cisco)
picocom -b 9600 /dev/ttyUSB0
```

NetTerm detecta los puertos automáticamente, incluidos los que se conecten
después, y permite elegir baudios, bits, paridad y parada.

---

## Estructura

```
netterm/
├── netterm/
│   ├── app.py            Aplicación y acciones globales
│   ├── window.py         Ventana principal, menús, acciones
│   ├── sidebar.py        Panel lateral (sesiones / herramientas / macros / sftp)
│   ├── terminal.py       Terminal VTE: local, SSH, serie, macros, multi-ejec
│   ├── netif.py          Enumeración dinámica de interfaces de red
│   ├── netops.py         Ping, traceroute, nmap, ss, barridos…
│   ├── packages.py       Gestor de paquetes sobre dnf
│   ├── servers.py        Servidores embebidos
│   ├── tunnels.py        Túneles SSH
│   ├── remote.py         Lanzadores RDP/VNC/XDMCP/FTP
│   ├── sftp.py           Explorador SFTP (paramiko)
│   ├── editor.py         Editor remoto con resaltado
│   ├── syntax.py         Motor de resaltado de sintaxis
│   ├── macro.py          Grabación y reproducción de macros
│   ├── multiexec.py      Modo multi-ejecución
│   ├── session.py        Modelo de sesión y túneles
│   ├── config.py         Ajustes y almacén de sesiones
│   ├── secrets.py        Bóveda con contraseña maestra
│   ├── sshconfig.py      Analizador de ~/.ssh/config
│   ├── mobaxterm.py      Importador de sesiones de MobaXterm
│   ├── dialogs.py        Diálogo de sesión
│   ├── prefs.py          Preferencias y «Customizer»
│   ├── tools.py          Panel de herramientas de red
│   └── gobj.py           Utilidades GObject
├── tests/test_functional.py
├── netterm.sh            Lanzador
├── dev.sh                Arranque/parada con fichero de PID
└── focus.py / shot.sh    Utilidades para capturar la ventana
```

---

## Pruebas

```bash
cd ~/netterm
export GI_TYPELIB_PATH=$PWD/vendor/usr/lib64/girepository-1.0
export LD_LIBRARY_PATH=$PWD/vendor/usr/lib64
.venv/bin/python -u tests/test_functional.py
```

Cubre la capa de red, las herramientas, el gestor de paquetes, la bóveda, el
analizador de SSH, la consola serie y la interfaz gráfica.

---

## Licencia

GPL-3.0-or-later. MobaXterm es software propietario de MobaXterm/BMob; este
proyecto es una reimplementación independiente a partir de su lista pública de
funciones, sin usar su código ni sus binarios.
