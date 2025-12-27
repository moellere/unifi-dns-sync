import os
import json
import time
import logging
import requests
import threading
from urllib3.exceptions import InsecureRequestWarning
from database import DatabaseManager
from web import app as web_app

# Suppress insecure request warnings for self-signed certificates
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize database
db = DatabaseManager(os.getenv('DB_PATH', '/data/dns_sync.db'))

class UnifiController:
    def __init__(self, config):
        self.host = config.get('host')
        self.api_key = config.get('api_key')
        self.site_name = config.get('site', 'default')
        self.verify_ssl = config.get('verify_ssl', False)
        self.domain_suffix = config.get('domain_suffix', '').strip()
        self.sync_dhcp_clients = config.get('sync_dhcp_clients', False)
        self.allowed_record_types = config.get('allowed_record_types', ['A_RECORD', 'CNAME_RECORD'])
        self.site_id = None
        # Integration API v1 base URL
        self.base_url = f"https://{self.host}/proxy/network/integration/v1"
        self.headers = {
            'X-API-KEY': self.api_key,
            'Accept': 'application/json'
        }

    def _normalize_domain(self, domain):
        """Normalize domain to lowercase and strip trailing dots."""
        if not domain:
            return ""
        return domain.lower().rstrip('.')

    def _resolve_site_id(self):
        """Find the site UUID that matches self.site_name."""
        if self.site_id:
            return self.site_id

        logger.info(f"Resolving site ID for site name '{self.site_name}' on {self.host}...")
        url = f"{self.base_url}/sites"
        try:
            response = requests.get(url, headers=self.headers, verify=self.verify_ssl, timeout=10)
            if response.status_code == 200:
                sites = response.json().get('data', [])
                for site in sites:
                    name = site.get('name')
                    sid = site.get('id')
                    # Case-insensitive match for name, exact match for ID
                    if (name and name.lower() == self.site_name.lower()) or sid == self.site_name:
                        self.site_id = sid
                        logger.info(f"Resolved site '{self.site_name}' to ID '{self.site_id}'")
                        return self.site_id
                
                logger.error(f"Site '{self.site_name}' not found on {self.host}. Available: {[s.get('name') for s in sites]}")
                return None
            else:
                logger.error(f"Failed to list sites on {self.host}: {response.status_code} {response.text}")
                return None
        except Exception as e:
            logger.error(f"Error listing sites on {self.host}: {str(e)}")
            return None

    def get_all_sites(self):
        """Fetch all sites available on this controller."""
        logger.info(f"Fetching all sites from {self.host}...")
        url = f"{self.base_url}/sites"
        try:
            response = requests.get(url, headers=self.headers, verify=self.verify_ssl, timeout=10)
            if response.status_code == 200:
                sites = response.json().get('data', [])
                logger.info(f"Found {len(sites)} sites on {self.host}")
                return sites
            else:
                logger.error(f"Failed to list sites on {self.host}: {response.status_code} {response.text}")
                return []
        except Exception as e:
            logger.error(f"Error listing sites on {self.host}: {str(e)}")
            return []

    def get_dns_records(self):
        site_id = self._resolve_site_id()
        if not site_id:
            return []

        logger.info(f"Fetching DNS records from {self.host} (Site: {self.site_name})...")
        url = f"{self.base_url}/sites/{site_id}/dns/policies"
        try:
            response = requests.get(url, headers=self.headers, verify=self.verify_ssl, timeout=10)
            if response.status_code == 200:
                data = response.json().get('data', [])
                # Filter by allowed record types and normalize domains
                filtered_data = []
                for r in data:
                    if r.get('type') in self.allowed_record_types:
                        r['domain'] = self._normalize_domain(r.get('domain'))
                        filtered_data.append(r)
                
                logger.info(f"Successfully fetched {len(filtered_data)} DNS policy records from {self.host} (filtered from {len(data)})")
                return filtered_data
            else:
                logger.error(f"Failed to fetch DNS records from {self.host}: {response.status_code} {response.text}")
                return []
        except Exception as e:
            logger.error(f"Error fetching DNS records from {self.host}: {str(e)}")
            return []

    def get_client_records(self):
        """Fetch connected clients and convert them to DNS record format."""
        if not self.sync_dhcp_clients:
            return []

        site_id = self._resolve_site_id()
        if not site_id:
            return []

        logger.info(f"Fetching client records from {self.host} (Site: {self.site_name})...")
        url = f"{self.base_url}/sites/{site_id}/clients"
        try:
            response = requests.get(url, headers=self.headers, verify=self.verify_ssl, timeout=10)
            if response.status_code == 200:
                clients = response.json().get('data', [])
                records = []
                for client in clients:
                    raw_name = client.get('name') or client.get('hostname') or client.get('displayName')
                    ip = client.get('ipAddress')
                    
                    if raw_name and ip:
                        # 1. Sanitize name: replace spaces with hyphens, remove other DNS-unsafe chars
                        import re
                        name = re.sub(r'[^a-zA-Z0-9-]', '-', raw_name).strip('-')
                        if not name:
                            continue
                            
                        # 2. Smart domain suffixing:
                        # Only append if it doesn't already end with the suffix
                        full_name = name
                        if self.domain_suffix:
                            suffix = self.domain_suffix.lstrip('.')
                            if not name.lower().endswith(f".{suffix.lower()}") and name.lower() != suffix.lower():
                                full_name = f"{name}.{suffix}"
                        
                        full_name = self._normalize_domain(full_name)
                        
                        # Convert to A_RECORD format for synchronization
                        records.append({
                            'type': 'A_RECORD',
                            'domain': full_name,
                            'ipv4Address': ip,
                            'enabled': True,
                            'ttlSeconds': 3600
                        })
                
                # Filter client records too if A_RECORD is not allowed (unlikely but consistent)
                filtered_records = [r for r in records if r.get('type') in self.allowed_record_types]
                logger.info(f"Successfully fetched {len(filtered_records)} client records from {self.host}")
                return filtered_records
            else:
                logger.error(f"Failed to fetch client records from {self.host}: {response.status_code} {response.text}")
                return []
        except Exception as e:
            logger.error(f"Error fetching client records from {self.host}: {str(e)}")
            return []

    def create_dns_record(self, record):
        site_id = self._resolve_site_id()
        if not site_id:
            return False

        domain = record.get('domain', 'unknown')
        rtype = record.get('type', 'UNKNOWN')
        val = record.get('ipv4Address') or record.get('alias') or record.get('value') or record.get('host')
        
        logger.info(f"Creating {rtype} record '{domain}' -> '{val}' on {self.host}...")
        url = f"{self.base_url}/sites/{site_id}/dns/policies"
        # Ensure domain is normalized before sending
        record['domain'] = self._normalize_domain(domain)
        # Remove ID and other response-only fields before sending
        payload = {k: v for k, v in record.items() if k not in ['id']}
        try:
            response = requests.post(url, headers=self.headers, json=payload, verify=self.verify_ssl, timeout=10)
            if response.status_code in [200, 201]:
                logger.info(f"Successfully created record on {self.host}")
                return True
            
            # Handle specific 400 errors for overlaps/conflicts
            if response.status_code == 400:
                try:
                    error_data = response.json()
                    error_code = error_data.get('code')
                    error_msg = error_data.get('message')
                    
                    overlap_codes = [
                        'api.dns.policy.validation.overlap-with-local-dns',
                        'api.dns.policy.validation.cname-alias-overlap'
                    ]
                    
                    if error_code in overlap_codes:
                        logger.info(f"Record '{domain}' already exists or conflicts on {self.host} (internal UniFi conflict). Skipping.")
                        return True # Treat as success since the record is effectively present
                    
                    logger.error(f"Failed to create record on {self.host}: 400 {error_code} - {error_msg}")
                except Exception:
                    logger.error(f"Failed to create record on {self.host}: 400 {response.text}")
            else:
                logger.error(f"Failed to create record on {self.host}: {response.status_code} {response.text}")
            return False
        except Exception as e:
            logger.error(f"Error creating record on {self.host}: {str(e)}")
            return False

    def delete_dns_record(self, record_id):
        site_id = self._resolve_site_id()
        if not site_id:
            return False

        logger.info(f"Deleting record {record_id} from {self.host}...")
        url = f"{self.base_url}/sites/{site_id}/dns/policies/{record_id}"
        try:
            response = requests.delete(url, headers=self.headers, verify=self.verify_ssl, timeout=10)
            if response.status_code in [200, 204]:
                logger.info(f"Successfully deleted record from {self.host}")
                return True
            else:
                logger.error(f"Failed to delete record from {self.host}: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error deleting record from {self.host}: {str(e)}")
            return False

def sync_dns():
    config_path = os.getenv('CONFIG_PATH', '/config/controllers.json')
    if not os.path.exists(config_path):
        logger.error(f"Config file not found at {config_path}")
        return

    try:
        with open(config_path, 'r') as f:
            controllers_config = json.load(f)
    except Exception as e:
        logger.error(f"Error reading config file: {str(e)}")
        return

    controllers = [UnifiController(cfg) for cfg in controllers_config]
    
    # 1. Discovery Phase: Fetch and Persist
    for controller in controllers:
        db.update_controller(controller.host, controller.api_key)
        sites = controller.get_all_sites()
        
        for site in sites:
            site_uuid = site.get('id')
            site_name = site.get('name')
            db.update_site(site_uuid, controller.host, site_name)
            
            # Temporarily override site_id on controller to fetch records for THIS site
            orig_site_id = controller.site_id
            orig_site_name = controller.site_name
            controller.site_id = site_uuid
            controller.site_name = site_name
            
            try:
                dns_records = controller.get_dns_records()
                client_records = controller.get_client_records()
                logger.info(f"Importing {len(dns_records)} DNS policies and {len(client_records)} client records from {controller.host} (Site: {site_name})")
                
                for r in (dns_records + client_records):
                    rtype = r.get('type')
                    domain = controller._normalize_domain(r.get('domain'))
                    val = r.get('ipv4Address') or r.get('alias') or r.get('value') or r.get('host')
                    db.upsert_record(rtype, domain, val, json.dumps(r), site_uuid)
            finally:
                controller.site_id = orig_site_id
                controller.site_name = orig_site_name

    # 2. Sync Phase: Replicate from DB
    all_records = db.get_all_records_with_origins()
    logger.info(f"Consolidated list from DB contains {len(all_records)} unique records.")

    for controller in controllers:
        sites = controller.get_all_sites()
        for site in sites:
            site_uuid = site.get('id')
            site_name = site.get('name')
            
            orig_site_id = controller.site_id
            orig_site_name = controller.site_name
            controller.site_id = site_uuid
            controller.site_name = site_name
            
            try:
                current_records = controller.get_dns_records()
                current_dns_map = {}
                for r in current_records:
                    rtype = r.get('type')
                    domain = controller._normalize_domain(r.get('domain'))
                    val = r.get('ipv4Address') or r.get('alias') or r.get('value') or r.get('host')
                    key = (rtype, domain, val)
                    current_dns_map[key] = r.get('id')

                for rec_row in all_records:
                    rtype = rec_row['type']
                    domain = rec_row['domain']
                    target = rec_row['target']
                    origins = rec_row['origin_site_uuids'].split(',')
                    
                    key = (rtype, domain, target)
                    
                    # RULE: Skip if already exists on this site
                    if key in current_dns_map:
                        continue
                        
                    # RULE: Skip if this specific site is an origin for this record
                    if site_uuid in origins:
                        logger.debug(f"Skipping record '{domain}' on site '{site_name}' ({controller.host}) because it originated here.")
                        continue
                    
                    # Create the record
                    record_data = json.loads(rec_row['record_raw'])
                    if controller.create_dns_record(record_data):
                        db.log_sync_event(rec_row['id'], site_uuid, 'CREATED')

            finally:
                controller.site_id = orig_site_id
                controller.site_name = orig_site_name

def main():
    # Start Web UI in a separate thread
    web_port = int(os.getenv('WEB_UI_PORT', '5000'))
    web_thread = threading.Thread(
        target=lambda: web_app.run(host='0.0.0.0', port=web_port, debug=False, use_reloader=False),
        daemon=True
    )
    web_thread.start()
    logger.info(f"Web UI started on port {web_port}")

    sync_interval = int(os.getenv('SYNC_INTERVAL_SECONDS', '3600'))
    while True:
        try:
            sync_dns()
        except Exception as e:
            logger.error(f"Unexpected error in sync loop: {str(e)}")
        
        logger.info(f"Sleeping for {sync_interval} seconds...")
        time.sleep(sync_interval)

if __name__ == "__main__":
    main()
