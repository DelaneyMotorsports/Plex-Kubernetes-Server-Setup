# Validation

The workflow runs on pull requests and pushes to main or plex-server-improvements.
All checks are blocking. It does not receive production credentials or target the
running Plex cluster.

```bash
python3 -m venv /tmp/media-validation
/tmp/media-validation/bin/pip install -r ci/requirements.txt
python3 scripts/install-ci-tools.py --destination /tmp/media-tools
PATH=/tmp/media-validation/bin:/tmp/media-tools:$PATH ./scripts/validate.sh
```

The binary installer supports Linux AMD64 CI hosts. Other systems can use their
native versions of the same tools. Download URLs and SHA256 hashes are committed
in `ci/tools.json`; release archives are verified before extracting a named binary.

The validation job:

- Builds every overlay and standalone addon.
- Checks Service selectors, Ingress backend ports, PVC references, secret references,
  and unsupported controller settings.
- Validates built-in resources against Kubernetes 1.31 schemas. It does not ignore
  missing schemas. Application, AppProject and SealedSecret resources are separately
  checked against checksum-pinned upstream CRD schemas in `ci/custom-resources.json`.
- Renders the exact Traefik chart and values installed by Ansible, including Helm's
  own chart-value schema validation.
- Runs encrypted Restic/SQLite round-trip and restore-controller tests, including
  failure paths that must keep workloads stopped.
- Runs ShellCheck, all three playbook syntax checks, and blocking ansible-lint.
- Queries OCI manifest indexes for real image availability and AMD64/ARM64 support.

The node-name placeholder and empty SealedSecret are intentional repository
configuration templates. CI permits only these documented cases, and tests that
strict deployment validation rejects them. It does not silently allow arbitrary
CHANGE-ME values. Before deploying your configured overlay, run the strict check:

```bash
kustomize build k8s/overlays/pi5 > /tmp/media-configured.yaml
python3 scripts/validate-manifests.py /tmp/media-configured.yaml
```

A separate startup job creates a new, uniquely named kind cluster with an isolated
kubeconfig. It starts the real Sonarr, Radarr and Prowlarr images using disposable
config/media volumes and checks their HTTP endpoints through the real Traefik
controller. The cluster is deleted on exit. Run it locally only where kind's
container runtime is available:

```bash
PATH=/tmp/media-validation/bin:/tmp/media-tools:$PATH ./scripts/smoke-cluster.sh
```

This smoke test exercises startup and routing, not your NAS, private VPN provider,
remote client playback, or a full disaster-recovery drill. The CI Kubernetes minor
matches the existing K3s manifests; passing it is not a claim that the old K3s
version remains in upstream security support. Production upgrade planning remains
separate from these application changes.
