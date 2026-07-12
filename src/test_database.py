import os
import sqlite3
import tempfile
import unittest

from database import DatabaseManager

# UniFi derives the built-in "Default" site's UUID deterministically, so two
# independent controllers report the SAME UUID for it. Origin tracking must
# therefore key on (controller_host, site_uuid), not the UUID alone.
SHARED_DEFAULT_UUID = '88f7af54-98f8-306a-a1c7-c9349722b1f6'


class TestOriginTracking(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(os.path.join(self.tmpdir.name, 'test.db'))

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_same_site_uuid_on_two_controllers_keeps_distinct_origins(self):
        self.db.update_controller('10.0.0.1', 'k1')
        self.db.update_controller('10.0.1.1', 'k2')
        self.db.update_site(SHARED_DEFAULT_UUID, '10.0.0.1', 'Default')
        self.db.update_site(SHARED_DEFAULT_UUID, '10.0.1.1', 'Default')

        # Same record seen on both controllers, one record seen on only one
        self.db.upsert_record('A_RECORD', 'both.com', '1.1.1.1', '{}', '10.0.0.1', SHARED_DEFAULT_UUID)
        self.db.upsert_record('A_RECORD', 'both.com', '1.1.1.1', '{}', '10.0.1.1', SHARED_DEFAULT_UUID)
        self.db.upsert_record('A_RECORD', 'only-c1.com', '2.2.2.2', '{}', '10.0.0.1', SHARED_DEFAULT_UUID)

        rows = {r['domain']: r for r in self.db.get_all_records_with_origins()}

        both_origins = rows['both.com']['origin_keys'].split(',')
        self.assertCountEqual(both_origins, [
            '10.0.0.1/' + SHARED_DEFAULT_UUID,
            '10.0.1.1/' + SHARED_DEFAULT_UUID,
        ])

        # The sync loop's skip rule: only-c1.com must NOT look like it
        # originated on controller 2, despite the identical site UUID.
        c1_origins = rows['only-c1.com']['origin_keys'].split(',')
        self.assertIn(DatabaseManager.origin_key('10.0.0.1', SHARED_DEFAULT_UUID), c1_origins)
        self.assertNotIn(DatabaseManager.origin_key('10.0.1.1', SHARED_DEFAULT_UUID), c1_origins)

    def test_sites_table_keeps_one_row_per_controller(self):
        self.db.update_site(SHARED_DEFAULT_UUID, '10.0.0.1', 'Default')
        self.db.update_site(SHARED_DEFAULT_UUID, '10.0.1.1', 'Default')

        conn = self.db._get_connection()
        hosts = [r['controller_host'] for r in
                 conn.execute("SELECT controller_host FROM sites WHERE uuid = ?", (SHARED_DEFAULT_UUID,))]
        self.assertCountEqual(hosts, ['10.0.0.1', '10.0.1.1'])

    def test_upsert_is_idempotent_per_origin(self):
        self.db.upsert_record('A_RECORD', 'a.com', '1.1.1.1', '{}', '10.0.0.1', SHARED_DEFAULT_UUID)
        self.db.upsert_record('A_RECORD', 'a.com', '1.1.1.1', '{}', '10.0.0.1', SHARED_DEFAULT_UUID)

        rows = self.db.get_all_records_with_origins()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['origin_keys'], '10.0.0.1/' + SHARED_DEFAULT_UUID)


class TestLegacySchemaMigration(unittest.TestCase):
    def test_pre_controller_host_tables_are_dropped_and_recreated(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        db_path = os.path.join(tmpdir.name, 'legacy.db')

        # Build a legacy (user_version 0) database keyed by site UUID alone
        conn = sqlite3.connect(db_path)
        with conn:
            conn.execute("CREATE TABLE sites (uuid TEXT PRIMARY KEY, controller_host TEXT, name TEXT, last_synced DATETIME)")
            conn.execute("CREATE TABLE record_origins (record_id TEXT, site_uuid TEXT, first_seen DATETIME, PRIMARY KEY (record_id, site_uuid))")
            conn.execute("CREATE TABLE sync_events (id INTEGER PRIMARY KEY AUTOINCREMENT, record_id TEXT, site_uuid TEXT, status TEXT, timestamp DATETIME)")
            conn.execute("INSERT INTO record_origins (record_id, site_uuid) VALUES ('r1', 'u1')")
        conn.close()

        db = DatabaseManager(db_path)
        self.addCleanup(db.close)

        # New composite-key writes must succeed against the migrated schema
        db.update_site(SHARED_DEFAULT_UUID, '10.0.0.1', 'Default')
        db.upsert_record('A_RECORD', 'a.com', '1.1.1.1', '{}', '10.0.0.1', SHARED_DEFAULT_UUID)
        rows = db.get_all_records_with_origins()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['origin_keys'], '10.0.0.1/' + SHARED_DEFAULT_UUID)

        # Migration runs once: reopening must not drop data again
        db.close()
        db2 = DatabaseManager(db_path)
        self.addCleanup(db2.close)
        self.assertEqual(len(db2.get_all_records_with_origins()), 1)


if __name__ == '__main__':
    unittest.main()
