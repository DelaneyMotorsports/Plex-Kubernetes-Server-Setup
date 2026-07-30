# Ansible — the machine layer

Provisions the Plex/K3s box(es) and bootstraps GitOps. After `site.yml` runs, Argo CD owns the
workloads; you should rarely need Ansible again except to add/rebuild nodes.

## Prerequisites (on your workstation)
- Ansible 2.14+ and SSH access to the target box(es).
- Only `ansible.builtin` modules are used — no Galaxy collections to install.

## Configure
1. `inventory/hosts.yml` — set `ansible_host` and `ansible_user` for each box. Put the control-plane
   node under `[k3s_server]`; workers under `[k3s_agent]`.
2. `inventory/group_vars/all.yml` — K3s version, NAS IP/export, timezone, and feature flags
   (`enable_tailscale`, versions).

## Run
```bash
ansible-playbook site.yml                                   # provision everything
ansible-playbook site.yml -e enable_tailscale=true \        # + secure remote access
                          -e tailscale_authkey=tskey-auth-xxxx
ansible-playbook add-node.yml -e target=<host>              # join a new worker
ansible-playbook reset.yml -e target=<host>                 # tear K3s off a box (destructive)
```

The on-box one-liner (`install.sh` at the repo root) runs `site.yml` against `localhost` using
`inventory/localhost.yml` — same roles, no SSH.

## Roles
| Role | Does |
|---|---|
| `common` | packages (incl. `nfs-common`), timezone, Raspberry Pi memory-cgroup enablement |
| `nfs_client` | verifies the NAS export is reachable (non-fatal) |
| `k3s_server` | installs the K3s control plane, exposes the join token + a user kubeconfig |
| `k3s_agent` | joins a worker using the server's token |
| `ingress_nginx` | installs the ingress-nginx controller (Traefik is disabled) |
| `sealed_secrets` | installs the Sealed Secrets controller |
| `argocd` | installs Argo CD and applies the root App-of-Apps |
| `tailscale` | (optional) installs Tailscale and joins your tailnet |
| `node_labels` | labels nodes with capabilities (e.g. transcode) |
