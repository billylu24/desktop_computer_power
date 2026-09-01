#!/usr/bin/env bash
# Installs the validated, volatile Ryzen Raphael + NVIDIA power-profile commands.
set -euo pipefail

readonly ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
readonly SOURCE_DIR=/usr/local/src/ryzen_smu
readonly RYZEN_SMU_REPO=https://github.com/amkillam/ryzen_smu.git
readonly RYZEN_SMU_COMMIT=d2983668300dd2a598e5a7dc40e71ce0678cc270

die() {
  printf 'install.sh: %s\n' "$*" >&2
  exit 1
}

[[ ${EUID} -eq 0 ]] || die 'run as root: sudo ./install.sh'
[[ -f "$ROOT_DIR/scripts/cpu-power" && -f "$ROOT_DIR/scripts/pc-power" && -f "$ROOT_DIR/scripts/ryzen4_ctl.rb" ]] || die 'run from a complete repository checkout'

apt update
apt install -y git dkms build-essential "linux-headers-$(uname -r)" ruby lm-sensors stress-ng

if [[ -e "$SOURCE_DIR/.git" ]]; then
  git -C "$SOURCE_DIR" fetch --depth 1 origin "$RYZEN_SMU_COMMIT"
elif [[ -e "$SOURCE_DIR" ]]; then
  die "$SOURCE_DIR exists but is not a Git checkout; move it aside before installing"
else
  git clone "$RYZEN_SMU_REPO" "$SOURCE_DIR"
fi
git -C "$SOURCE_DIR" checkout --detach "$RYZEN_SMU_COMMIT"
grep -q 'case 0x61:' "$SOURCE_DIR/smu.c" || die 'ryzen_smu source lacks the Raphael (0x61) detection case'
grep -q 'CODENAME_RAPHAEL' "$SOURCE_DIR/smu.c" || die 'ryzen_smu source lacks Raphael support'

make -C "$SOURCE_DIR"
if ! dkms status | grep -q '^ryzen_smu/0.1.7, .*: installed$'; then
  make -C "$SOURCE_DIR" dkms-install
fi

install -d -m 0755 /usr/local/libexec /usr/local/sbin
install -m 0644 "$ROOT_DIR/scripts/ryzen4_ctl.rb" /usr/local/libexec/ryzen4_ctl.rb
install -m 0755 "$ROOT_DIR/scripts/cpu-power" /usr/local/sbin/cpu-power
install -m 0755 "$ROOT_DIR/scripts/pc-power" /usr/local/sbin/pc-power

printf '%s\n' 'Installed. No boot-time power profile was configured.'
printf '%s\n' 'Load the module when needed: sudo modprobe ryzen_smu'
