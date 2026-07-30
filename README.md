# Plex Kubernetes Media Stack

A self-hosted media stack managed like production infrastructure: **Ansible** provisions the
machines, **Argo CD** runs the workloads via GitOps, and a dedicated **NAS** serves the media over
NFS. Plex, automated downloading, VPN-isolated torrenting, and subtitle management — declarative,
remotely manageable, and self-healing.

Two layers, cleanly separated:

- **Ansible** owns the machines (Day 0–1): OS prep, K3s, NFS client, and the one-time bootstrap of
  Argo CD + Sealed Secrets. Adding a node is one command.
- **Argo CD** owns the workloads (Day 2–forever): it continuously reconciles the cluster to this
  Git repo. Drift is reverted automatically, rollbacks are `git revert`, and a rebuilt node repaints
  itself from Git with no human intervention.

Bulk media lives on a **separate NAS box** ("Nomad") and is mounted into the cluster over NFS, so the
compute nodes stay disposable and the library survives any node being reimaged.

---

## Topology

```
┌───────────────────────────┐        NFS (RWX, hardlink-capable)        ┌────────────────────────┐
│   NAS  ("Nomad" box)       │◄──────────────────────────────────────────│  Plex box (K3s)        │
│   /export/media            │                                            │  Pi 5 / x86 / VM       │
│     ├── media/{tv,movies}  │        media pods mount:                   │                        │
│     └── downloads/         │          /media      (subPath: media)      │  Plex · Sonarr · Radarr│
│   (owned by 1000:1000)     │          /downloads  (subPath: downloads)  │  Prowlarr · Bazarr ... │
└───────────────────────────┘                                            └────────────────────────┘
        one NFS export, media + downloads under one root  ⇒  instant hardlink imports

Managed by:
  ansible/   ──►  provisions the Plex box: K3s + Sealed Secrets + Argo CD
  argocd/    ──►  root App-of-Apps ─► media-stack Application (selfHeal + prune)
  k8s/       ──►  the Kubernetes manifests Argo continuously applies
```

---

## How it stays healthy (no human intervention)

| Failure | Who heals it | You do |
|---|---|---|
| A pod crashes | K8s controller restarts it | nothing |
| Someone hand-edits a live resource (drift) | Argo CD `selfHeal` reverts it to Git | nothing |
| You want a change | `git commit` → Argo syncs | commit |
| A change was bad | `git revert` → Argo rolls back | revert |
| The whole box dies / is reimaged | `ansible-playbook site.yml` rebuilds K3s+Argo → Argo repaints every app from Git; media is intact on the NAS; app configs restore from the nightly NAS backup | one command |
| You need more capacity | `ansible-playbook add-node.yml -e target=<host>` | one command |

---

## Install

### One-line (on the Plex box itself)

```bash
curl -sSL https://raw.githubusercontent.com/DelaneyMotorsports/Plex-Kubernetes-Server-Setup/main/install.sh | bash
```

The installer is a thin bootstrap: it installs Ansible + git, clones the repo, and runs
`ansible/site.yml` against the local machine. That brings up K3s, the Sealed Secrets controller, and
Argo CD, then Argo takes over deploying the media stack from Git.

> **Review it first?** `curl -sSL ...install.sh | less` — encouraged.

Pass config through env vars to skip interaction:

```bash
export NAS_IP="192.168.1.50" NAS_EXPORT_PATH="/export/media"
export GITOPS_REPO_URL="https://github.com/<you>/Plex-Kubernetes-Server-Setup.git"
curl -sSL https://raw.githubusercontent.com/DelaneyMotorsports/Plex-Kubernetes-Server-Setup/main/install.sh | bash
```

### Remote (manage a fleet from your workstation — the IT-pro path)

```bash
git clone https://github.com/DelaneyMotorsports/Plex-Kubernetes-Server-Setup.git
cd Plex-Kubernetes-Server-Setup/ansible

# 1. Describe your machine(s)
$EDITOR inventory/hosts.yml            # set ansible_host + SSH user
$EDITOR inventory/group_vars/all.yml   # NAS IP/export, versions, feature flags

# 2. Provision everything
ansible-playbook site.yml
# optional secure remote access:
ansible-playbook site.yml -e enable_tailscale=true -e tailscale_authkey=tskey-auth-xxxx
```

### Finish (two commits, both picked up by Argo)

```bash
# a) Point storage at your NAS
$EDITOR k8s/overlays/pi5/nas-patch.yaml   # server = NAS LAN IP, path = export
# b) Seal your secrets into Git (encrypted, safe to commit)
cp .env.example .env && $EDITOR .env      # WireGuard keys, Plex claim
./scripts/seal-secrets.sh .env            # writes k8s/base/sealed-secret.yaml
git commit -am "configure NAS + secrets" && git push
```

Argo CD reconciles both within its sync window — no `kubectl apply` needed.

---

## The NAS (Nomad box)

Media lives on a **separate machine** running as a NAS. This repo does not manage that box; it only
mounts it. Requirements:

- Export **one directory** (e.g. `/export/media`) that contains both `media/` (with `tv/`, `movies/`,
  `music/`) and `downloads/` (with `complete/`, `incomplete/`). Keeping them under one export is what
  makes Sonarr/Radarr imports **instant hardlinks** instead of slow, space-doubling copies.
- Own the export as **UID:GID `1000:1000`** (matches `PUID`/`PGID` in `k8s/base/configmap.yaml`) and
  export it so writes as that user succeed — e.g. `no_root_squash`, or `all_squash` with
  `anonuid=1000,anongid=1000`.
- Any filesystem is fine (ext4/XFS/etc.) — redundancy is the NAS's concern, not this repo's.

Set the cluster's view of it in `k8s/overlays/pi5/nas-patch.yaml` (the one place to edit for storage).

---

## Why Kubernetes (K3s) + GitOps instead of Docker Compose

| | Docker Compose | This stack (K3s + Argo CD) |
|---|---|---|
| Self-healing | Manual restart policies | Controllers restart pods **and** Argo reverts drift |
| Config source of truth | Files copied between hosts | Git — audited, revertable |
| Rolling updates | Stop → pull → start | Zero-downtime rollout |
| Secrets | `.env` on disk | Sealed Secrets (encrypted, in Git) |
| Network isolation | Docker networks | NetworkPolicies + namespace isolation |
| Rebuild a dead host | Re-run everything by hand | `ansible-playbook site.yml`, Argo repaints |
| Add a node | Rewire compose/hosts | `ansible-playbook add-node.yml` |

### Key design decisions

**Single NFS export, mounted via subPath.** `media-nfs-pvc` (ReadWriteMany) is mounted as
`/media` (`subPath: media`) and `/downloads` (`subPath: downloads`). Both are the same underlying
filesystem, so hardlinks/atomic-moves work across them. RWX also means pods can run on **any** node —
the storage no longer pins the cluster to one machine.

**App config stays local, backed up to the NAS.** Config volumes (Plex DB, *arr configs — all SQLite)
use the node's local-path storage, because SQLite over NFS has locking problems. A nightly CronJob
(`k8s/base/backup/`) tars that data to the NAS, so a reimaged node restores from the latest snapshot.

**Gluetun + qBittorrent share a pod network namespace.** All qBittorrent traffic physically cannot
leave except through the WireGuard tunnel — no routing rules. A `wait-for-vpn` init container blocks
qBittorrent until Gluetun reports a connected VPN IP.

**No Cloudflare dependencies.** No Tunnel, no WARP, no proxied domains. Remote access is via Tailscale
(optional) or your own network.

---

## Services

| Service | Port | Purpose |
|---|---|---|
| Plex | 32400 | Media server — streams to all clients (mounts media read-only) |
| Sonarr | 8989 | TV series automation |
| Radarr | 7878 | Movie automation |
| Prowlarr | 9696 | Indexer aggregator |
| Bazarr | 6767 | Subtitle downloading |
| Overseerr | 5055 | Request portal for family/friends |
| qBittorrent | 8080 | Torrent client (VPN-isolated) |
| Gluetun | — | WireGuard VPN gateway |

Plus a range of enrichment/maintenance apps (Tdarr, Janitorr, ErsatzTV, Recyclarr, Kometa, and more)
under `k8s/base/`.

---

## Remote management

- **Argo CD UI** is the console. Get the admin password and reach it:
  ```bash
  kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo
  kubectl -n argocd port-forward svc/argocd-server 8080:443
  ```
- **Tailscale** (optional, via the Ansible role) puts the Plex box on your tailnet, so the Argo UI and
  every service are reachable from anywhere with no public ports exposed.

---

## Post-install configuration

After the pods are up, wire the apps together once via their web UIs:

1. **Prowlarr** — add indexers.
2. **Sonarr/Radarr** — sync indexers from Prowlarr; add qBittorrent (host `qbittorrent`, port `8080`).
3. **Bazarr** — connect to `sonarr:8989` and `radarr:7878`.
4. **Overseerr** — connect to Plex, Sonarr, Radarr.
5. **Plex** — complete setup at `http://plex.local:32400/web`; add libraries at `/media/tv` and
   `/media/movies`.

---

## Access

Add to `/etc/hosts` (or your local DNS/Pi-hole):

```
<PLEX_BOX_IP>  plex.local sonarr.local radarr.local prowlarr.local
<PLEX_BOX_IP>  bazarr.local overseerr.local qbittorrent.local
```

The apps are served over HTTP on port **80** by ingress-nginx, which K3s ServiceLB (klipper) binds to
the node's IP — so `http://sonarr.local` just works, no port suffix. (Plex is the exception: it uses
`hostNetwork` and answers directly on `:32400`.) On a multi-node cluster, swap ServiceLB for MetalLB
with a dedicated address pool.

---

## Maintenance

```bash
# See what Argo thinks (sync/health of every app)
kubectl -n argocd get applications

# Stream logs from a service
kubectl logs -n media deploy/sonarr -f

# Confirm the VPN exit IP
kubectl exec -n media deploy/gluetun-qbittorrent -c gluetun -- wget -qO- http://localhost:8000/v1/publicip/ip

# Health snapshot
./scripts/verify.sh

# Add a worker node
ansible-playbook ansible/add-node.yml -e target=<host-in-inventory>

# Re-provision a box from scratch (media on the NAS is untouched)
ansible-playbook ansible/reset.yml -e target=<host> && ansible-playbook ansible/site.yml
```

---

## Repository structure

```
.
├── install.sh                   # thin bootstrap: installs Ansible, runs site.yml
├── ansible/                     # Layer 1 — the machines
│   ├── site.yml                 #   full provision (K3s + Sealed Secrets + Argo CD)
│   ├── add-node.yml             #   one-command node join
│   ├── reset.yml                #   teardown / re-provision
│   ├── inventory/               #   fleet as code (+ group_vars, localhost inventory)
│   └── roles/                   #   common, k3s_server, k3s_agent, nfs_client, ingress_nginx,
│                                #   sealed_secrets, argocd, tailscale, node_labels
├── argocd/                      # Layer 2 — GitOps
│   ├── root.yaml                #   App-of-Apps entrypoint
│   └── apps/                    #   AppProject + media-stack Application (selfHeal/prune)
├── k8s/
│   ├── base/                    # environment-agnostic manifests
│   │   ├── storage/             #   NFS PV + RWX claim + StorageClass
│   │   ├── backup/              #   nightly config backup CronJob → NAS
│   │   ├── sealed-secret.yaml   #   encrypted secrets (generated by seal-secrets.sh)
│   │   └── <service>/           #   one dir per app
│   └── overlays/pi5/            # node pinning + nas-patch.yaml (your NAS IP)
└── scripts/
    ├── seal-secrets.sh          # encrypt secrets into Git (GitOps path)
    ├── create-secrets.sh        # imperative secret (non-GitOps fallback)
    ├── bootstrap.sh             # direct kubectl apply (non-GitOps fallback)
    └── verify.sh                # health check
```

---

## OS options for the Plex box

The Ansible `common` role targets **Debian-family** systems (Raspberry Pi OS Lite 64-bit, Ubuntu,
Debian) and auto-enables the memory cgroup on Raspberry Pi (required by K3s). Fedora is also handled
for package installs. For an immutable option, Talos Linux can host the cluster; point the Argo CD
bootstrap at it instead of running the K3s roles (Pi 5 support since Talos v1.7).

---

## Roadmap

- [x] **NFS media storage** — media on the NAS, mounted RWX with hardlink support.
- [x] **GitOps** — Argo CD App-of-Apps with self-heal + prune.
- [x] **Declarative provisioning** — Ansible for K3s, controllers, and node joins.
- [x] **Encrypted secrets in Git** — Sealed Secrets.
- [x] **Config disaster recovery** — nightly backup to the NAS.
- [ ] **Hardware transcoding** — Pi 5 VideoCore VII; uncomment the `/dev/dri` mount in
  `k8s/base/plex/deployment.yaml` and set `privileged: true`.
- [ ] **3-node HA** — embedded-etcd control plane; storage is already RWX-ready.
- [ ] **MetalLB** — dedicated LAN IP for ingress on multi-node (replaces single-node ServiceLB).
- [ ] **TLS / HTTPS** — cert-manager for external Overseerr access.
- [ ] **Image pinning** — replace `latest` tags + Renovate automation.
- [ ] **Monitoring** — Prometheus + Grafana as a new Argo app.

---

*Delaney Motorsports R&D — Kevin Delaney, Director of Research and Development*
