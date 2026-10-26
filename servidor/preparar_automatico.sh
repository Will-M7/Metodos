#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ ${1:-} == --comprobar ]]; then
    shift
    exec python3 -B -m servidor.preparar_automatico --comprobar "$@"
fi
[[ $EUID -ne 0 ]] || { echo 'Ejecutar como propietario (sin sudo delante); se pedirá sudo sólo para lo necesario.' >&2; exit 1; }
. /etc/os-release
[[ $ID == ubuntu ]] || { echo 'Este instalador es para Ubuntu.' >&2; exit 1; }
# Evitar instalar/cambiar nada en un contenedor o sesión sin el bus necesario.
systemctl --user show-environment >/dev/null || { echo 'No se puede acceder a systemd de usuario. Ejecutar en una terminal normal de Ubuntu.' >&2; exit 2; }
if [[ -x $HOME/.local/share/metodos-servidor/codex-cli/node_modules/.bin/codex ]]; then
    export PATH="$HOME/.local/share/metodos-servidor/codex-cli/node_modules/.bin:$PATH"
fi
arguments=()
command -v tailscale >/dev/null || arguments+=(--tailscale)
if ! command -v codex >/dev/null && ! command -v npm >/dev/null; then arguments+=(--node); fi
missing=false
for package in python3-venv python3-pip octave openssh-client openssh-server ca-certificates curl; do
    [[ $(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true) == 'install ok installed' ]] || missing=true
done
if $missing || ((${#arguments[@]})); then sudo bash servidor/dependencias_ubuntu.sh "${arguments[@]}"; fi
if ! systemctl is-enabled --quiet tailscaled || ! tailscale status --json >/dev/null 2>&1; then
    sudo systemctl enable --now tailscaled
fi
systemctl is-enabled --quiet tailscaled || { echo 'Tailscaled no esta habilitado para el arranque.' >&2; exit 2; }
backend=$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin).get("BackendState",""))')
if [[ $backend != Running ]]; then sudo tailscale up; fi
if ! command -v codex >/dev/null; then
    npm install --prefix "$HOME/.local/share/metodos-servidor/codex-cli" '@openai/codex'
    export PATH="$HOME/.local/share/metodos-servidor/codex-cli/node_modules/.bin:$PATH"
fi
if ! codex login status; then codex login; fi
linger=$(loginctl show-user "$(id -un)" -p Linger --value)
if [[ $linger != yes ]]; then sudo loginctl enable-linger "$(id -un)"; fi
[[ $(loginctl show-user "$(id -un)" -p Linger --value) == yes ]] || { echo 'No se confirmó persistencia tras cerrar sesión.' >&2; exit 2; }
exec python3 -B -m servidor.preparar_automatico "$@"
