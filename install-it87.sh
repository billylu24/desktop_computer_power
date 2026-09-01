#!/usr/bin/env bash
# Install the exact IT8689E-capable driver tested on the reference board.
# This script installs a driver only; it never changes PWM values.
set -euo pipefail

readonly SOURCE_DIR=/usr/local/src/it87
readonly REPO=https://github.com/frankcrawford/it87.git
readonly COMMIT=c567739c639533177abd66894a6a8d561337285f

die() { printf 'install-it87.sh: %s\n' "$*" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || die 'run as root: sudo ./install-it87.sh'

apt update
apt install -y git dkms build-essential "linux-headers-$(uname -r)"

if dkms status | grep -q '^it87/'; then
  die 'an it87 DKMS module is already installed; inspect and remove/upgrade it explicitly'
fi
if [[ -e $SOURCE_DIR/.git ]]; then
  git -C "$SOURCE_DIR" fetch origin "$COMMIT"
elif [[ -e $SOURCE_DIR ]]; then
  die "$SOURCE_DIR exists but is not a Git checkout"
else
  git clone "$REPO" "$SOURCE_DIR"
fi
git -C "$SOURCE_DIR" checkout --detach "$COMMIT"
grep -q 'it8689' "$SOURCE_DIR/it87.c" || die 'pinned source does not contain IT8689E support'
grep -q 'mmio' "$SOURCE_DIR/it87.c" || die 'pinned source does not contain the Gigabyte MMIO path'

(cd "$SOURCE_DIR" && ./dkms-install.sh)
modinfo it87 >/dev/null || die 'it87 is not available through modprobe after DKMS installation'
printf 'Installed it87 commit %s. No PWM values were changed.\n' "$COMMIT"
