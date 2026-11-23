# Cómo contribuir en NetTerm

Gracias por querer mejorar **NetTerm**, la terminal avanzada y alternativa
nativa a MobaXterm en Linux.

## Puesta en marcha

```bash
git clone git@github.com:<tu-usuario>/netterm.git
cd netterm

python3 -m venv --system-site-packages .venv
.venv/bin/pip install paramiko pyserial cryptography

./packaging/fetch-vendor.sh      # tipografías GI de VTE sin root
```

Para ejecutar:

```bash
export GI_TYPELIB_PATH=$PWD/vendor/usr/lib64/girepository-1.0
export LD_LIBRARY_PATH=$PWD/vendor/usr/lib64
.venv/bin/python -m netterm
```

O bien instala el paquete del sistema y ya no necesitas nada de esto:

```bash
sudo dnf install vte291-gtk4 python3-paramiko python3-pyserial python3-cryptography
```

## Antes de enviar un cambio

```bash
.venv/bin/python -m compileall -q netterm
export GI_TYPELIB_PATH=$PWD/vendor/usr/lib64/girepository-1.0
export LD_LIBRARY_PATH=$PWD/vendor/usr/lib64
xvfb-run -a .venv/bin/python -u tests/test_functional.py
```

Las pruebas deben terminar con `0 fallidas`. También conviene comprobar que el
RPM sigue construyéndose:

```bash
./packaging/build-rpm.sh
```

## Estilo del código

- Python con `from __future__ import annotations` y tipado en las firmas.
- 4 espacios, líneas de 100 caracteres como máximo.
- Docstrings y comentarios **en español**.
- Sin dependencias nuevas si puede evitarse: el proyecto usa lo que ya trae
  la distribución (GTK4, libadwaita, VTE) más `paramiko`, `pyserial` y
  `cryptography`.
- Nada de rutas absolutas ni de rutas del entorno de desarrollo.

## Traducciones

La interfaz se localiza con `netterm/i18n.py`:

```python
from .i18n import tr

boton = Gtk.Button(label=tr("New SSH session"))
```

- El **original en inglés** es la clave del catálogo.
- Cada módulo de `netterm/locale/` aporta su diccionario `STRINGS`.
- Para añadir un idioma: crea `netterm/locale/en.py` con las traducciones
  correspondientes y selecciona el idioma con `NETTERM_LANG=en`.

Si añades una cadena a la interfaz, añade también su traducción; si no,
`tr()` devolverá el texto original y la interfaz seguirá funcionando.

## Estructura

| Módulo | Responsabilidad |
|---|---|
| `netterm/app.py` | aplicación, acciones globales, menús |
| `netterm/window.py` | ventana principal, menubar, acciones de ventana |
| `netterm/sidebar.py` | panel lateral (sesiones / herramientas / macros / SFTP) |
| `netterm/terminal.py` | terminales VTE: local, SSH, serie, macros |
| `netterm/netif.py` | enumeración dinámica de interfaces de red |
| `netterm/netops.py` | ping, traceroute, nmap, barridos |
| `netterm/sftp.py` | explorador SFTP |
| `netterm/editor.py` | editor remoto con resaltado |
| `netterm/syntax.py` | motor de resaltado de sintaxis |
| `netterm/servers.py` | servidores embebidos |
| `netterm/tunnels.py` | túneles SSH |
| `netterm/packages.py` | gestor de paquetes sobre `dnf` |
| `netterm/locale/` | catálogos de traducción |

## Commit y pull request

- Un commit por cambio, con mensaje en imperativo y resumen de una línea.
- Si el cambio toca la interfaz, añade o actualiza la traducción.
- Si el cambio es grande, ábrelo primero como *issue* para discutirlo.

## Licencia

Al enviar código aceptas que se publique bajo la licencia del proyecto
(GPL-3.0-or-later). Si tu aportación es una obra que exige cesión de derechos
de autor, indícalo en el pull request.

## Seguridad

No abras un issue público para vulnerabilidades. Escribe al equipo de
mantenimiento por correo y.publica el aviso tras una corrección.
