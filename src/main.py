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
        self.port = config.get('port', 443)
        self.username = config.get('username')
        self.password = config.get('password')
        self.site = config.get('site', 'default')
        self.verify_ssl = config.get('verify_ssl', False)
        self.base_url = f"https://{self.host}:{self.port}"
        self.session = requests.Session()

    def login(self):
        logger.info(f"Logging into {self.host}...")
        # Try UniFi OS login first
        login_url = f"{self.base_url}/api/auth/login"
        payload = {
            'username': self.username,
            'password': self.password
        }
        try:
            response = self.session.post(login_url, json=payload, verify=self.verify_ssl, timeout=10)
            if response.status_code == 200:
                logger.info(f"Successfully logged into {self.host} (UniFi OS)")
                return True
            
            # Fallback to legacy login
            login_url = f"{self.base_url}/api/login"
            response = self.session.post(login_url, json=payload, verify=self.verify_ssl, timeout=10)
            if response.status_code == 200:
                logger.info(f"Successfully logged into {self.host} (Legacy)")
                return True
            
            logger.error(f"Failed to login to {self.host}: {response.status_code} {response.text}")
            return False
        except Exception as e:
            logger.error(f"Error logging into {self.host}: {str(e)}")
            return False

    def get_dns_records(self):
        logger.info(f"Fetching DNS records from {self.host}...")
        url = f"{self.base_url}/proxy/network/api/s/{self.site}/rest/dnsexternal"
        try:
            response = self.session.get(url, verify=self.verify_ssl, timeout=10)
            # If 404, try without /proxy/network
            if response.status_code == 404:
                url = f"{self.base_url}/api/s/{self.site}/rest/dnsexternal"
                response = self.session.get(url, verify=self.verify_ssl, timeout=10)
            
            if response.status_code == 200:
                data = response.json().get('data', [])
                logger.info(f"Found {len(data)} records on {self.host}")
                return data
            else:
                logger.error(f"Failed to fetch records from {self.host}: {response.status_code} {response.text}")
                return []
        except Exception as e:
            logger.error(f"Error fetching records from {self.host}: {str(e)}")
            return []

    def create_dns_record(self, record):
        logger.info(f"Creating record {record['name']} on {self.host}...")
        url = f"{self.base_url}/proxy/network/api/s/{self.site}/rest/dnsexternal"
        # Remove internal fields before sending
        payload = {k: v for k, v in record.items() if k not in ['_id', 'site_id']}
        try:
            response = self.session.post(url, json=payload, verify=self.verify_ssl, timeout=10)
            if response.status_code == 404:
                url = f"{self.base_url}/api/s/{self.site}/rest/dnsexternal"
                response = self.session.post(url, json=payload, verify=self.verify_ssl, timeout=10)
            
            if response.status_code in [200, 201]:
                logger.info(f"Successfully created record on {self.host}")
                return True
            else:
                logger.error(f"Failed to create record on {self.host}: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error creating record on {self.host}: {str(e)}")
            return False

    def delete_dns_record(self, record_id):
        logger.info(f"Deleting record {record_id} from {self.host}...")
        url = f"{self.base_url}/proxy/network/api/s/{self.site}/rest/dnsexternal/{record_id}"
        try:
            response = self.session.delete(url, verify=self.verify_ssl, timeout=10)
            if response.status_code == 404:
                url = f"{self.base_url}/api/s/{self.site}/rest/dnsexternal/{record_id}"
                response = self.session.delete(url, verify=self.verify_ssl, timeout=10)
            
            if response.status_code == 200:
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

    with open(config_path, 'r') as f:
        controllers_config = json.load(f)

    controllers = [UnifiController(cfg) for cfg in controllers_config]
    
    # 1. Login and Fetch all records
    all_records = []
    successful_controllers = []
    
    for controller in controllers:
        if controller.login():
            records = controller.get_dns_records()
            successful_controllers.append(controller)
            # Add records to the master list, keeping track of which are already there
            for r in records:
                all_records.append(r)

    if not successful_controllers:
        logger.warning("No controllers could be accessed. Skipping sync.")
        return

    # 2. Consolidate records
    unique_records = {}
    for r in all_records:
        key = (r['name'], r['record'], r['type'])
        if key not in unique_records:
            unique_records[key] = r

    consolidated_list = list(unique_records.values())
    logger.info(f"Consolidated list contains {len(consolidated_list)} unique records.")

    # 3. Update each controller
    for controller in successful_controllers:
        current_records = controller.get_dns_records()
        current_map = {(r['name'], r['record'], r['type']): r['_id'] for r in current_records}
        
        # Determine what to add
        for record in consolidated_list:
            key = (record['name'], record['record'], record['type'])
            if key not in current_map:
                controller.create_dns_record(record)

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
