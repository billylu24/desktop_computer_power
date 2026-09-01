#!/usr/bin/env bash
# Final activation step. Run only after CPU/SYS mapping and active PWM tests.
set -euo pipefail

readonly FANS_CONF=/etc/pc-power/fans.conf
readonly FAND=/usr/local/libexec/pc-fand.py
readonly UNIT_SOURCE=/usr/local/share/desktop-computer-power/pc-fand.service

die() { printf 'enable-fan-service.sh: %s\n' "$*" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || die 'run as root: sudo ./enable-fan-service.sh'
[[ -x $FAND ]] || die "missing $FAND; run install.sh first"
[[ -r $FANS_CONF ]] || die "missing $FANS_CONF"
[[ -r $UNIT_SOURCE ]] || die "missing $UNIT_SOURCE; run install.sh first"
grep -Eq '^[[:space:]]*enabled[[:space:]]*=[[:space:]]*true[[:space:]]*$' "$FANS_CONF" ||
  die 'fans.conf is not enabled; CPU/SYS mapping must be completed first'

modprobe it87
"$FAND" --dry-run --once >/dev/null || die 'final dry-run failed'
install -m 0644 "$UNIT_SOURCE" /etc/systemd/system/pc-fand.service
systemctl daemon-reload
systemctl enable --now pc-fand.service
sleep 3
systemctl is-active --quiet pc-fand.service || die 'pc-fand.service did not remain active'
printf '%s\n' 'pc-fand.service is active. No CPU/GPU/Linux profile was applied.'
