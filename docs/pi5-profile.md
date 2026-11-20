# Pi 5 default profile

The default contains seven Deployments: Plex, Sonarr, Radarr, Prowlarr, Bazarr,
Overseerr, and Gluetun/qBittorrent. Enrichment and transcoding services are opt-in
Kustomize addons; no extra daemon starts just because it exists in the repository.

| Scope | Configured memory limits |
| --- | ---: |
| Seven core application Deployments, including the VPN sidecar | 4.75 GiB |
| Core applications plus Traefik | 5 GiB |
| Core, Traefik, and one scheduled config backup | 5.5 GiB |

The last two limits are checked in CI against `ci/pi5-budget.json`. These are
resource ceilings, not measured consumption or guaranteed available RAM. K3s,
Argo CD and the OS are outside this application budget and need the remaining
headroom. Memory requests for core plus Traefik total 1376 MiB. CPU requests are
scheduling reservations; CPU limits can be oversubscribed. Measure real usage
with `kubectl top pods -A` and node metrics before raising limits or enabling addons.

Pi 5 has no hardware video encoder. This profile prioritizes Direct Play and
compatible pre-encoded media. Mounting `/dev/dri` or enabling privileged mode does
not add the missing encoder. The optional Tdarr and ErsatzTV services need a
separately tested encoding configuration and suitable compute for their workload.

Plex transcode scratch has an 8 GiB disk ceiling and a 10 GiB ephemeral-storage
limit. Optional Tdarr scratch has a 32 GiB ceiling and a 40 GiB limit. Adjust those
explicitly for large source files. Backup staging can need approximately the
entire config dataset and has a 100 GiB disk ceiling. These limits do not allocate
that much disk in advance or provide NAS capacity guarantees.

## Enable an addon

First satisfy the [application prerequisites](applications.md), supply its config
and private API keys, and review the memory budget. For example, add Profilarr to
your own Pi overlay resources:

```yaml
resources:
- ../../base
- ../../addons/profilarr
```

Keep the overlay's existing NAS, node-selection and resource patches. Rebuild,
run strict configuration validation, and recalculate the budget before committing.
CI also schema-checks every addon and verifies references against the core stack.
The unused app PVCs are intentionally retained so disabling an addon does not
prune its configuration. Backups continue to include those config volumes.

There are no automatic hardware-detection or cross-node failover claims here.
Local config PVCs and the recovery unit remain tied to one node; adding a worker
alone does not relocate application state.
