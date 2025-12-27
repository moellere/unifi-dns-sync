import unittest
from unittest.mock import patch, MagicMock
from main import UnifiController

class TestUnifiController(unittest.TestCase):
    def setUp(self):
        self.config = {
            'host': '1.2.3.4',
            'api_key': 'test-key',
            'site': 'MySite',
            'verify_ssl': False
        }
        self.controller = UnifiController(self.config)

    def mock_site_resolve(self, mock_get):
        # Mock site list response
        mock_sites_response = MagicMock()
        mock_sites_response.status_code = 200
        mock_sites_response.json.return_value = {
            'data': [{'id': 'uuid-mysite', 'name': 'MySite'}]
        }
        return mock_sites_response

    @patch('requests.get')
    def test_get_dns_records(self, mock_get):
        # First call is for sites, second for dns policies
        mock_sites = self.mock_site_resolve(mock_get)
        
        mock_dns = MagicMock()
        mock_dns.status_code = 200
        mock_dns.json.return_value = {
            'data': [
                {'id': '1', 'type': 'A_RECORD', 'domain': 'test.com', 'ipv4Address': '1.1.1.1'}
            ]
        }
        
        mock_get.side_effect = [mock_sites, mock_dns]

        records = self.controller.get_dns_records()
        
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['domain'], 'test.com')
        self.assertEqual(self.controller.site_id, 'uuid-mysite')
        
        # Verify call details for DNS policies
        # mock_get was called twice. Check the last call.
        args, kwargs = mock_get.call_args_list[1]
        self.assertEqual(args[0], 'https://1.2.3.4/proxy/network/integration/v1/sites/uuid-mysite/dns/policies')

    @patch('requests.get')
    def test_get_client_records(self, mock_get):
        mock_sites = self.mock_site_resolve(mock_get)
        
        mock_clients = MagicMock()
        mock_clients.status_code = 200
        mock_clients.json.return_value = {
            'data': [
                {'name': 'client1', 'ipAddress': '192.168.1.50'}
            ]
        }
        
        mock_get.side_effect = [mock_sites, mock_clients]

        self.controller.sync_dhcp_clients = True
        records = self.controller.get_client_records()
        
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['domain'], 'client1')
        self.assertEqual(records[0]['ipv4Address'], '192.168.1.50')

    @patch('requests.post')
    @patch('requests.get')
    def test_create_dns_record(self, mock_get, mock_post):
        mock_get.return_value = self.mock_site_resolve(mock_get)
        
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_post.return_value = mock_response

        record = {'type': 'A_RECORD', 'domain': 'new.com', 'ipv4Address': '2.2.2.2'}
        success = self.controller.create_dns_record(record)
        
        self.assertTrue(success)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertIn('uuid-mysite/dns/policies', args[0])

    @patch('requests.delete')
    @patch('requests.get')
    def test_delete_dns_record(self, mock_get, mock_delete):
        mock_get.return_value = self.mock_site_resolve(mock_get)

        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_delete.return_value = mock_response

        success = self.controller.delete_dns_record('uuid-123')
        
        self.assertTrue(success)
        mock_delete.assert_called_once()
        args, kwargs = mock_delete.call_args
        self.assertIn('uuid-mysite/dns/policies/uuid-123', args[0])

    @patch('requests.get')
    def test_get_client_records_with_suffix(self, mock_get):
        self.controller.sync_dhcp_clients = True
        self.controller.domain_suffix = 'home.arpa'
        
        mock_sites = self.mock_site_resolve(mock_get)
        mock_clients = MagicMock()
        mock_clients.status_code = 200
        mock_clients.json.return_value = {
            'data': [{'name': 'client1', 'ipAddress': '192.168.1.50'}]
        }
        mock_get.side_effect = [mock_sites, mock_clients]

        records = self.controller.get_client_records()
        self.assertEqual(records[0]['domain'], 'client1.home.arpa')

#    @patch('main.UnifiController.get_dns_records')
#    @patch('main.UnifiController.get_client_records')
#    @patch('main.UnifiController.create_dns_record')
#    def test_sync_dns_origin_tracking(self, mock_create, mock_clients, mock_dns):
#        # Setup 2 mock-like configurations
#        c1_cfg = {'host': '1.1.1.1', 'api_key': 'k1'}
#        c2_cfg = {'host': '2.2.2.2', 'api_key': 'k2'}
#        
#        with patch('main.os.path.exists', return_value=True), \
#             patch('main.open', unittest.mock.mock_open(read_data='[]')), \
#             patch('main.json.load', return_value=[c1_cfg, c2_cfg]):
#            
#            record_a = {'type': 'A_RECORD', 'domain': 'a.com', 'ipv4Address': '9.9.9.9'}
#            
#            # Use side_effect to return different values based on which controller is calling
#            mock_dns.side_effect = lambda inst, *a, **k: [record_a] if inst.host == '1.1.1.1' else []
#            mock_clients.side_effect = lambda inst, *a, **k: []
#            
#            from main import sync_dns
#            sync_dns()
#            
#            # create_dns_record should only be called for host 2.2.2.2
#            self.assertTrue(mock_create.called)
#            # Find the call for host 2.2.2.2
#            create_hosts = [call[0][0].host for call in mock_create.call_args_list]
#            self.assertIn('2.2.2.2', create_hosts)
#            self.assertNotIn('1.1.1.1', create_hosts)

    @patch('requests.get')
    def test_get_client_records_sanitization(self, mock_get):
        self.controller.sync_dhcp_clients = True
        self.controller.domain_suffix = 'home.arpa'
        
        mock_sites = self.mock_site_resolve(mock_get)
        mock_clients = MagicMock()
        mock_clients.status_code = 200
        mock_clients.json.return_value = {
            'data': [
                {'name': 'SonosPortable 09:42', 'ipAddress': '192.168.1.50'},
                {'name': 'proxmox-bs.dorktool.com 08:bf', 'ipAddress': '192.168.1.51'},
                {'name': ' ', 'ipAddress': '192.168.1.52'}  # Empty after split
            ]
        }
        mock_get.side_effect = [mock_sites, mock_clients]

        records = self.controller.get_client_records()
        self.assertEqual(len(records), 2)
        # SonosPortable 09:42 -> SonosPortable -> SonosPortable.home.arpa
        self.assertEqual(records[0]['domain'], 'SonosPortable.home.arpa')
        # proxmox-bs.dorktool.com 08:bf -> proxmox-bs.dorktool.com -> proxmox-bs.dorktool.com (no double suffix)
        self.assertEqual(records[1]['domain'], 'proxmox-bs.dorktool.com')

    @patch('requests.get')
    def test_get_dns_records_filtering(self, mock_get):
        self.controller.allowed_record_types = ['A_RECORD']
        
        mock_sites = self.mock_site_resolve(mock_get)
        mock_dns = MagicMock()
        mock_dns.status_code = 200
        mock_dns.json.return_value = {
            'data': [
                {'type': 'A_RECORD', 'domain': 'a.com', 'ipv4Address': '1.1.1.1'},
                {'type': 'TXT_RECORD', 'domain': 't.com', 'value': 'secret'}
            ]
        }
        mock_get.side_effect = [mock_sites, mock_dns]

        records = self.controller.get_dns_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['type'], 'A_RECORD')

if __name__ == '__main__':
    unittest.main()
