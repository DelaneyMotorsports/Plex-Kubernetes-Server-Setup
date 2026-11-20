# Application validation and prerequisites

Public OCI manifest indexes were queried directly for availability and
`linux/arm64` / `linux/amd64` support. This checks image publication, not that an
app with your private configuration or API keys has completed a startup test.
The later image lock records the exact verified manifest indexes.

| Application | Result and required configuration |
| --- | --- |
| Plex, Sonarr, Radarr, Prowlarr, Bazarr, Overseerr, qBittorrent | Published multiarch LinuxServer images. Complete the existing web setup and service wiring. |
| Gluetun | Published multiarch image. Supply valid WireGuard credentials and matching provider settings. See [VPN notes](vpn.md). |
| Recyclarr | `latest` returns 404; use the published major-8 tag. Remove the unsupported `daemon` argument: the image's default entrypoint runs cron. Run as UID/GID 1000. Supply `/config/recyclarr.yml` with Sonarr/Radarr URLs and API keys before enabling it. Avoid having Recyclarr and Profilarr overwrite the same profiles. |
| Profilarr | Published ARM64/AMD64 image. Configure its database source and Sonarr/Radarr connections in its UI. |
| Unpackerr | Published multiarch image. Config is mounted at `/config`. `UN_QBIT_0_URL` is not a supported integration. Sonarr and Radarr API keys come from a separate `unpackerr-secret`. |
| Tdarr | Published ARM64/AMD64 image. `/app/server` contains its database, plugins and samples and now has a dedicated PVC included in backup. `/app/configs` and `/app/logs` remain persistent. Configure libraries and node concurrency before enabling transcoding. |
| Posterr | Published ARM64/AMD64 image. Correct persistent paths are `/usr/src/app/config` and `/usr/src/app/public/custom`. Change its upstream default password during setup. |
| ErsatzTV | Published multiarch image. Configure libraries/channels and use compatible compute for real-time encoding. |
| Kometa | Published ARM64/AMD64 image. Supply `/config/config.yml`, Plex access and metadata-provider credentials before enabling its scheduled jobs. |
| Janitorr | The original Docker Hub reference is unavailable. The upstream image is `ghcr.io/schaka/janitorr:jvm-stable`, with ARM64/AMD64. It is a config-driven Jellyfin/Emby service, not the advertised Plex web UI. Moved to an opt-in addon with no invented UI/probes; supply `/config/application.yml` and external dependencies. |
| Varken | Its multiarch image exists, but this repository does not supply its required InfluxDB/Grafana stack or `varken.ini`. Moved to an opt-in addon requiring those external services and network-policy allowances. |
| Sub-Zero | Upstream is a deprecated Plex plugin recommending Bazarr, not this standalone port-5000 service. Its container reference could not be pulled anonymously. Removed the invalid application definition. Bazarr remains. |
| ThePosterDB, Mediux, Scannarr | The configured image references are not anonymously retrievable (registry 401/403); no usable matching upstream deployment could be verified. Removed these definitions. ThePosterDB/Mediux artwork can still be consumed through a supported configured artwork tool such as Kometa. |

Config PVCs for removed or opt-in apps are deliberately retained to preserve any
existing data. They do not turn those apps on. Remove old PVCs only after a backup
and a separate decision to discard their contents.

## Optional services

Janitorr and Varken are under `k8s/addons/`. Add their directory as a Kustomize
resource in your own overlay only after configuring the external requirements.
Janitorr uses the same `/media` path as this stack; make its configuration paths
match. Neither addon is part of the Plex default deployment.

To provide Unpackerr's separate keys, create a private file outside this repository
with `SONARR_API_KEY=...` and `RADARR_API_KEY=...`, then run:

```bash
kubectl -n media create secret generic unpackerr-secret \
  --from-env-file=/secure/unpackerr.env --dry-run=client -o yaml | kubectl apply -f -
```

Keep that private file in your password manager or seal this distinct Secret if
you want to manage it through Git. Do not commit plaintext application credentials.
The config backup includes application config files, but external dependencies
and separately supplied credentials must also have an off-cluster recovery source.

## Upstream references

- [Recyclarr container entrypoint and cron](https://recyclarr.dev/guide/installation/docker/)
- [Unpackerr configuration](https://unpackerr.zip/docs/install/configuration/)
- [Tdarr volume mapping](https://docs.tdarr.io/docs/installation/docker/volume-mapping/)
- [Posterr installation](https://github.com/petersem/posterr)
- [Janitorr installation and prerequisites](https://github.com/Schaka/janitorr)
- [Varken example dependencies](https://github.com/Boerderij/Varken/blob/master/docker-compose.yml)
- [Sub-Zero deprecation](https://github.com/pannal/Sub-Zero.bundle)
