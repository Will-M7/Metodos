#!/usr/bin/env bash
# Ayudante elevado: sólo paquetes oficiales, sin arrancar un SSH general nuevo.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Este ayudante requiere sudo.' >&2; exit 1; }
need_tail=false;need_node=false
for argument in "$@"; do
    case "$argument" in --tailscale) need_tail=true;; --node) need_node=true;; *) exit 2;; esac
done
packages=()
for package in python3 python3-venv python3-pip octave openssh-client openssh-server ca-certificates curl; do
    [[ $(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true) == 'install ok installed' ]] || packages+=("$package")
done
if $need_node; then packages+=(nodejs npm); fi
new_ssh=false;own_policy=false
cleanup() {
    if $new_ssh; then
        # Estas unidades no existían antes de esta instalación. Nunca detener SSH preexistente.
        systemctl disable --now ssh.service ssh.socket >/dev/null 2>&1 || true
    fi
    if $own_policy && [[ -f /usr/sbin/policy-rc.d ]] && grep -qx '# metodos-install-no-service-start' /usr/sbin/policy-rc.d; then
        rm -- /usr/sbin/policy-rc.d
    fi
}
trap cleanup EXIT
if [[ " ${packages[*]} " == *' openssh-server '* ]]; then
    if systemctl cat ssh.service >/dev/null 2>&1 || systemctl cat ssh.socket >/dev/null 2>&1; then
        echo 'Paquete SSH ausente pero existe una unidad ajena: se conserva; instalar el componente con el administrador.' >&2; exit 1
    fi
    new_ssh=true
    if [[ -e /usr/sbin/policy-rc.d ]]; then
        policy_status=0
        /usr/sbin/policy-rc.d ssh start || policy_status=$?
        [[ $policy_status -eq 101 ]] || { echo 'La política existente permitiría arrancar SSH general; no se modifica.' >&2; exit 1; }
    else
        (set -o noclobber; printf '#!/bin/sh\n# metodos-install-no-service-start\nexit 101\n' > /usr/sbin/policy-rc.d)
        own_policy=true;chmod 755 /usr/sbin/policy-rc.d
    fi
fi
if ((${#packages[@]})); then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${packages[@]}"
fi
if $need_tail; then
    . /etc/os-release
    [[ $ID == ubuntu && ${VERSION_CODENAME:-} =~ ^[a-z]+$ ]] || { echo 'Se requiere Ubuntu con codename conocido.' >&2; exit 1; }
    key=/usr/share/keyrings/metodos-tailscale.gpg
    list=/etc/apt/sources.list.d/metodos-tailscale.list
    temp=$(mktemp -d)
    trap 'cleanup; rm -rf -- "$temp"' EXIT
    curl --proto '=https' --tlsv1.2 --fail --show-error --location "https://pkgs.tailscale.com/stable/ubuntu/${VERSION_CODENAME}.noarmor.gpg" -o "$temp/key"
    [[ -s $temp/key ]] || exit 1
    printf 'deb [signed-by=%s] https://pkgs.tailscale.com/stable/ubuntu %s main\n' "$key" "$VERSION_CODENAME" > "$temp/list"
    if [[ -e $key ]]; then cmp -s "$temp/key" "$key" || { echo 'Keyring previo distinto; conservado.' >&2; exit 1; }; else install -m 644 "$temp/key" "$key"; fi
    if [[ -e $list ]]; then cmp -s "$temp/list" "$list" || { echo 'Fuente apt previa distinta; conservada.' >&2; exit 1; }; else install -m 644 "$temp/list" "$list"; fi
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tailscale
fi
