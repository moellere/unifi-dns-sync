<<<<<<< HEAD
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

## Build and Publish

### Local Build
To build the image locally:
```bash
docker build -t unifi-dns-sync:latest .
```

### GitHub Actions (Recommended)
This repository includes a GitHub Action to automatically build and push the image to [GitHub Container Registry (GHCR)](https://ghcr.io) on every push to the `main` branch or when a version tag (e.g., `v1.0.0`) is created.

1. Push your code to GitHub.
2. The image will be available at `ghcr.io/YOUR_USERNAME/unifi-dns-sync:latest`.

> [!TIP]
> Make sure to update the `image.repository` in `charts/unifi-dns-sync/values.yaml` to match your own GitHub username.
=======
# unifi-dns-sync
Python-based utility/container to synchronize DNS records across Unifi controllers
>>>>>>> unifi-dns-sync/main
