# Unifi DNS Sync

A tool to synchronize DNS records across multiple Unifi controllers.

# WARNING!

This tool is in active development and is not yet ready for production use. It is provided as-is and should be used with caution. It is DANGEROUS to use this tool in a production environment as it may cause data loss or corruption.  Did I say it was dangerous?  I mean it.  It's going to make changes to your DNS records on your Unifi controllers.  **If you don't know what you're doing, this could be really bad.**  If you DO know what you're doing, and are making assumptions about what may happen if you use this, it could still be bad!

Understand the code, review the TODOs, and **make sure you know what you're doing before using this tool!**

If it makes changes to your DNS records, it will **not** attempt to reverse those changes.  It will only attempt to make changes to ensure that all controllers have the same records.  There is currently no way to recover other than manually recreating DNS entries, or restoring from a backup.  **You DID create a backup before you started using this tool, right?**

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
