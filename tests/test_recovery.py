import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('recovery', ROOT / 'k8s/base/backup/config-recovery.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        self.claim = self.source / 'plex-config-pvc'
        self.claim.mkdir(parents=True)
        self.work = self.root / 'work'
        self.keys = self.root / 'keys.json'
        self.keys.write_text(json.dumps({'items': [{'metadata': {
            'name': 'sealed-secrets-key-fixture', 'namespace': 'kube-system',
            'uid': 'must-not-restore', 'resourceVersion': '123',
            'labels': {'sealedsecrets.bitnami.com/sealed-secrets-key': 'active'}},
            'data': {'tls.key': 'Zml4dHVyZQ==', 'tls.crt': 'Zml4dHVyZQ=='}}]}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_live_wal_database_and_numeric_ownership(self):
        db = self.claim / 'library.db'
        with sqlite3.connect(db) as conn:
            conn.execute('pragma journal_mode=wal')
            conn.execute('create table media (name text)')
            conn.execute('insert into media values (?)', ('committed-in-wal',))
            conn.commit()
            self.assertTrue(Path(str(db) + '-wal').exists())
            (self.claim / 'settings.json').write_text('{"configured":true}')
            recovery.snapshot_tree(self.claim, self.root / 'copy')
        with sqlite3.connect(self.root / 'copy/library.db') as conn:
            self.assertEqual(conn.execute('select name from media').fetchone()[0], 'committed-in-wal')
            self.assertEqual(conn.execute('pragma integrity_check').fetchone()[0], 'ok')
        conn.close()
        self.assertFalse((self.root / 'copy/library.db-wal').exists())
        self.assertEqual((self.root / 'copy/settings.json').read_text(), '{"configured":true}')
        self.assertEqual((self.root / 'copy').stat().st_uid, self.claim.stat().st_uid)

    def test_empty_or_unrelated_key_backup_is_rejected(self):
        self.keys.write_text('{"items":[]}')
        with self.assertRaisesRegex(RuntimeError, 'No Sealed Secrets'):
            recovery.sealed_keys(self.keys)

    def test_sealing_keys_remove_cluster_specific_metadata(self):
        key = recovery.sealed_keys(self.keys)['items'][0]
        self.assertNotIn('uid', key['metadata'])
        self.assertNotIn('resourceVersion', key['metadata'])
        self.assertIn('tls.key', key['data'])

    @unittest.skipUnless(shutil.which('restic'), 'restic required for encrypted round-trip')
    def test_encrypted_roundtrip_and_nonempty_restore_refusal(self):
        (self.claim / 'preferences.xml').write_text('<Preferences fixture="true"/>')
        env = {'RESTIC_REPOSITORY': str(self.root / 'repository'),
               'RESTIC_PASSWORD': 'test-fixture-password-not-a-real-secret',
               'RESTIC_CACHE_DIR': str(self.root / 'cache')}
        with patch.dict(os.environ, env), patch.object(recovery, 'ARCHIVE_ROOT', str(self.work / 'snapshot')):
            recovery.backup(self.source, self.work, self.keys)
            self.assertFalse((self.work / 'snapshot').exists())
            with self.assertRaisesRegex(RuntimeError, 'not empty'):
                recovery.restore(self.source, self.work, 'latest')
            self.assertEqual((self.claim / 'preferences.xml').read_text(), '<Preferences fixture="true"/>')
            (self.claim / 'preferences.xml').unlink()
            recovery.restore(self.source, self.work, 'latest')
            self.assertEqual((self.claim / 'preferences.xml').read_text(), '<Preferences fixture="true"/>')
            invalid = subprocess.run(['restic', 'snapshots'], env={**os.environ, 'RESTIC_PASSWORD': 'wrong'},
                                     capture_output=True)
            self.assertNotEqual(invalid.returncode, 0)
        self.assertFalse((self.work / 'restored').exists())

    def test_failed_backup_cleans_plaintext_staging(self):
        (self.claim / 'settings').write_text('fixture')
        with patch.dict(os.environ, {'RESTIC_REPOSITORY': str(self.root / 'repository')}), \
                patch.object(recovery, 'run', side_effect=RuntimeError('storage unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'storage unavailable'):
                recovery.backup(self.source, self.work, self.keys)
        self.assertFalse((self.work / 'snapshot').exists())


if __name__ == '__main__':
    unittest.main()
