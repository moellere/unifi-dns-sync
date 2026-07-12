import sqlite3
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path='/data/dns_sync.db'):
        self.db_path = db_path
        # Ensure directory exists
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            
        self.conn = None
        self._initialize_db()

    def _get_connection(self):
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
        return self.conn

    def _initialize_db(self):
        """Create tables if they don't exist."""
        # Sites, origins and events are keyed by (controller_host, site_uuid),
        # never by site UUID alone: UniFi derives the built-in "Default" site's
        # UUID deterministically, so distinct controllers can report the SAME
        # site UUID. Keying on the UUID alone makes records from one controller
        # look like they originated on every controller, and nothing syncs.
        queries = [
            """
            CREATE TABLE IF NOT EXISTS controllers (
                host TEXT PRIMARY KEY,
                api_key TEXT,
                last_contact DATETIME
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sites (
                uuid TEXT,
                controller_host TEXT,
                name TEXT,
                last_synced DATETIME,
                PRIMARY KEY (controller_host, uuid),
                FOREIGN KEY (controller_host) REFERENCES controllers(host)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS dns_records (
                id TEXT PRIMARY KEY,
                type TEXT,
                domain TEXT,
                target TEXT,
                record_raw TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS record_origins (
                record_id TEXT,
                controller_host TEXT,
                site_uuid TEXT,
                first_seen DATETIME,
                PRIMARY KEY (record_id, controller_host, site_uuid),
                FOREIGN KEY (record_id) REFERENCES dns_records(id),
                FOREIGN KEY (controller_host, site_uuid) REFERENCES sites(controller_host, uuid)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sync_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id TEXT,
                controller_host TEXT,
                site_uuid TEXT,
                status TEXT,
                timestamp DATETIME,
                FOREIGN KEY (record_id) REFERENCES dns_records(id),
                FOREIGN KEY (controller_host, site_uuid) REFERENCES sites(controller_host, uuid)
            )
            """
        ]

        conn = self._get_connection()
        try:
            with conn:
                self._migrate_legacy_schema(conn)
                for query in queries:
                    conn.execute(query)
                conn.execute("PRAGMA user_version = 1")
            logger.info(f"Database initialized at {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize database: {str(e)}")
            raise

    def _migrate_legacy_schema(self, conn):
        """Drop tables from the pre-controller_host schema (user_version 0).

        The old schema keyed sites/origins/events by site UUID alone and
        cannot represent two controllers sharing a UUID. Dropped contents are
        rediscovered from the controllers on the next sync cycle; only
        sync-event history is actually lost.
        """
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= 1:
            return
        for table in ('record_origins', 'sync_events', 'sites'):
            existed = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()
            if existed:
                logger.warning(f"Migrating schema: dropping legacy table '{table}' (re-keyed by controller_host + site_uuid)")
                conn.execute(f"DROP TABLE {table}")

    def update_controller(self, host, api_key=None):
        conn = self._get_connection()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO controllers (host, api_key, last_contact) VALUES (?, ?, ?)",
                (host, api_key, datetime.utcnow())
            )

    def update_site(self, uuid, host, name):
        conn = self._get_connection()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO sites (uuid, controller_host, name, last_synced) VALUES (?, ?, ?, ?)",
                (uuid, host, name, datetime.utcnow())
            )

    def upsert_record(self, rtype, domain, target, record_raw, controller_host, site_uuid):
        import hashlib
        # Primary key is a hash of (type, domain, target) to uniqueness
        record_key = f"{rtype}:{domain}:{target}"
        record_id = hashlib.sha256(record_key.encode()).hexdigest()
        
        conn = self._get_connection()
        with conn:
            # Check if record exists
            cursor = conn.execute("SELECT 1 FROM dns_records WHERE id = ?", (record_id,))
            exists = cursor.fetchone()
            
            # Upsert the record itself
            conn.execute(
                "INSERT OR REPLACE INTO dns_records (id, type, domain, target, record_raw) VALUES (?, ?, ?, ?, ?)",
                (record_id, rtype, domain, target, record_raw)
            )
            
            if not exists:
                logger.info(f"New DNS record discovered: {rtype} {domain} -> {target}")
            
            # Check if origin already exists for this controller/site
            cursor = conn.execute(
                "SELECT 1 FROM record_origins WHERE record_id = ? AND controller_host = ? AND site_uuid = ?",
                (record_id, controller_host, site_uuid)
            )
            origin_exists = cursor.fetchone()

            if not origin_exists:
                if exists:
                    logger.info(f"Record {domain} ({rtype}) discovered on new site {site_uuid} ({controller_host})")

                # Link to origin
                conn.execute(
                    "INSERT OR IGNORE INTO record_origins (record_id, controller_host, site_uuid, first_seen) VALUES (?, ?, ?, ?)",
                    (record_id, controller_host, site_uuid, datetime.utcnow())
                )

                # Log a DISCOVERY event
                self.log_sync_event(record_id, controller_host, site_uuid, 'DISCOVERY')

        return record_id

    def log_sync_event(self, record_id, controller_host, site_uuid, status):
        conn = self._get_connection()
        with conn:
            conn.execute(
                "INSERT INTO sync_events (record_id, controller_host, site_uuid, status, timestamp) VALUES (?, ?, ?, ?, ?)",
                (record_id, controller_host, site_uuid, status, datetime.utcnow())
            )

    @staticmethod
    def origin_key(controller_host, site_uuid):
        """Identity of a record's origin: a site on a specific controller."""
        return f"{controller_host}/{site_uuid}"

    def get_all_records_with_origins(self):
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT r.*, GROUP_CONCAT(o.controller_host || '/' || o.site_uuid) as origin_keys
            FROM dns_records r
            JOIN record_origins o ON r.id = o.record_id
            GROUP BY r.id
        """)
        return cursor.fetchall()
    
    def get_controller_by_host(self, host):
        conn = self._get_connection()
        cursor = conn.execute("SELECT * FROM controllers WHERE host = ?", (host,))
        return cursor.fetchone()

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None
