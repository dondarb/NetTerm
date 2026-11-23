#!/bin/bash
# Instalación de NetTerm a nivel de usuario (~/.local), sin permisos de root.
#
# Deja la entrada en el menú de aplicaciones de KDE Plasma (y de cualquier
# escritorio que lea ~/.local/share/applications).
#
# Para la instalación global usa el RPM:
#     sudo dnf install ~/rpmbuild/RPMS/noarch/netterm-*.rpm
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

SITE="$HOME/.local/lib/python3.15/site-packages"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"

echo "==> Copiando el módulo Python"
mkdir -p "$SITE"
rm -rf "$SITE/netterm"
cp -r netterm "$SITE/netterm"
find "$SITE/netterm" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || :
python3 -m compileall -q "$SITE/netterm"

echo "==> Instalando el lanzador"
mkdir -p "$BIN"
sed "s|^#!/usr/bin/python3|#!$BIN/../libexec/netterm-python|" /dev/null >/dev/null
cat > "$BIN/netterm" <<EOF
#!/usr/bin/python3
# Lanzador de NetTerm (instalación por usuario).
import os
import sys

os.environ.setdefault("PYTHONWARNINGS", "ignore::DeprecationWarning")

if __name__ == "__main__":
    try:
        from netterm.app import main as app_main
    except ImportError:
        sys.stderr.write(
            "No se encuentra el modulo 'netterm'. "
            "Reinstala con: ~/netterm/packaging/install-user.sh\n")
        raise SystemExit(1)
    raise SystemExit(app_main())
EOF
chmod 0755 "$BIN/netterm"

echo "==> Registrando la entrada de escritorio"
mkdir -p "$APPS" "$ICONS"
sed -e "s|^Exec=.*|Exec=$BIN/netterm|" -e "s|^Icon=.*|Icon=netterm|" \
    data/netterm.desktop > "$APPS/netterm.desktop"
cp data/netterm.svg "$ICONS/netterm.svg"

echo "==> Copiando las tipografías GI locales (VTE)"
# Fedora 45 no trae vte291-gtk4 instalado; se incluye una copia local para
# que NetTerm funcione sin permisos de administrador.
VENDOR="$HOME/.local/share/netterm/vendor"
if [ -d vendor ]; then
    rm -rf "$VENDOR"
    mkdir -p "$VENDOR"
    cp -r vendor/usr "$VENDOR/"
    echo "    $VENDOR"
else
    echo "    (no encontrado: instala vte291-gtk4 con sudo dnf install vte291-gtk4)"
fi

echo "==> Actualizando la base de datos del menú"
update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -f -t "$ICONS" 2>/dev/null || true

echo
echo "NetTerm instalado en el menú de aplicaciones."
echo "  lanzador : $BIN/netterm"
echo "  módulo   : $SITE/netterm"
echo "  entrada  : $APPS/netterm.desktop"
echo
echo "Para desinstalar:"
echo "  rm -rf $SITE/netterm $BIN/netterm $APPS/netterm.desktop $ICONS/netterm.svg"
