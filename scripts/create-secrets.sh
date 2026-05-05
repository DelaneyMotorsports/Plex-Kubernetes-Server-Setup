#!/usr/bin/env bash
# Creates the media-stack-secret Kubernetes Secret from a .env file.
# Usage: ./scripts/create-secrets.sh [path-to-env-file]
# Default env file: .env in the repo root
set -euo pipefail

ENV_FILE="${1:-.env}"
NAMESPACE="media"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: $ENV_FILE not found."
  echo "  Copy .env.example to .env and fill in your values, then re-run."
  exit 1
fi

# Validate required secret fields
required_keys=(WIREGUARD_PRIVATE_KEY WIREGUARD_ADDRESSES PLEX_CLAIM)
source "$ENV_FILE"

for key in "${required_keys[@]}"; do
  val="${!key:-}"
  if [[ -z "$val" || "$val" == "CHANGE-ME" ]]; then
    echo "Error: $key is not set or still says CHANGE-ME in $ENV_FILE"
    exit 1
  fi
done

echo "Creating/updating media-stack-secret in namespace: $NAMESPACE"

kubectl create secret generic media-stack-secret \
  --namespace "$NAMESPACE" \
  --from-literal=WIREGUARD_PRIVATE_KEY="$WIREGUARD_PRIVATE_KEY" \
  --from-literal=WIREGUARD_ADDRESSES="$WIREGUARD_ADDRESSES" \
  --from-literal=PLEX_CLAIM="$PLEX_CLAIM" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Done. Secret applied successfully."
echo ""
echo "Note: PLEX_CLAIM expires 4 minutes after generation."
echo "      After first Plex startup, the claim is stored in config and this secret"
echo "      can be updated with a blank PLEX_CLAIM value."
