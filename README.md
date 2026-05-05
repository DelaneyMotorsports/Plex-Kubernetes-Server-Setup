# Plex Kubernetes Media Stack

A self-hosted media stack that runs on a Raspberry Pi 5, a spare x86 box, or any cloud VM. Plex, automated downloading, VPN-isolated torrenting, and subtitle management — all on Kubernetes, all self-contained.

## One-Line Install

```bash
curl -sSL https://raw.githubusercontent.com/DelaneyMotorsports/Plex-Kubernetes-Server-Setup/main/install.sh | bash
```

The installer handles everything interactively: installs K3s, sets up ingress, prompts for your VPN keys and Plex token, mounts your drive, and deploys the full stack. Takes about 5 minutes on a fresh Pi 5.

> **Want to review the script first?** `curl -sSL ...install.sh | less` — we encourage it.

**Automation / CI** — pre-set env vars to skip prompts:

```bash
export WIREGUARD_PRIVATE_KEY="your-key"
export WIREGUARD_ADDRESSES="10.5.0.2/32"
export PLEX_CLAIM="claim-xxxxxx"
export TZ="America/Chicago"
curl -sSL https://raw.githubusercontent.com/DelaneyMotorsports/Plex-Kubernetes-Server-Setup/main/install.sh | bash
```

---

## Why Kubernetes Instead of Docker Compose

| | Docker Compose | Kubernetes (K3s) |
|---|---|---|
| Self-healing | Manual restart policies | Pod controller auto-restarts |
| Rolling updates | Stop → pull → start | Zero-downtime rollout |
| Resource limits | Optional, rarely enforced | Enforced per container |
| Secrets | `.env` files on disk | Kubernetes Secrets (encrypted at rest in etcd) |
| Network isolation | Docker networks | NetworkPolicies + namespace isolation |
| Config management | Copy files between hosts | `kustomize` overlays per environment |
| Future scale | Rewrite everything | Add nodes |

---

## Architecture

```
                          ┌──────────────────────────────────────────┐
                          │           media namespace                 │
                          │                                           │
  LAN / Browser ──────────┤─► Overseerr :5055  (request portal)      │
                          │       │                                   │
                          │       ├──► Sonarr :8989  (TV)            │
                          │       └──► Radarr :7878  (Movies)        │
                          │               │           │               │
                          │               └─────┬─────┘              │
                          │                     ▼                     │
                          │              Prowlarr :9696               │
                          │              (indexer aggregator)         │
                          │                                           │
                          │  ┌─── Pod: gluetun + qbittorrent ──────┐ │
                          │  │  Gluetun (WireGuard VPN)            │ │
                          │  │     ↕  shared network namespace      │ │
                          │  │  qBittorrent :8080                  │ │
                          │  └─────────────────────────────────────┘ │
                          │                     │                     │
                          │       ┌─────────────┴─────────────┐      │
                          │       ▼                             ▼      │
                          │  /downloads PVC             /media PVC    │
                          │       │                             │      │
                          │  Sonarr / Radarr ──────► Plex :32400     │
                          │                           Bazarr :6767    │
                          └──────────────────────────────────────────┘
```

### Key Design Decisions

**Gluetun + qBittorrent as a sidecar pod.** Both containers share the pod's network namespace. All qBittorrent traffic physically cannot leave except through the WireGuard tunnel — no routing rules needed. A `wait-for-vpn` init container blocks qBittorrent from starting until Gluetun reports a connected VPN IP.

**No Cloudflare dependencies.** This stack has zero Cloudflare involvement: no Cloudflare Tunnel, no WARP, no Cloudflare-proxied domains. Your traffic goes directly from your device, through your VPN, to wherever you point it. Privacy and freedom are the baseline, not an add-on.

**Prowlarr replaces Jackett.** Prowlarr syncs indexer configs directly into Sonarr and Radarr via their APIs — no per-app indexer duplication.

**ReadWriteOnce on a single node.** Multiple pods (Sonarr, Radarr, Bazarr, Plex) share the same `media-library-pvc`. On a single-node cluster, `ReadWriteOnce` means "one node," not "one pod" — all pods on the same node can mount it. Multi-node clusters need NFS or Longhorn (documented in Roadmap).

---

## Services

| Service | Port | Purpose |
|---|---|---|
| Plex | 32400 | Media server — streams to all clients |
| Sonarr | 8989 | TV series automation |
| Radarr | 7878 | Movie automation |
| Prowlarr | 9696 | Indexer aggregator |
| Bazarr | 6767 | Subtitle downloading |
| Overseerr | 5055 | Request portal for family/friends |
| qBittorrent | 8080 | Torrent client (VPN-isolated) |
| Gluetun | — | WireGuard VPN gateway (NordVPN, no external ports) |

---

## OS Options for Pi 5

The installer targets **Debian-family systems** (Raspberry Pi OS Lite 64-bit, Ubuntu, Debian). Pick your path:

### Option A — Raspberry Pi OS Lite 64-bit (Recommended to start)
Fastest path to a working stack. Flash with Raspberry Pi Imager, enable SSH, then run the one-liner. Non-immutable, but battle-tested on Pi hardware.

### Option B — Talos Linux (Recommended for production / immutable)
Purpose-built Kubernetes OS. No SSH, no shell, no package manager. Entirely API-driven. Pi 5 support since **Talos v1.7** (2024).

```bash
# 1. Flash the rpi_generic Talos image to your SD/USB
#    Download: https://github.com/siderolabs/talos/releases
#    File: metal-arm64.raw.xz  (write with: xz -dc *.xz | sudo dd of=/dev/sdX bs=4M)

# 2. Bootstrap
talosctl gen config media-cluster https://<PI_IP>:6443
talosctl apply-config --insecure --nodes <PI_IP> --file controlplane.yaml
talosctl bootstrap --nodes <PI_IP>
talosctl kubeconfig --nodes <PI_IP> ~/.kube/config

# 3. Run the installer pointing at the existing cluster (skip K3s install)
export KUBECONFIG=~/.kube/config
curl -sSL https://raw.githubusercontent.com/DelaneyMotorsports/Plex-Kubernetes-Server-Setup/main/install.sh | bash
```

**Gotchas:** Update Pi 5 EEPROM from Raspberry Pi OS before flashing Talos. Talos needs current firmware to boot on Pi 5.

### Option C — Fedora IoT with K3s
Atomic updates via `rpm-ostree`. Pi 5 support since Fedora 40. Same one-liner install once the OS is up.

---

## Manual / Custom Install

If you want full control instead of the one-liner:

```bash
git clone https://github.com/DelaneyMotorsports/Plex-Kubernetes-Server-Setup.git
cd Plex-Kubernetes-Server-Setup

cp .env.example .env
# Fill in .env — VPN keys, Plex claim, timezone, etc.

# Set your node name and storage paths
NODE=$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')
sed -i "s/CHANGE-ME-NODE-NAME/$NODE/g" \
  k8s/base/storage/media-pv.yaml \
  k8s/overlays/pi5/node-selector-patch.yaml

# Create secrets
chmod +x scripts/*.sh
./scripts/create-secrets.sh .env

# Deploy
kubectl apply -k k8s/overlays/pi5/

# Check status
./scripts/verify.sh
```

---

## Post-Install Configuration

After first boot, wire the services together (one-time setup via their web UIs):

1. **Prowlarr** — add your indexers
2. **Sonarr** → Settings → Indexers → click "Sync App Indexers" (Prowlarr auto-pushes)
3. **Sonarr** → Settings → Download Clients → Add qBittorrent → Host: `qbittorrent`, Port: `8080`
4. **Radarr** — same as Sonarr
5. **Bazarr** → Settings → Sonarr: `sonarr:8989`, Radarr: `radarr:7878`
6. **Overseerr** → connect to Plex, Sonarr, Radarr

**Plex claim:** Visit `http://plex.local:32400/web` and complete setup. Add library at `/media/tv` and `/media/movies`.

---

## Access

Add to `/etc/hosts` (or your local DNS/Pi-hole) on any device:

```
<PI_IP>  plex.local sonarr.local radarr.local prowlarr.local
<PI_IP>  bazarr.local overseerr.local qbittorrent.local
```

| Service | URL |
|---|---|
| Plex | http://plex.local:32400/web |
| Sonarr | http://sonarr.local |
| Radarr | http://radarr.local |
| Prowlarr | http://prowlarr.local |
| Bazarr | http://bazarr.local |
| Overseerr | http://overseerr.local |
| qBittorrent | http://qbittorrent.local |

---

## Maintenance

```bash
# Roll a full image update across all services
kubectl rollout restart deployment -n media

# Stream logs from a service
kubectl logs -n media deploy/sonarr -f

# Check VPN is connected and get exit IP
kubectl exec -n media deploy/gluetun-qbittorrent -c gluetun \
  -- wget -qO- http://localhost:8000/v1/publicip/ip

# Status snapshot
./scripts/verify.sh
```

---

## Repository Structure

```
.
├── install.sh                   # One-line installer
├── .env.example                 # Config template
├── .gitignore
├── k8s/
│   ├── base/                    # Environment-agnostic manifests
│   │   ├── kustomization.yaml
│   │   ├── namespace.yaml
│   │   ├── configmap.yaml
│   │   ├── network-policies.yaml
│   │   ├── storage/             # PVs, PVCs, StorageClass
│   │   ├── gluetun-qbittorrent/ # VPN sidecar + torrent client
│   │   ├── prowlarr/
│   │   ├── sonarr/
│   │   ├── radarr/
│   │   ├── bazarr/
│   │   ├── overseerr/
│   │   └── plex/
│   └── overlays/
│       └── pi5/                 # Pi 5 node selector patch
└── scripts/
    ├── bootstrap.sh             # Manual bootstrap (alternative to install.sh)
    ├── create-secrets.sh        # Creates K8s Secret from .env
    └── verify.sh                # Health check
```

---

## Roadmap

- [ ] **Hardware transcoding** — Pi 5's VideoCore VII supports H.264/H.265. Uncomment the `/dev/dri` device mount in `k8s/base/plex/deployment.yaml`.
- [ ] **MetalLB** — assign a real LAN IP to the Plex LoadBalancer service (removes need for `hostNetwork`).
- [ ] **TLS / HTTPS** — cert-manager + Let's Encrypt for Overseerr external access.
- [ ] **Multi-node storage** — replace `media-local` PVs with an NFS StorageClass or Longhorn when adding nodes.
- [ ] **Talos migration guide** — step-by-step from RPi OS + K3s to Talos, preserving all config.
- [ ] **Image pinning** — replace `latest` tags with pinned versions + Renovate/Dependabot automation.
- [ ] **Monitoring** — Prometheus + Grafana dashboard for Pi 5 resource tracking.

---

*Delaney Motorsports R&D — Kevin Delaney, Director of Research and Development*
