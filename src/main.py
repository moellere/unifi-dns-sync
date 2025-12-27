import os
import json
import time
import logging
import requests
from urllib3.exceptions import InsecureRequestWarning

# Suppress insecure request warnings for self-signed certificates
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
                    raw_name = client.get('name', '')
                    ip = client.get('ipAddress')
                    
                    if raw_name and ip:
                        # 1. Strip everything after a space (e.g. "Device MAC" -> "Device")
                        name = raw_name.split(' ')[0]
                        if not name:
                            continue
                            
                        # 2. Smart domain suffixing:
                        # Only append if it doesn't already have a dot (assume dot = already has a domain)
                        full_name = name
                        if self.domain_suffix:
                            if '.' not in name:
                                full_name = f"{name}.{self.domain_suffix.lstrip('.')}"
                            # else: already appears to have a domain part, don't append
                        
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
    
    # 1. Fetch all records and track origins
    # key: (rtype, domain, val) -> value: { 'record': data, 'origins': set(hosts) }
    record_map = {}
    successful_controllers = []
    
    for controller in controllers:
        host = controller.host
        # Fetch actual DNS records
        dns_records = controller.get_dns_records()
        # Fetch client records
        client_records = controller.get_client_records()
        
        combined = dns_records + client_records
        
        if combined or controller.api_key:
            successful_controllers.append(controller)
            for r in combined:
                val = None
                rtype = r.get('type')
                if rtype == 'A_RECORD': val = r.get('ipv4Address')
                elif rtype == 'AAAA_RECORD': val = r.get('ipv6Address')
                elif rtype == 'CNAME_RECORD': val = r.get('alias')
                elif rtype == 'MX_RECORD': val = f"{r.get('host')}:{r.get('priority')}"
                elif rtype == 'TXT_RECORD': val = r.get('value')
                
                key = (rtype, controller._normalize_domain(r.get('domain')), val)
                if key not in record_map:
                    record_map[key] = {'record': r, 'origins': set()}
                record_map[key]['origins'].add(host)

    if not successful_controllers:
        logger.warning("No controllers could be accessed or all are empty. Skipping sync.")
        return

    logger.info(f"Consolidated list contains {len(record_map)} unique records.")

    # 2. Update each controller
    for controller in successful_controllers:
        host = controller.host
        current_records = controller.get_dns_records()
        
        # Create a map of existing DNS policy records on THIS controller
        current_dns_map = {}
        for r in current_records:
            val = None
            rtype = r.get('type')
            if rtype == 'A_RECORD': val = r.get('ipv4Address')
            elif rtype == 'AAAA_RECORD': val = r.get('ipv6Address')
            elif rtype == 'CNAME_RECORD': val = r.get('alias')
            elif rtype == 'MX_RECORD': val = f"{r.get('host')}:{r.get('priority')}"
            elif rtype == 'TXT_RECORD': val = r.get('value')
            
            key = (rtype, controller._normalize_domain(r.get('domain')), val)
            current_dns_map[key] = r.get('id')
        
        # Determine what to add
        for key, data in record_map.items():
            # RULE: Skip if already exists as a DNS policy on this controller
            if key in current_dns_map:
                continue
                
            # RULE: Skip if this controller is the ORIGIN of this record
            if host in data['origins']:
                logger.debug(f"Skipping record {key[1]} on {host} because it originated from this controller.")
                continue
            
            # Create the record
            controller.create_dns_record(data['record'])

def main():
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
