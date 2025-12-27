from flask import Flask, render_template_string
import sqlite3
import os

app = Flask(__name__)
DB_PATH = os.getenv('DB_PATH', '/data/dns_sync.db')

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>UniFi DNS Sync - Status</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; max-width: 1200px; margin: 0 auto; padding: 20px; background-color: #f4f7f6; }
        h1 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }
        h2 { color: #2980b9; margin-top: 30px; }
        .table-container { background: white; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); overflow-x: auto; margin-bottom: 20px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px 15px; text-align: left; border-bottom: 1px solid #eee; }
        th { background-color: #3498db; color: white; font-weight: bold; }
        tr:hover { background-color: #f1f1f1; }
        .status-created { color: #27ae60; font-weight: bold; }
        .status-failed { color: #c0392b; font-weight: bold; }
        .empty { padding: 20px; text-align: center; color: #7f8c8d; font-style: italic; }
    </style>
</head>
<body>
    <h1>UniFi DNS Sync Dashboard</h1>
    
    <h2>Controllers</h2>
    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th>Host</th>
                    <th>Last Contact</th>
                </tr>
            </thead>
            <tbody>
                {% for controller in data.controllers %}
                <tr>
                    <td>{{ controller.host }}</td>
                    <td>{{ controller.last_contact }}</td>
                </tr>
                {% else %}
                <tr><td colspan="2" class="empty">No controllers registered</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <h2>Sites</h2>
    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th>UUID</th>
                    <th>Controller</th>
                    <th>Name</th>
                    <th>Last Synced</th>
                </tr>
            </thead>
            <tbody>
                {% for site in data.sites %}
                <tr>
                    <td>{{ site.uuid }}</td>
                    <td>{{ site.controller_host }}</td>
                    <td>{{ site.name }}</td>
                    <td>{{ site.last_synced }}</td>
                </tr>
                {% else %}
                <tr><td colspan="4" class="empty">No sites registered</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <h2>DNS Records (Consolidated)</h2>
    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th>Type</th>
                    <th>Domain</th>
                    <th>Target</th>
                    <th>Origins</th>
                </tr>
            </thead>
            <tbody>
                {% for record in data.records %}
                <tr>
                    <td>{{ record.type }}</td>
                    <td>{{ record.domain }}</td>
                    <td>{{ record.target }}</td>
                    <td>{{ record.origin_site_uuids }}</td>
                </tr>
                {% else %}
                <tr><td colspan="4" class="empty">No records found</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <h2>Sync Events (Last 50)</h2>
    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Domain</th>
                    <th>Site</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {% for event in data.events %}
                <tr>
                    <td>{{ event.timestamp }}</td>
                    <td>{{ event.domain }}</td>
                    <td>{{ event.site_name }}</td>
                    <td class="status-{{ event.status | lower }}">{{ event.status }}</td>
                </tr>
                {% else %}
                <tr><td colspan="4" class="empty">No sync events logged</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</body>
</html>
"""

def query_db():
    if not os.path.exists(DB_PATH):
        return {
            'controllers': [],
            'sites': [],
            'records': [],
            'events': []
        }
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        controllers = [dict(r) for r in cursor.execute("SELECT host, last_contact FROM controllers").fetchall()]
        sites = [dict(r) for r in cursor.execute("SELECT uuid, controller_host, name, last_synced FROM sites").fetchall()]
        
        # Records with origins
        records = [dict(r) for r in cursor.execute("""
            SELECT r.type, r.domain, r.target, GROUP_CONCAT(o.site_uuid) as origin_site_uuids
            FROM dns_records r
            JOIN record_origins o ON r.id = o.record_id
            GROUP BY r.id
        """).fetchall()]
        
        # Events with joined info
        events = [dict(r) for r in cursor.execute("""
            SELECT e.timestamp, r.domain, s.name as site_name, e.status
            FROM sync_events e
            JOIN dns_records r ON e.record_id = r.id
            JOIN sites s ON e.site_uuid = s.uuid
            ORDER BY e.timestamp DESC
            LIMIT 50
        """).fetchall()]
        
        return {
            'controllers': controllers,
            'sites': sites,
            'records': records,
            'events': events
        }
    finally:
        conn.close()

@app.route('/')
def index():
    data = query_db()
    return render_template_string(HTML_TEMPLATE, data=data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
