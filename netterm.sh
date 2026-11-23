#!/bin/bash
# Lanzador de NetTerm.
# Prepara las rutas GI/LD para las tipografías extraídas en vendor/ (VTE)
# y arranca la aplicación con el intérprete del entorno virtual.

set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

export GI_TYPELIB_PATH="$PWD/vendor/usr/lib64/girepository-1.0${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
export LD_LIBRARY_PATH="$PWD/vendor/usr/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

exec "$PY" -m netterm "$@"
