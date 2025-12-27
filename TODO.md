# Project Roadmap & TODO

## Persistence & Improved Sync
- [ ] **SQLite Migration**: Implement a local database to track record states, detect deletions, and provide faster lookups. 
  - *Reference*: [sqlite_migration.md](docs/design/sqlite_migration.md)
- [ ] **Deletion Propagation**: Support removing records from controllers if they are deleted from others or no longer in the consolidated list.

## Web Interface (GUI)
- [ ] **Admin Dashboard**: A premium, modern web interface to manage the application.
  - **Configuration Management**: 
    - Set sync frequency (interval seconds).
    - Toggle DHCP client inclusion.
    - Select allowed record types (A, CNAME, MX, etc.).
  - **Controller Management**: Add/Remove/Edit Unifi controller credentials and sites.
  - **Live Monitoring**: 
    - Display current records being synced.
    - Show sync logs and status history.
    - Visualization of DNS record propagation across controllers.

## Observability & Maintenance
- [ ] **Metrics Export**: Export Prometheus metrics for sync successes/failures and record counts.
- [ ] **Health Checks**: Implement a health check endpoint for Kubernetes liveness/readiness probes.
- [ ] **Dry Run Mode**: Add a configuration option to simulate changes without applying them.
