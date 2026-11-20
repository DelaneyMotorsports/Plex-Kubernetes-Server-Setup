# Config backup and recovery

This protects application configuration and Sealed Secrets private keys. Bulk media
needs a separate NAS backup. A single-node loss is recoverable only if the NAS
repository and its password survive. Keep the password in an off-cluster password
manager before relying on the schedule. Losing it makes encrypted backups unreadable.

## Enable and verify

1. Create `backups/` beneath the existing NFS export and allow the backup job to write
   it. Do not publish that directory through Plex or other media applications.
2. Run `./scripts/create-backup-secret.sh`. The password is a separate Kubernetes
   Secret, never the shared application Secret and never a Git file. Preserve its
   value off-cluster. Recreate this Secret when recovering a new cluster.
3. Sync the backup manifests, then run:

   ```bash
   kubectl -n media create job --from=cronjob/config-backup config-backup-check
   kubectl -n media logs -f job/config-backup-check -c backup
   kubectl -n media wait --for=condition=complete job/config-backup-check --timeout=7200s
   ```

The job runs at 03:00 America/New_York. It stages ordinary config files and uses
SQLite's online backup API, including committed WAL data, instead of copying live
SQLite files with tar. Missing sealing keys or a failed copy abort the backup.
Restic encrypts the snapshot before storing it under `backups/restic` on the NAS.
Only a successful snapshot is followed by retention: seven daily, four weekly,
and three monthly snapshots. Plaintext staging is removed on success and failure;
Kubernetes removes the ephemeral volume after the pod is deleted.

The archive maps data by logical PVC name, not by generated local-path directory.
All config PVCs are mounted read-only for backup. The PVC affinities constrain the
job to the node holding them; this is a **single-node config backup**. Do not split
config PVCs across nodes without implementing one backup/restore unit per node.
The job will remain Pending rather than silently backing up the wrong host path.

Staging requires free disk space approximately equal to the config dataset, with a
100 GiB ceiling. Restic restore also needs that much staging space. These are disk
volumes, not RAM. Inspect ephemeral-storage capacity before enabling the schedule.
The backup identity can list Secrets in kube-system because Kubernetes RBAC cannot
restrict a list operation to labels. The script exports only sealing-key Secrets.
Treat this pod, its service account, and its password as privileged backup access.

## Recover a rebuilt cluster

Use the Git revision corresponding to the backup's PVC set. Keep root and media
Argo applications paused during recovery; do not let new apps initialize their
config volumes first. Existing installations are paused by the restore script.

1. Provision K3s and Sealed Secrets. Apply the matching storage, backup and config
   manifests, including their PVCs. On a fresh installation keep media Deployments
   at zero replicas while recovery is in progress. Configure the NAS overlay and
   create `config-backup-secret` with the original offline password.
2. Mount the NAS backup directory on your administration machine. Install restic
   0.18.1 and kubectl. Set `RESTIC_REPOSITORY` to its `restic` subdirectory and read
   the original password without including it in shell command history:

   ```bash
   export RESTIC_REPOSITORY=/mnt/nas/backups/restic
   read -r -s -p 'Backup password: ' RESTIC_PASSWORD; echo
   export RESTIC_PASSWORD
   restic snapshots --host media-stack --tag media-config
   ./scripts/restore-sealed-secrets.sh <snapshot-id>
   ```

   This restores the original sealing keys before the controller decrypts Git
   secrets, and restarts the controller. A short-lived private temporary directory
   holds the recovered key document and is removed on exit. Do not store it in Git.
3. Restore configuration with the same explicit snapshot ID:

   ```bash
   ./scripts/restore-config.py --snapshot <snapshot-id>
   ```

   The script records original replica counts and Argo policies in the
   `media-recovery-state` ConfigMap, disables root/child auto-sync, waits for any
   active sync to end, suspends scheduled backups, and stops all media Deployments.
   The one-shot restore Job checks Restic integrity and every destination before
   writing any config. It receives no Kubernetes API token. Nonempty volumes are
   refused. For an intentional rollback into existing volumes, inspect the snapshot
   first and explicitly add `--overwrite`.
4. Inspect `kubectl -n media logs job/<restore-job> -c backup`, verify the chosen
   snapshot and application data, then run:

   ```bash
   ./scripts/restore-config.py --resume
   ```

   Resume requires a successful restore Job and reinstates original replicas,
   schedule and Argo policies. A failed restore keeps workloads stopped. Inspect
   the Job and preserve `media-recovery-state`; do not resume after a failure.
   To retry a failed Job, use the retry procedure below.

The former tar archives are not Restic snapshots. Preserve them separately for
manual recovery until a successful encrypted backup has been verified. Restic
repository maintenance does not delete those old archives.

## Failed restore retry

First inspect the failed Job logs and fix the cause. Workloads and reconciliation
must remain paused. Keep the original `media-recovery-state` ConfigMap. Run
`./scripts/restore-config.py --retry --snapshot <snapshot-id>` to make a new restore
Job while retaining the original resume state. If a previous attempt wrote some
files, inspect them and explicitly add `--overwrite`. A failed Job never resumes
applications automatically.

## Recovery drill

Run `python3 -m unittest discover -s tests -v` with restic on PATH. Tests exercise a
live WAL database, encrypted backup/restore, missing keys, failed backup cleanup,
wrong passwords and refusal to overwrite existing data. These local tests do not
replace a restore drill on a spare Kubernetes node with a copy of your real NAS
repository. Record the last successful backup and restore drill in your operations log.
