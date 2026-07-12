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
from database import DatabaseManager

# Every standalone controller reports this same deterministic UUID for its
# built-in "Default" site — the regression this suite guards against.
SHARED_DEFAULT_UUID = '88f7af54-98f8-306a-a1c7-c9349722b1f6'


def fake_get_all_sites(self):
    return [{'id': SHARED_DEFAULT_UUID, 'name': 'Default'}]


def fake_get_client_records(self):
    return []


class SyncTestCase(unittest.TestCase):
    """Runs sync_dns() against a fresh database with mocked controllers."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(os.path.join(self.tmpdir.name, 'test.db'))
        self._orig_db = main.db
        main.db = self.db

    def tearDown(self):
        main.db = self._orig_db
        self.db.close()
        self.tmpdir.cleanup()

    def run_sync(self, cfg, records_by_host):
        """Run one sync_dns() cycle; returns [(host, domain)] creates."""
        created = []

        def fake_get_dns_records(ctrl):
            return [dict(r) for r in records_by_host.get(ctrl.host, [])]

        def fake_create(ctrl, record_data):
            created.append((ctrl.host, record_data['domain']))
            return True

        with patch('main.os.path.exists', return_value=True), \
             patch('builtins.open', mock_open(read_data=json.dumps(cfg))), \
             patch.object(main.UnifiController, 'get_all_sites', fake_get_all_sites), \
             patch.object(main.UnifiController, 'get_dns_records', fake_get_dns_records), \
             patch.object(main.UnifiController, 'get_client_records', fake_get_client_records), \
             patch.object(main.UnifiController, 'create_dns_record', fake_create):
            sync_dns()
        return created


class TestSyncWithSharedSiteUuid(SyncTestCase):
    def test_record_syncs_to_other_controller_despite_shared_uuid(self):
        record_a = {'type': 'A_RECORD', 'domain': 'a.com', 'ipv4Address': '9.9.9.9'}
        cfg = [
            {'host': '10.0.0.1', 'api_key': 'k1'},
            {'host': '10.0.1.1', 'api_key': 'k2'},
        ]
        created = self.run_sync(cfg, {'10.0.0.1': [record_a]})

        # The record originated on controller 1, so it must be created on
        # controller 2 — even though both sites share the same UUID.
        self.assertIn(('10.0.1.1', 'a.com'), created)
        self.assertNotIn(('10.0.0.1', 'a.com'), created)


class TestAuthoritativeSubnets(SyncTestCase):
    CFG = [
        {'host': '10.250.0.1', 'api_key': 'k1', 'authoritative_subnets': ['10.250.0.0/16']},
        {'host': '10.254.0.1', 'api_key': 'k2', 'authoritative_subnets': ['10.254.0.0/16']},
    ]

    def test_stale_record_for_foreign_subnet_is_not_replicated(self):
        # 10.254.0.1 holds a legacy record pointing INTO 10.250.0.1's subnet;
        # 10.250.0.1 (the authority for that range) doesn't serve it, so it
        # must not be replicated anywhere.
        stale = {'type': 'A_RECORD', 'domain': 'stale.example.com', 'ipv4Address': '10.250.6.30'}
        created = self.run_sync(self.CFG, {'10.254.0.1': [stale]})

        self.assertEqual([c for c in created if c[1] == 'stale.example.com'], [])

    def test_record_from_its_authority_still_replicates(self):
        # Same target subnet, but originating from the authoritative
        # controller — this is the normal sync path and must still work.
        legit = {'type': 'A_RECORD', 'domain': 'legit.example.com', 'ipv4Address': '10.250.6.30'}
        created = self.run_sync(self.CFG, {'10.250.0.1': [legit]})

        self.assertIn(('10.254.0.1', 'legit.example.com'), created)

    def test_record_outside_declared_subnets_replicates_freely(self):
        # Targets in no one's declared range (e.g. an old third network) are
        # not subject to the authority rule.
        other = {'type': 'A_RECORD', 'domain': 'other.example.com', 'ipv4Address': '10.246.0.139'}
        created = self.run_sync(self.CFG, {'10.254.0.1': [other]})

        self.assertIn(('10.250.0.1', 'other.example.com'), created)

    def test_cname_records_are_not_subject_to_authority_rule(self):
        cname = {'type': 'CNAME_RECORD', 'domain': 'alias.example.com', 'targetDomain': 'traefik.example.com'}
        created = self.run_sync(self.CFG, {'10.254.0.1': [cname]})

        self.assertIn(('10.250.0.1', 'alias.example.com'), created)


if __name__ == '__main__':
    unittest.main()
