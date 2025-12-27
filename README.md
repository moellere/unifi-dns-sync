# Unifi DNS Sync

A tool to synchronize DNS records across multiple Unifi controllers.

## Features
- Periodically fetches DNS records from configured controllers.
- Consolidates unique records based on (name, record, type).
- Updates all controllers to ensure they have all consolidated records.

## Local Development
1. Install dependencies: `pip install -r requirements.txt`
2. Create a `controllers.json` file.
3. Run the script: `python src/main.py`

## Configuration

The application requires a `controllers.json` file. By default, it looks for it at `/config/controllers.json`, but you can override this with the `CONFIG_PATH` environment variable.

### `controllers.json` Example
```json
[
  {
    "host": "10.0.0.1",
    "api_key": "YOUR_INTEGRATION_API_KEY",
    "site": "default",
    "sync_dhcp_clients": true,
    "domain_suffix": "home.arpa",
    "allowed_record_types": ["A_RECORD", "CNAME_RECORD"],
    "verify_ssl": false
  },
  {
    "host": "unifi.example.com",
    "api_key": "ANOTHER_API_KEY",
    "site": "HomeSite",
    "verify_ssl": true
  }
]
```

### Environment Variables
- `SYNC_INTERVAL_SECONDS`: How often to synchronize (default: `3600`).
- `CONFIG_PATH`: Path to the configuration file (default: `/config/controllers.json`).
- `LOG_LEVEL`: Logging level (default: `INFO`).

### Origin Tracking
The script automatically tracks which controller a record was pulled from (either as a DNS policy or a DHCP client). It will **not** attempt to create or update that record on its source controller, ensuring that each controller remains the primary source of truth for its own local records.

## Build and Publish

### Local Build
To build the image locally:
```bash
docker build -t unifi-dns-sync:latest .
```

### GitHub Actions
This repository includes a GitHub Action to automatically build and push the image to GHCR on every push to `main`.
