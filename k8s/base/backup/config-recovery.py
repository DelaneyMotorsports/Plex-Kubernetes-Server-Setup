#!/usr/bin/env python3
"""Consistent SQLite config snapshots and encrypted, logical-PVC restores."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import ssl
import subprocess
import urllib.request

FORMAT = 1
ARCHIVE_ROOT = '/work/snapshot'


def run(*args):
    subprocess.run(args, check=True)


def is_sqlite(path):
    if path.is_symlink() or not path.is_file():
        return False
    with path.open('rb') as stream:
        return stream.read(16) == b'SQLite format 3\x00'


def copy_metadata(source, target):
    shutil.copystat(source, target, follow_symlinks=False)
    info = source.lstat()
    os.chown(target, info.st_uid, info.st_gid, follow_symlinks=False)


def snapshot_tree(source, target):
    """Copy ordinary config and use SQLite's backup API for live databases.

    WAL and SHM sidecars are excluded only when the corresponding database is
    SQLite. A copy failure aborts the snapshot; no previous backup is deleted.
    """
    target.mkdir(parents=True)
    for item in sorted(source.iterdir()):
        out = target / item.name
        if item.is_symlink():
            out.symlink_to(os.readlink(item))
        elif item.is_dir():
            snapshot_tree(item, out)
        elif any(item.name.endswith(suffix) and is_sqlite(
                item.with_name(item.name[:-len(suffix)]))
                for suffix in ('-wal', '-shm', '-journal')):
            continue
        elif is_sqlite(item):
            # mode=ro includes committed WAL transactions; immutable=1 would not.
            with closing(sqlite3.connect(item.resolve().as_uri() + '?mode=ro', uri=True,
                                         timeout=60)) as src:
                with closing(sqlite3.connect(out)) as dst:
                    src.backup(dst, pages=256, sleep=0.05)
            copy_metadata(item, out)
        elif item.is_file():
            shutil.copy2(item, out)
            copy_metadata(item, out)
        else:
            raise RuntimeError(f'Unsupported config file type: {item}')
    copy_metadata(source, target)


def sealed_keys(keys_file=None):
    if keys_file:
        data = json.loads(Path(keys_file).read_text())
    else:
        sa = Path('/var/run/secrets/kubernetes.io/serviceaccount')
        host = os.environ['KUBERNETES_SERVICE_HOST']
        if ':' in host:
            host = '[' + host + ']'
        port = os.environ.get('KUBERNETES_SERVICE_PORT_HTTPS', '443')
        url = (f'https://{host}:{port}/api/v1/namespaces/kube-system/secrets'
               '?labelSelector=sealedsecrets.bitnami.com%2Fsealed-secrets-key')
        request = urllib.request.Request(url, headers={
            'Authorization': 'Bearer ' + (sa / 'token').read_text().strip()})
        context = ssl.create_default_context(cafile=str(sa / 'ca.crt'))
        # Cluster API must be reached directly, never through an internet proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                            urllib.request.HTTPSHandler(context=context))
        with opener.open(request, timeout=30) as response:
            data = json.load(response)
    items = []
    for secret in data.get('items', []):
        metadata = secret['metadata']
        labels = metadata.get('labels', {})
        if 'sealedsecrets.bitnami.com/sealed-secrets-key' not in labels:
            continue
        if not secret.get('data', {}).get('tls.key'):
            raise RuntimeError('Sealing key lacks its private key')
        items.append({'apiVersion': 'v1', 'kind': 'Secret',
                      'metadata': {k: metadata[k] for k in
                                   ('name', 'namespace', 'labels', 'annotations')
                                   if k in metadata},
                      'type': secret.get('type', 'kubernetes.io/tls'),
                      'data': secret['data']})
    if not items:
        raise RuntimeError('No Sealed Secrets private keys found; backup aborted')
    return {'apiVersion': 'v1', 'kind': 'List', 'items': items}


def backup(source, work, keys_file=None):
    root = work / 'snapshot'
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(mode=0o700, parents=True)
    try:
        keys = sealed_keys(keys_file)
        claims = sorted(p.name for p in source.iterdir() if p.is_dir())
        if not claims:
            raise RuntimeError('No mounted config PVCs found')
        for name in claims:
            snapshot_tree(source / name, root / 'configs' / name)
        key_path = root / 'sealed-secrets-keys.json'
        key_path.write_text(json.dumps(keys))
        key_path.chmod(0o600)
        (root / 'manifest.json').write_text(json.dumps({
            'format': FORMAT, 'claims': claims, 'archive_root': ARCHIVE_ROOT}))
        repository = Path(os.environ['RESTIC_REPOSITORY'])
        if not (repository / 'config').exists():
            run('restic', 'init')
        run('restic', 'backup', str(root), '--host', 'media-stack',
            '--tag', 'media-config')
        run('restic', 'forget', '--host', 'media-stack', '--tag', 'media-config',
            '--keep-daily', '7', '--keep-weekly', '4', '--keep-monthly', '3', '--prune')
    finally:
        # Never leave plaintext keys/config in staging after success or failure.
        if root.exists():
            shutil.rmtree(root)


def restore(source, work, snapshot, overwrite=False):
    target = work / 'restored'
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, mode=0o700)
    try:
        run('restic', 'restore', snapshot, '--host', 'media-stack', '--tag',
            'media-config', '--target', str(target), '--verify')
        root = target / ARCHIVE_ROOT.lstrip('/')
        manifest = json.loads((root / 'manifest.json').read_text())
        claims = manifest['claims']
        mounted = sorted(p.name for p in source.iterdir() if p.is_dir())
        if manifest.get('format') != FORMAT or sorted(claims) != mounted:
            raise RuntimeError('Backup PVC set/format differs from this installation; '
                               'use the matching repository revision')
        # Validate every destination before changing any volume.
        for name in claims:
            if name != Path(name).name or name in ('.', '..'):
                raise RuntimeError('Invalid PVC name in snapshot')
            dest = source / name
            if dest.is_symlink() or not (root / 'configs' / name).is_dir():
                raise RuntimeError('Missing snapshot or invalid destination')
            if not overwrite and any(dest.iterdir()):
                raise RuntimeError(f'{name} is not empty; use --overwrite only after review')
        for name in claims:
            dest = source / name
            for entry in dest.iterdir():
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
            # snapshot_tree also preserves permissions and numeric ownership.
            stage = root / 'configs' / name
            for entry in stage.iterdir():
                out = dest / entry.name
                if entry.is_dir() and not entry.is_symlink():
                    snapshot_tree(entry, out)
                elif entry.is_symlink():
                    out.symlink_to(os.readlink(entry))
                else:
                    shutil.copy2(entry, out)
                    copy_metadata(entry, out)
            copy_metadata(stage, dest)
    finally:
        if target.exists():
            shutil.rmtree(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['backup', 'restore'])
    parser.add_argument('--source', type=Path, default=Path('/config-volumes'))
    parser.add_argument('--work', type=Path, default=Path('/work'))
    parser.add_argument('--keys-file')
    parser.add_argument('--snapshot', default=os.environ.get('RESTORE_SNAPSHOT', 'latest'))
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    if not os.environ.get('RESTIC_PASSWORD'):
        parser.error('RESTIC_PASSWORD is required and must be kept off-cluster too')
    os.environ.setdefault('RESTIC_REPOSITORY', '/backup/restic')
    os.environ.setdefault('RESTIC_CACHE_DIR', str(args.work / 'cache'))
    os.umask(0o077)
    if args.action == 'backup':
        backup(args.source, args.work, args.keys_file)
    else:
        restore(args.source, args.work, args.snapshot,
                args.overwrite or os.environ.get('RESTORE_OVERWRITE') == 'true')


if __name__ == '__main__':
    main()
