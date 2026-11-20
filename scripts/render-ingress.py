#!/usr/bin/env python3
"""Render exactly the Traefik values used by the Ansible bootstrap."""
import argparse
from pathlib import Path
import subprocess
from jinja2 import StrictUndefined, Template
import yaml
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    variables = yaml.safe_load((ROOT / 'ansible/inventory/group_vars/all.yml').read_text())
    template = Template((ROOT / 'ansible/roles/ingress_traefik/templates/media-ingress.yaml.j2').read_text(),
                        undefined=StrictUndefined)
    chart = yaml.safe_load(template.render(**variables))
    values = args.directory / 'traefik-values.values'
    values.write_text(chart['spec']['valuesContent'])
    cluster = yaml.safe_load((ROOT / 'ci/cluster.yaml').read_text())
    with (args.directory / 'traefik.yaml').open('w') as output:
        subprocess.run(['helm', 'template', 'media-ingress', 'traefik', '--repo',
                        chart['spec']['repo'], '--version', chart['spec']['version'],
                        '--namespace', chart['spec']['targetNamespace'], '--kube-version',
                        cluster['kubeVersion'], '--values', str(values)], stdout=output, check=True)


if __name__ == '__main__':
    main()
