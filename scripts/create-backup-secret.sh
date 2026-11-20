#!/usr/bin/env bash
# Supply RESTIC_PASSWORD from a password manager or read it interactively.
set -euo pipefail
if [[ -z "${RESTIC_PASSWORD:-}" ]]; then
  read -r -s -p 'Backup encryption password (keep an offline copy): ' RESTIC_PASSWORD
  printf '\n' >&2
fi
[[ ${#RESTIC_PASSWORD} -ge 20 ]] || { echo 'Use at least 20 characters.' >&2; exit 1; }
printf '%s' "$RESTIC_PASSWORD" | kubectl -n media create secret generic config-backup-secret \
  --from-file=RESTIC_PASSWORD=/dev/stdin --dry-run=client -o yaml | kubectl apply -f -
