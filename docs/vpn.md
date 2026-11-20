# VPN startup and verification

Gluetun is a restartable init sidecar. Its startup probe must succeed before
qBittorrent starts. Startup gets five minutes; readiness removes an unhealthy pod
from Service endpoints, and liveness allows two minutes for Gluetun's internal
VPN self-healing before restarting its container. Probes execute the image's
healthcheck command, which uses its internal health server. They never call the
credential-bearing control API or depend on anonymous access to port 8000.

Control-server authentication remains enabled, with the listener bound to
127.0.0.1:8000. There is no Service exposing it. Only qBittorrent UI port 8080 is
allowed through Gluetun's normal-interface firewall. The VPN-side firewall is
not opened for an assumed provider-forwarded port.

`FIREWALL_OUTBOUND_SUBNETS` lists K3s defaults 10.42.0.0/16 (pods) and
10.43.0.0/16 (services). Edit these in the Gluetun Deployment if your cluster uses
different ranges. Do not substitute 0.0.0.0/0 or broad LAN ranges; do not overlap
the WireGuard tunnel subnet. Cluster-local traffic is the explicit exception to
VPN routing. DNS/health targets use Quad9, Google ICMP and GitHub without depending
on Cloudflare DNS or its health endpoint.

After supplying your own VPN keys and syncing the branch:

```bash
kubectl -n media rollout status deployment/gluetun-qbittorrent --timeout=600s
kubectl -n media exec deployment/gluetun-qbittorrent -c gluetun -- /gluetun-entrypoint healthcheck
kubectl -n media logs deployment/gluetun-qbittorrent -c gluetun --since=10m | grep -i 'public ip'
```

Confirm the reported IP belongs to your VPN, and confirm Sonarr/Radarr can reach
qBittorrent at `http://qbittorrent:8080`. A live credentialed test is still needed:
in an isolated test deployment, interrupt its VPN connection and verify downloads
lose internet access while the pod becomes unready, then verify automatic recovery.
Do not disable Gluetun's firewall to perform that test. CI checks the startup and
firewall configuration but cannot prove your provider's tunnel is leak-free.
