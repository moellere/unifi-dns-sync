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

Origins are keyed by **controller + site**, not by site UUID alone. This matters because UniFi derives the built-in "Default" site's UUID deterministically — every standalone controller reports the *same* UUID for it. Keying on the UUID alone would make every record look like it originated everywhere, silently disabling sync between controllers that both use the Default site.

## Deploying on Kubernetes (Helm)

A Helm chart lives in `charts/unifi-dns-sync`. First-time setup:

### 1. Create a UniFi Integration API key

On each controller: **Settings → Control Plane → Integrations → Create API Key**.
The tool talks to the Integration API (`/proxy/network/integration/v1`), so a
regular admin login/password will not work — it must be an API key.

### 2. Provide the controller config

The app reads a single `controllers.json` file (see the example above). The
chart mounts it from a Kubernetes Secret, and there are two ways to supply it:

**Option A — `existingSecret` (recommended):** create the Secret yourself and
tell the chart to use it. Your API keys never touch Helm values or your git
history.

```bash
# controllers.json is the file from the example above
kubectl create namespace unifi-dns-sync
kubectl create secret generic unifi-dns-sync-controllers \
  --namespace unifi-dns-sync \
  --from-file=controllers.json=./controllers.json
```

```yaml
# values.yaml
existingSecret: unifi-dns-sync-controllers
```

The Secret must contain a key named exactly `controllers.json`. If you run a
GitOps workflow (ArgoCD/Flux), encrypt it with
[sealed-secrets](https://github.com/bitnami-labs/sealed-secrets), SOPS, or
external-secrets instead of `kubectl create secret`, and commit the encrypted
form.

**Option B — inline `controllers` values (quick tests only):** set the
`controllers` list directly in values and the chart renders the Secret for
you. Anything you put here ends up in plaintext in your values file and Helm
release history — don't commit real API keys this way.

```yaml
# values.yaml
controllers:
  - host: "10.0.0.1"
    api_key: "YOUR_INTEGRATION_API_KEY"
    site: "default"
    verify_ssl: false
```

### 3. Install

```bash
helm install unifi-dns-sync ./charts/unifi-dns-sync \
  --namespace unifi-dns-sync --create-namespace \
  -f values.yaml
```

### 4. Verify

```bash
kubectl logs -n unifi-dns-sync deploy/unifi-dns-sync
```

A healthy first cycle logs `Importing N DNS policies and M client records
from <host>` for each controller, then `Consolidated list from DB contains N
unique records.` If it reports `0 unique records` and no import lines, your
`controllers.json` is empty or the Secret isn't mounted correctly.

The web UI dashboard is exposed on port 5000 (Service port 80) for inspecting
what was discovered and synced.

### Things to know

- **A single controller with a single site syncs nothing.** Origin tracking
  (see above) means records are never written back to the site they came
  from. The tool becomes useful with two or more controllers/sites.
- **Persistence is off by default** (`persistence.enabled: false`), so the
  record database is rebuilt from the controllers on every pod restart. Enable
  it if you want sync history to survive restarts.
- Re-read the WARNING at the top of this file before pointing this at a
  controller you care about.

## Build and Publish

### Local Build
To build the image locally:
```bash
docker build -t unifi-dns-sync:latest .
```

### GitHub Actions
This repository includes a GitHub Action to automatically build and push the image to GHCR on every push to `main`.
