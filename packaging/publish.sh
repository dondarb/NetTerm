#!/bin/bash
# Publica NetTerm en un repositorio público de GitHub.
#
# El repositorio remoto debe existir y estar vacío. Créalo con:
#     gh repo create netterm --public --description "..."   (con gh CLI)
#   o desde la web: https://github.com/new  (nombre: netterm, sin README)
#
# Después, ejecuta este script.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

REPO="${1:-netterm}"
USERNAME="${GITHUB_USER:-$(git config --global user.name | tr -d ' ' | tr 'A-Z' 'a-z')}"
REMOTE="git@github.com:${USERNAME}/${REPO}.git"

echo "==> Repositorio remoto: $REMOTE"

if git remote get-url origin >/dev/null 2>&1; then
    git remote set-url origin "$REMOTE"
else
    git remote add origin "$REMOTE"
fi

echo "==> Subiendo"
git push -u origin main

echo
echo "==> Etiquetando la versión actual"
VERSION=$(grep -m1 '^Version:' packaging/netterm.spec | awk '{print $2}')
if git rev-parse "v$VERSION" >/dev/null 2>&1; then
    echo "    la etiqueta v$VERSION ya existe"
else
    git tag -a "v$VERSION" -m "NetTerm $VERSION"
    git push origin "v$VERSION"
fi

echo
echo "==> Publicación completada:"
echo "    https://github.com/${USERNAME}/${REPO}"
