#!/usr/bin/env bash
# RESTIC_REPOSITORY points to the mounted NAS repository; password stays out of Git.
set -euo pipefail
: "${RESTIC_REPOSITORY:?Set RESTIC_REPOSITORY to the mounted encrypted repository}"
: "${RESTIC_PASSWORD:?Set the offline copy of RESTIC_PASSWORD}"
for binary in restic kubectl; do command -v "$binary" >/dev/null; done
# pipefail prevents applying a partial/failed dump. Materialize before applying so
# no Kubernetes write occurs unless the complete JSON document was recovered.
TASK_RECOVERY_DIR=$(mktemp -d)
chmod 700 "$TASK_RECOVERY_DIR"
trap 'rm -rf "$TASK_RECOVERY_DIR"' EXIT
umask 077
restic dump --host media-stack --tag media-config "${1:-latest}" /work/snapshot/sealed-secrets-keys.json > "$TASK_RECOVERY_DIR/keys.json"
python3 -m json.tool "$TASK_RECOVERY_DIR/keys.json" >/dev/null
kubectl apply -f "$TASK_RECOVERY_DIR/keys.json"
kubectl -n kube-system rollout restart deployment/sealed-secrets-controller
kubectl -n kube-system rollout status deployment/sealed-secrets-controller --timeout=180s
