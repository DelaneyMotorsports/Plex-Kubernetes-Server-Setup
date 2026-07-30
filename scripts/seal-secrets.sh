#!/usr/bin/env bash
# Encrypt the media-stack secrets into a SealedSecret that is safe to commit to Git.
#
# Usage: ./scripts/seal-secrets.sh [path-to-env-file]     (default: .env)
#
# Requires: kubectl + kubeseal, and a cluster whose Sealed Secrets controller is running
# (Ansible installs it via the sealed_secrets role). The output overwrites
# k8s/base/sealed-secret.yaml — commit that file and Argo will apply it; the controller
# decrypts it into the real media-stack-secret in-cluster.
set -euo pipefail

ENV_FILE="${1:-.env}"
NAMESPACE="media"
OUT="k8s/base/sealed-secret.yaml"
CONTROLLER_NS="kube-system"
CONTROLLER_NAME="sealed-secrets-controller"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: $ENV_FILE not found. Copy .env.example to .env and fill it in." >&2
  exit 1
fi
for bin in kubectl kubeseal; do
  command -v "$bin" >/dev/null 2>&1 || { echo "Error: '$bin' not found in PATH." >&2; exit 1; }
done

# shellcheck disable=SC1090
source "$ENV_FILE"
required_keys=(WIREGUARD_PRIVATE_KEY WIREGUARD_ADDRESSES PLEX_CLAIM)
for key in "${required_keys[@]}"; do
  val="${!key:-}"
  if [[ -z "$val" || "$val" == "CHANGE-ME" ]]; then
    echo "Error: $key is unset or still 'CHANGE-ME' in $ENV_FILE" >&2
    exit 1
  fi
done

echo "Sealing media-stack-secret for namespace '$NAMESPACE' -> $OUT"

kubectl create secret generic media-stack-secret \
  --namespace "$NAMESPACE" \
  --from-literal=WIREGUARD_PRIVATE_KEY="$WIREGUARD_PRIVATE_KEY" \
  --from-literal=WIREGUARD_ADDRESSES="$WIREGUARD_ADDRESSES" \
  --from-literal=PLEX_CLAIM="$PLEX_CLAIM" \
  --dry-run=client -o yaml \
  | kubeseal --format yaml \
      --controller-namespace "$CONTROLLER_NS" \
      --controller-name "$CONTROLLER_NAME" \
  > "$OUT"

echo "Wrote $OUT"
echo "Next: git add $OUT && git commit -m 'chore: update sealed media secret' && git push"
echo "Argo CD will sync it and the Sealed Secrets controller will materialize the Secret."
