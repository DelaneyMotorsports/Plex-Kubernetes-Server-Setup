from pathlib import Path
import ipaddress
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class VpnTests(unittest.TestCase):
    def setUp(self):
        doc = yaml.safe_load((ROOT / 'k8s/base/gluetun-qbittorrent/deployment.yaml').read_text())
        self.spec = doc['spec']['template']['spec']
        self.vpn = self.spec['initContainers'][0]
        self.env = {e['name']: e['value'] for e in self.vpn['env']}

    def test_client_start_is_gated_by_native_sidecar_health(self):
        self.assertEqual(len(self.spec['initContainers']), 1)
        self.assertEqual(self.vpn['restartPolicy'], 'Always')
        for probe in ('startupProbe', 'livenessProbe', 'readinessProbe'):
            self.assertEqual(self.vpn[probe]['exec']['command'], ['/gluetun-entrypoint', 'healthcheck'])
        self.assertEqual(self.spec['containers'][0]['name'], 'qbittorrent')

    def test_control_api_is_private_and_firewall_has_no_internet_bypass(self):
        self.assertEqual(self.env['HTTP_CONTROL_SERVER_ADDRESS'], '127.0.0.1:8000')
        self.assertNotIn('HTTP_CONTROL_SERVER_AUTH_DEFAULT_ROLE', self.env)
        self.assertEqual(self.env['FIREWALL'], 'on')
        self.assertEqual(self.env['FIREWALL_INPUT_PORTS'], '8080')
        for subnet in self.env['FIREWALL_OUTBOUND_SUBNETS'].split(','):
            network = ipaddress.ip_network(subnet)
            self.assertTrue(network.is_private)
            self.assertGreaterEqual(network.prefixlen, 16)
        self.assertNotIn('NET_ADMIN', self.spec['containers'][0].get('securityContext', {}).get('capabilities', {}).get('add', []))


if __name__ == '__main__':
    unittest.main()
