import json
import os
import tempfile
import unittest
from unittest.mock import patch, mock_open

# main.py opens its database at import time; point it somewhere disposable
# before the import in case this module is loaded first.
_tmpdir = tempfile.TemporaryDirectory()
os.environ.setdefault('DB_PATH', os.path.join(_tmpdir.name, 'sync_test.db'))

import main
from main import sync_dns

# Every standalone controller reports this same deterministic UUID for its
# built-in "Default" site — the regression this test guards against.
SHARED_DEFAULT_UUID = '88f7af54-98f8-306a-a1c7-c9349722b1f6'


class TestSyncWithSharedSiteUuid(unittest.TestCase):
    def test_record_syncs_to_other_controller_despite_shared_uuid(self):
        record_a = {'type': 'A_RECORD', 'domain': 'a.com', 'ipv4Address': '9.9.9.9'}
        cfg = [
            {'host': '10.0.0.1', 'api_key': 'k1'},
            {'host': '10.0.1.1', 'api_key': 'k2'},
        ]
        created = []

        def fake_get_all_sites(self):
            return [{'id': SHARED_DEFAULT_UUID, 'name': 'Default'}]

        def fake_get_dns_records(self):
            return [dict(record_a)] if self.host == '10.0.0.1' else []

        def fake_get_client_records(self):
            return []

        def fake_create(self, record_data):
            created.append((self.host, record_data['domain']))
            return True

        with patch('main.os.path.exists', return_value=True), \
             patch('builtins.open', mock_open(read_data=json.dumps(cfg))), \
             patch.object(main.UnifiController, 'get_all_sites', fake_get_all_sites), \
             patch.object(main.UnifiController, 'get_dns_records', fake_get_dns_records), \
             patch.object(main.UnifiController, 'get_client_records', fake_get_client_records), \
             patch.object(main.UnifiController, 'create_dns_record', fake_create):
            sync_dns()

        # The record originated on controller 1, so it must be created on
        # controller 2 — even though both sites share the same UUID.
        self.assertIn(('10.0.1.1', 'a.com'), created)
        self.assertNotIn(('10.0.0.1', 'a.com'), created)


if __name__ == '__main__':
    unittest.main()
