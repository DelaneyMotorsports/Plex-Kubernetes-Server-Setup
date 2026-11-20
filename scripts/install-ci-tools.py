#!/usr/bin/env python3
"""Install the repository's checksum-pinned Linux AMD64 validation tools."""
import argparse
import bz2
import hashlib
import io
import json
from pathlib import Path
import platform
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'AMD64'):
        parser.error('These CI binaries require Linux AMD64; use native tools on other hosts')
    args.destination.mkdir(parents=True, exist_ok=True)
    tools = json.loads((ROOT / 'ci/tools.json').read_text())
    for name, spec in tools.items():
        with urllib.request.urlopen(spec['url'], timeout=90) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != spec['sha256']:
            raise RuntimeError('Checksum mismatch: ' + name)
        if spec.get('member'):
            with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as archive:
                payload = archive.extractfile(spec['member']).read()
        elif spec.get('compression') == 'bz2':
            payload = bz2.decompress(data)
        else:
            payload = data
        target = args.destination / name
        target.write_bytes(payload)
        target.chmod(0o755)
        print('Installed pinned ' + name)


if __name__ == '__main__':
    main()
