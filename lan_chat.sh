#!/usr/bin/env bash
# LanChat — lanzador. by Un fantasma en el sistema · https://www.unfantasmaenelsistema.com · MIT
#
#   ./lan_chat.sh                      menú interactivo
#   ./lan_chat.sh serve [opciones]     crear una sala
#   ./lan_chat.sh join IP --nick ana   unirse a una sala
#   ./lan_chat.sh --help               todas las opciones
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for candidate in "${PYTHON:-}" python3 python; do
  [[ -n "$candidate" ]] || continue
  if command -v "$candidate" >/dev/null 2>&1 \
     && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null; then
    exec "$candidate" "$HERE/lanchat.py" "$@"
  fi
done

echo "[-] LanChat necesita Python 3.8 o superior / LanChat needs Python 3.8+" >&2
echo "    sudo apt install -y python3" >&2
exit 1
