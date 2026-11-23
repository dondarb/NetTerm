#!/bin/bash
# Descarga las tipografías GI de VTE (GTK4) sin permisos de administrador.
#
# Fedora 45 no trae instalado el paquete «vte291-gtk4», que aporta la
# tipografía GI «Vte-3.91.typelib» que necesita NetTerm. Este script extrae
# el RPM en ./vendor para que la aplicación funcione en cualquier equipo.
#
# Si prefieres la versión del sistema:  sudo dnf install vte291-gtk4
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

DEST="vendor"
if [ -d "$DEST/usr/lib64/girepository-1.0" ] && \
   [ -f "$DEST/usr/lib64/girepository-1.0/Vte-3.91.typelib" ]; then
    echo "Ya está descargado en $DEST"
    exit 0
fi

command -v rpm2cpio >/dev/null || {
    echo "Se necesita rpm2cpio (paquete 'rpm')."; exit 1; }

mkdir -p "$DEST"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

BASE="https://kojipkgs.fedoraproject.org/packages"
VER="0.84.1"
REL="1.fc45"

fetch() {
    local pkg="$1" arch="$2" dest="$TMP/$pkg.rpm"
    local url="$BASE/$pkg/$VER/$REL/$arch/os/$pkg-$VER-$REL.$arch.rpm"
    echo "==> $pkg ($arch)"
    curl -fsSL -o "$dest" "$url" || {
        echo "    no se pudo descargar: $url"; return 1; }
    rpm2cpio "$dest" | cpio -idm --quiet -D "$DEST"
}

fetch vte291 x86_64
fetch vte291-gtk4 x86_64
fetch simdutf x86_64

echo
echo "Tipografías GI descargadas en $DEST"
ls "$DEST/usr/lib64/girepository-1.0/"
