#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
command -v python3 >/dev/null || { echo 'Instalar Python 3.10+ desde paquetes oficiales de Ubuntu.'; exit 1; }
command -v octave >/dev/null || echo 'PENDIENTE: sudo apt install octave'
command -v tailscale >/dev/null || echo 'PENDIENTE: instalar Tailscale desde https://tailscale.com/download/linux y ejecutar tailscale up'
test -x /usr/sbin/sshd || echo 'PENDIENTE: OpenSSH Server. Configurar exclusivamente la instancia privada; no iniciar un SSH publico.'
exec python3 -B -m servidor.preparar --instalar-paquetes --probar-codex "$@"
