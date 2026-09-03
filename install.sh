#!/usr/bin/env bash
# Installs the validated, volatile Ryzen Raphael + NVIDIA power-profile commands.
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
readonly ROOT_DIR
readonly SOURCE_DIR=/usr/local/src/ryzen_smu
readonly RYZEN_SMU_REPO=https://github.com/amkillam/ryzen_smu.git
readonly RYZEN_SMU_COMMIT=d2983668300dd2a598e5a7dc40e71ce0678cc270
readonly GPUTEMPS_SOURCE_DIR=/usr/local/src/gputemps
readonly GPUTEMPS_REPO=https://github.com/ThomasBaruzier/gddr6-core-junction-vram-temps.git
readonly GPUTEMPS_COMMIT=37688e080165aefdf3842889cc5535c6be7ca073

die() {
  printf 'install.sh: %s\n' "$*" >&2
  exit 1
}

[[ ${EUID} -eq 0 ]] || die 'run as root: sudo ./install.sh'
[[ -f "$ROOT_DIR/scripts/cpu-power" && -f "$ROOT_DIR/scripts/pc-power" && -f "$ROOT_DIR/scripts/pc-fand.py" && -f "$ROOT_DIR/scripts/ryzen4_ctl.rb" ]] || die 'run from a complete repository checkout'

apt update
apt install -y git dkms build-essential "linux-headers-$(uname -r)" ruby lm-sensors stress-ng python3 power-profiles-daemon libpci-dev

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

if [[ -e "$GPUTEMPS_SOURCE_DIR/.git" ]]; then
  git -C "$GPUTEMPS_SOURCE_DIR" fetch origin "$GPUTEMPS_COMMIT"
elif [[ -e "$GPUTEMPS_SOURCE_DIR" ]]; then
  die "$GPUTEMPS_SOURCE_DIR exists but is not a Git checkout"
else
  git clone "$GPUTEMPS_REPO" "$GPUTEMPS_SOURCE_DIR"
fi
git -C "$GPUTEMPS_SOURCE_DIR" checkout --detach "$GPUTEMPS_COMMIT"
if git -C "$GPUTEMPS_SOURCE_DIR" apply --check "$ROOT_DIR/patches/gputemps-rtx5070-gb205.patch" 2>/dev/null; then
  git -C "$GPUTEMPS_SOURCE_DIR" apply "$ROOT_DIR/patches/gputemps-rtx5070-gb205.patch"
elif ! git -C "$GPUTEMPS_SOURCE_DIR" apply --reverse --check "$ROOT_DIR/patches/gputemps-rtx5070-gb205.patch" 2>/dev/null; then
  die 'gputemps GB205 patch does not apply cleanly to the pinned source'
fi
make -C "$GPUTEMPS_SOURCE_DIR" clean all

install -d -m 0755 /usr/local/libexec /usr/local/sbin /etc/pc-power /usr/local/share/desktop-computer-power
install -m 0644 "$ROOT_DIR/scripts/ryzen4_ctl.rb" /usr/local/libexec/ryzen4_ctl.rb
install -m 0755 "$GPUTEMPS_SOURCE_DIR/gputemps" /usr/local/libexec/gputemps
install -m 0755 "$ROOT_DIR/scripts/pc-fand.py" /usr/local/libexec/pc-fand.py
install -m 0755 "$ROOT_DIR/scripts/pc-power-silent-at-boot" /usr/local/libexec/pc-power-silent-at-boot
install -m 0755 "$ROOT_DIR/scripts/cpu-power" /usr/local/sbin/cpu-power
install -m 0755 "$ROOT_DIR/scripts/pc-power" /usr/local/sbin/pc-power
install -m 0644 "$ROOT_DIR/config/fan-profiles.json" /etc/pc-power/fan-profiles.json
install -m 0644 "$ROOT_DIR/config/fans.conf.example" /etc/pc-power/fans.conf.example
if [[ ! -e /etc/pc-power/fans.conf ]]; then
  install -m 0644 "$ROOT_DIR/config/fans.conf.example" /etc/pc-power/fans.conf
elif ! grep -q '^\[lower\]$' /etc/pc-power/fans.conf || ! grep -q '^\[upper\]$' /etc/pc-power/fans.conf; then
  printf '%s\n' 'WARNING: existing fans.conf uses an older fan-zone schema.' >&2
  printf '%s\n' 'Migrate it using /etc/pc-power/fans.conf.example before enabling pc-fand.' >&2
fi
install -m 0644 "$ROOT_DIR/systemd/pc-fand.service" /usr/local/share/desktop-computer-power/pc-fand.service
install -m 0644 "$ROOT_DIR/systemd/pc-power-silent.service" /usr/local/share/desktop-computer-power/pc-power-silent.service

printf '%s\n' 'Installed userspace files. Fan writes and pc-fand.service remain disabled.'
printf '%s\n' 'Load the CPU module when needed: sudo modprobe ryzen_smu'
printf '%s\n' 'Complete three-zone active fan testing before enable-fan-service.sh.'
