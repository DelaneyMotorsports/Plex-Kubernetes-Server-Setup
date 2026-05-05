# Plex Kubernetes Media Stack

A production-grade Kubernetes media server stack — Plex, automated downloading, VPN isolation, and subtitle management — designed to run on a Raspberry Pi 5 and scale to multi-node clusters.

## Why Kubernetes Instead of Docker Compose

| | Docker Compose | Kubernetes (K3s) |
|---|---|---|
| Self-healing | Manual restart policies | Pod controller restarts failed containers |
| Updates | `docker compose pull && up` | `kubectl rollout` with zero-downtime |
| Resource limits | Optional, often ignored | Enforced per-container |
| Secrets | `.env` files on disk | Kubernetes Secrets (encrypted at rest) |
| Network isolation | Docker networks | NetworkPolicies with namespace isolation |
| Config management | Copy files between hosts | `kustomize` overlays per environment |
| Observability | `docker logs` | Full metrics/logging ecosystem |
| Future scale | Rewrite everything | Add nodes |

The goal is to prove this runs efficiently on a Pi 5 first, then scale or harden as needed.

---

## Architecture

```
                          ┌─────────────────────────────────────────────┐
                          │             media namespace                  │
                          │                                              │
  LAN / Browser ──────────┤─► Overseerr :5055  (request portal)         │
                          │       │                                      │
                          │       ├──► Sonarr :8989  (TV)               │
                          │       └──► Radarr :7878  (Movies)           │
                          │               │           │                  │
                          │               └─────┬─────┘                 │
                          │                     │                        │
                          │              Prowlarr :9696  (indexers)      │
                          │                     │                        │
                          │              Flaresolverr :8191  (CF bypass) │
                          │                                              │
                          │  ┌─── Pod: gluetun-qbittorrent ──────────┐  │
                          │  │  Gluetun (WireGuard VPN)              │  │
                          │  │      ↕  shared network namespace       │  │
                          │  │  qBittorrent :8080 (downloads)        │  │
                          │  └───────────────────────────────────────┘  │
                          │                     │                        │
                          │          ┌──────────┴──────────┐            │
                          │          ▼                      ▼            │
                          │    /downloads PVC        /media PVC          │
                          │          │                      │            │
                          │    Sonarr/Radarr ──────► Plex :32400        │
                          │          │                Bazarr :6767       │
                          │          └──────────────────────┘            │
                          └─────────────────────────────────────────────┘
```

### Key Design Decisions

**Gluetun + qBittorrent as a sidecar pod**: Both containers share the same network namespace. All qBittorrent traffic is automatically routed through the WireGuard tunnel — no iptables rules needed. The `wait-for-vpn` init container blocks qBittorrent from starting until the VPN is confirmed connected.

**Prowlarr replaces Jackett**: Prowlarr is the modern indexer manager. It integrates directly with Sonarr/Radarr without needing per-app indexer configs, and supports the same indexers as Jackett.

**Storage split**: Config volumes use K3s's `local-path` dynamic provisioner (fast, low-overhead). Media and downloads use `local` PVs that you bind to your actual drive mount points.

**ReadWriteOnce on single node**: Multiple pods can mount the same `ReadWriteOnce` PVC when they all schedule on the same node. Sonarr, Radarr, Bazarr, and Plex all share `media-library-pvc` this way.

---

## Services

| Service | Port | Purpose |
|---|---|---|
| Plex | 32400 | Media server — streams to all clients |
| Sonarr | 8989 | TV series management and automation |
| Radarr | 7878 | Movie management and automation |
| Prowlarr | 9696 | Indexer aggregator (replaces Jackett) |
| Bazarr | 6767 | Subtitle downloading |
| Overseerr | 5055 | Request portal for family/friends |
| qBittorrent | 8080 | Torrent client (behind VPN) |
| Gluetun | 8000 | WireGuard VPN gateway (NordVPN) |
| Flaresolverr | 8191 | Cloudflare bypass for indexers |

---

## Pi 5 Setup Guide

### The OS Question

You mentioned struggling with immutable/atomic OSes on Pi 5. Here's the honest state of each option:

#### Option A — Talos Linux (Recommended for pure K8s)
Talos is purpose-built for Kubernetes: read-only root filesystem, no SSH, no package manager, managed entirely via API. Pi 5 support landed in **Talos v1.7.0** (mid-2024).

```bash
# Download the Pi 5 image
curl -LO https://github.com/siderolabs/talos/releases/latest/download/metal-arm64.raw.xz

# Flash to SD or USB SSD
xz -dc metal-arm64.raw.xz | sudo dd of=/dev/sdX bs=4M status=progress

# Generate machine config
talosctl gen config media-cluster https://<PI_IP>:6443

# Bootstrap
talosctl apply-config --insecure --nodes <PI_IP> --file controlplane.yaml
talosctl bootstrap --nodes <PI_IP>
talosctl kubeconfig --nodes <PI_IP> .
```

Gotchas:
- Needs current Pi 5 EEPROM (update via `rpi-eeprom-update` from Raspberry Pi OS first)
- HDMI output on Talos is limited; manage via `talosctl` from another machine
- No `/var/lib/rancher/k3s` — uses containerd directly; adjust PVC paths accordingly

#### Option B — K3s on Raspberry Pi OS Lite (Fastest path to working)
If you want to validate the stack before committing to an immutable OS, this is the right starting point.

```bash
# Flash Raspberry Pi OS Lite (64-bit) — use Raspberry Pi Imager
# Enable SSH and set hostname in Imager's settings

# On the Pi:
sudo apt update && sudo apt full-upgrade -y

# Install K3s (single-node, no HA needed)
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server \
  --disable traefik \
  --write-kubeconfig-mode 644" sh -

# Install ingress-nginx (since we disabled traefik)
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.1/deploy/static/provider/baremetal/deploy.yaml

# Copy kubeconfig to your machine
scp pi@<PI_IP>:/etc/rancher/k3s/k3s.yaml ~/.kube/config
sed -i 's/127.0.0.1/<PI_IP>/g' ~/.kube/config
```

#### Option C — Fedora IoT with K3s (Best balance of immutability + flexibility)
Fedora IoT uses `rpm-ostree` (now `bootc`) for atomic, transactional updates with rollback. Official Pi 5 images exist as of Fedora 40.

```bash
# Download Fedora IoT ARM64 image from https://fedoraproject.org/iot/download
# Flash to SD/USB SSD

# After boot, install K3s as on Option B
# Atomic updates: rpm-ostree upgrade  (applies on reboot, rollback if broken)
```

### Storage Setup (All Options)

The stack expects two host mount points:

```bash
# Mount your USB SSD (adjust /dev/sda1 to your device)
sudo mkdir -p /mnt/media /mnt/downloads

# Add to /etc/fstab for persistence
echo "UUID=$(blkid -s UUID -o value /dev/sda1) /mnt/media ext4 defaults,nofail 0 2" | sudo tee -a /etc/fstab

# Create subdirectory structure
sudo mkdir -p /mnt/media/tv /mnt/media/movies /mnt/media/music
sudo mkdir -p /mnt/downloads/incomplete /mnt/downloads/complete

# Set ownership to your PUID/PGID (default 1000)
sudo chown -R 1000:1000 /mnt/media /mnt/downloads
```

---

## Configuration

### 1. Clone and configure

```bash
git clone https://github.com/delaneymotorsports/plex-kubernetes-server-setup.git
cd plex-kubernetes-server-setup

cp .env.example .env
# Edit .env — fill in WIREGUARD_PRIVATE_KEY, WIREGUARD_ADDRESSES, PLEX_CLAIM
```

**Getting your NordVPN WireGuard key:**
1. Log into NordVPN → My Account → Services
2. Go to the NordVPN app → Settings → Set up NordVPN manually → WireGuard
3. Generate a key pair and note the private key and assigned IP

**Getting your Plex claim:**
1. Visit `https://plex.tv/claim` while logged in
2. Copy the token — it expires in 4 minutes, so do this right before deploying

### 2. Set your node name and storage paths

```bash
# Get your node name
kubectl get nodes

# Set it in both files — replace CHANGE-ME-NODE-NAME with your actual hostname
sed -i 's/CHANGE-ME-NODE-NAME/YOUR-HOSTNAME/g' \
  k8s/base/storage/media-pv.yaml \
  k8s/overlays/pi5/node-selector-patch.yaml
```

If your media or downloads paths differ from `/mnt/media` and `/mnt/downloads`, update them in `k8s/base/storage/media-pv.yaml`.

### 3. Adjust storage sizes

Edit `k8s/base/storage/media-pv.yaml` to match your drive:
```yaml
capacity:
  storage: 2Ti   # ← change to your actual drive size
```

And the corresponding PVCs in `k8s/base/storage/pvcs.yaml`.

---

## Deployment

```bash
# Make scripts executable
chmod +x scripts/*.sh

# Bootstrap (first time only)
./scripts/bootstrap.sh pi5

# Subsequent updates
kubectl apply -k k8s/overlays/pi5/

# Check status
./scripts/verify.sh
```

### Access URLs

Add to `/etc/hosts` on any machine that needs access:
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

### Post-Deploy Configuration (one-time)

1. **Plex**: Open `http://plex.local:32400/web` → complete setup wizard → add library pointing to `/media/tv` and `/media/movies`
2. **Prowlarr**: Add indexers → go to Settings → Apps → add Sonarr and Radarr (use their ClusterIP service names as hostnames)
3. **Sonarr**: Settings → Download Clients → add qBittorrent at `qbittorrent:8080` → Settings → Indexers → auto-sync from Prowlarr
4. **Radarr**: Same as Sonarr
5. **Bazarr**: Connect to Sonarr (`sonarr:8989`) and Radarr (`radarr:7878`) → add subtitle providers
6. **Overseerr**: Connect to Plex, Sonarr, Radarr

---

## Secrets Management

The current setup uses Kubernetes Secrets (base64-encoded, stored in etcd). For production hardening:

- **SealedSecrets**: Encrypt secrets with a cluster-specific key so they're safe to commit to git
- **External Secrets Operator**: Pull secrets from AWS Secrets Manager, Vault, etc.
- **Talos**: Encrypts etcd at rest by default

For home use, Kubernetes Secrets + git-ignoring the `.env` file is sufficient.

---

## Maintenance

```bash
# Update all images (trigger pod recreation with new pull)
kubectl rollout restart deployment -n media

# View logs for a service
kubectl logs -n media deploy/sonarr -f

# Check VPN status
kubectl exec -n media deploy/gluetun-qbittorrent -c gluetun -- wget -qO- http://localhost:8000/v1/publicip/ip

# Expand a PVC (if your storage class supports it)
kubectl patch pvc plex-config-pvc -n media -p '{"spec":{"resources":{"requests":{"storage":"50Gi"}}}}'
```

---

## File Structure

```
.
├── .env.example                 # Configuration template
├── .gitignore
├── k8s/
│   ├── base/                    # Base manifests (environment-agnostic)
│   │   ├── kustomization.yaml
│   │   ├── namespace.yaml
│   │   ├── configmap.yaml       # Non-sensitive config
│   │   ├── network-policies.yaml
│   │   ├── storage/             # PVs, PVCs, StorageClass
│   │   ├── gluetun-qbittorrent/ # VPN sidecar + torrent client
│   │   ├── prowlarr/
│   │   ├── sonarr/
│   │   ├── radarr/
│   │   ├── bazarr/
│   │   ├── overseerr/
│   │   ├── plex/
│   │   └── flaresolverr/
│   └── overlays/
│       └── pi5/                 # Pi 5 specific patches (node selector)
└── scripts/
    ├── bootstrap.sh             # One-time cluster setup
    ├── create-secrets.sh        # Creates K8s Secret from .env
    └── verify.sh                # Health check
```

---

## Roadmap / Open Questions

- [ ] **Hardware transcoding**: Pi 5's VideoCore VII supports H.264/H.265. Requires `/dev/dri` device mount + `privileged: true` in the Plex pod. Toggle commented out in `k8s/base/plex/deployment.yaml`.
- [ ] **MetalLB**: For the Plex `LoadBalancer` service to get a real LAN IP without `hostNetwork`, install MetalLB and configure an IP pool from your LAN range.
- [ ] **Ingress TLS**: Add cert-manager + Let's Encrypt for HTTPS (needed for Overseerr external access).
- [ ] **Monitoring**: Prometheus + Grafana for resource tracking on the Pi 5.
- [ ] **Multi-node**: Replace `media-local` PVs with an NFS-backed StorageClass or Longhorn for shared storage across nodes.
- [ ] **Image pinning**: Replace `latest` tags with specific versions and automate updates via Renovate or Dependabot.
- [ ] **Talos migration**: Once validated on Raspberry Pi OS + K3s, document the Talos migration path.
