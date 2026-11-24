#!/bin/bash
# Construye el RPM de NetTerm sin necesidad de root.
#
# rpmbuild no está instalado como paquete del sistema en este equipo, así que
# se usa la copia local de ~/rpmbuild/rpmroot.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

TOPDIR="$HOME/rpmbuild"
MACRODIR="$TOPDIR/rpmroot/usr/lib/rpm"
RPMBUILD="$TOPDIR/rpmroot/usr/bin/rpmbuild"

# rpmuncompress y amigos no están instalados como paquete del sistema.
export PATH="$TOPDIR/rpmroot/usr/bin:$PATH"

VERSION="$(grep -m1 '^Version:' packaging/netterm.spec | awk '{print $2}')"
RELEASE="$(grep -m1 '^Release:' packaging/netterm.spec | awk '{print $2}')"
DIST="$(. /etc/os-release; echo ".${VERSION_ID}")"
ARCH="$(uname -m)"

TARBALL="$TOPDIR/SOURCES/netterm-${VERSION}.tar.gz"

echo "==> Preparando sources"
mkdir -p "$TOPDIR"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
STAGE="$TOPDIR/BUILD/netterm-${VERSION}"
rm -rf "$STAGE"
mkdir -p "$STAGE"
# Copia sólo lo necesario para construir el paquete.
cp -r netterm "$STAGE/netterm"
cp -r data "$STAGE/data"
cp README.md LICENSE NOTICE "$STAGE/"
mkdir -p "$STAGE/packaging"
cp packaging/netterm.spec "$STAGE/packaging/"
find "$STAGE" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || :
find "$STAGE" -name '*.pyc' -delete 2>/dev/null || :

tar -czf "$TARBALL" -C "$TOPDIR/BUILD" "netterm-${VERSION}"
cp packaging/netterm.spec "$TOPDIR/SPECS/"

echo "==> rpmbuild -ba"
"$RPMBUILD" \
    --define "_rpmmacrodir $MACRODIR" \
    --define "_topdir $TOPDIR" \
    --define "_arch $ARCH" \
    --define "_build_arch $ARCH" \
    --define "dist $DIST" \
    --nodeps \
    --define "python3_sitelib /usr/lib/python3.15/site-packages" \
    --define "__python3 /usr/bin/python3" \
    --define "__rpmuncompress $TOPDIR/rpmroot/usr/bin/rpmuncompress" \
    --define "__brp_compress $MACRODIR/brp-compress" \
    --define "__brp_remove_la_files $MACRODIR/brp-remove-la-files" \
    --define "__brp_strip_comment_note $MACRODIR/brp-strip-comment-note" \
    --define "__brp_strip $MACRODIR/brp-strip" \
    --define "__brp_strip_static_archive $MACRODIR/brp-strip-static-archive" \
    --define "__check_files $MACRODIR/check-files" \
    -ba "$TOPDIR/SPECS/netterm.spec"

RPM=$(ls -t "$TOPDIR"/RPMS/*/netterm-*.rpm 2>/dev/null | head -1)
echo
echo "==> RPM generado: $RPM"
rpm -qip "$RPM" | head -20
echo
echo "==> Contenido:"
rpm -qlp "$RPM" | head -40
echo
echo "Para instalarlo:"
echo "  sudo dnf install $RPM"
