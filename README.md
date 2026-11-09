# QR Attendance

A QR-code attendance system for classrooms: phones or tablets open the **scanner
page**, scan student QR codes, and every scan is recorded against the class the
admin is currently tracking. The **admin dashboard** shows attendance coming in
live, lets you switch which class is being tracked, and gives you per-class CSV
downloads.

## What's in this repo

| Path | Purpose |
|---|---|
| `run.py` | Server entrypoint (HTTPS on port 8443 by default) |
| `app/` | Flask application package (routes, database, live events) |
| `public/scanner.html` | The scanner page devices open |
| `public/admin.html` | The admin dashboard |
| `public/photos/` | Passport photos, referenced by filename in the QR codes |
| `certs/` | TLS certificates — **not committed**; you generate them |
| `data/` | Created at runtime: the scanning database + CSV archive |
| `data/scans.db` | SQLite — the source of truth for every scan ever recorded |
| `data/csv/` | One auto-maintained CSV per class (e.g. `data/csv/cs_101.csv`) |

## Quick start (macOS)

### 1. Requirements

- macOS with Python 3.11+ (check: `python3 --version`; install via
  `brew install python` if missing)
- OpenSSL — macOS ships LibreSSL, which works for all commands below

### 2. Set up the project

```bash
cd /path/to/qr_scanner
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Generate TLS certificates

Camera access on phones requires **HTTPS**, so the server refuses to start
without certificates. You'll create a small Certificate Authority (CA), then a
server certificate signed by it that includes your Mac's LAN IP.

> Find your Mac's IP on the classroom network: `ipconfig getifaddr en0`
> (use `en1` if you're on Wi-Fi and `en0` is Ethernet).

```bash
mkdir -p certs && cd certs

# 1) Create a local CA
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 \
    -out ca.crt -subj "/CN=LocalDevCA"

# 2) Create the server key and CSR (use YOUR Mac's IP as the CN)
SERVER_IP=192.168.1.42   # <-- replace with your ipconfig getifaddr result
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr -subj "/CN=${SERVER_IP}"

# 3) Create a SAN config so browsers trust the cert for that IP
cat > san.cnf <<EOF
[req]
distinguished_name = req_distinguished_name
[req_distinguished_name]
[ v3_req ]
subjectAltName = @alt_names
[alt_names]
IP.1 = ${SERVER_IP}
DNS.1 = localhost
EOF

# 4) Sign the server certificate with your CA
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out server.crt -days 365 -sha256 -extfile san.cnf -extensions v3_req

cd ..
```

You should now have `certs/ca.crt`, `certs/server.crt` and `certs/server.key`.

### 4. Run the server

```bash
source .venv/bin/activate
python run.py
```

You'll see the data locations, URLs, and whether admin auth is on. The server
listens on `https://0.0.0.0:8443` (change with the `QR_PORT` / `QR_HOST`
environment variables).

### 5. Open the firewall

System Settings → Network → Firewall → Options → allow **Python** incoming
connections (or temporarily disable the firewall while testing). If macOS
prompts on first run, choose *Allow*.

### 6. Trust the CA on scanning devices

Each phone/tablet needs to trust your CA **before** opening the scanner page:

- **iOS**: Safari → `https://<mac-ip>:8443/ca.crt` → allow download →
  Settings → Profile Downloaded → Install → then
  Settings → General → About → Certificate Trust Settings → enable trust
  for *LocalDevCA*.
- **Android**: Chrome → `https://<mac-ip>:8443/ca.crt` → download →
  Settings → Security → Encryption & credentials → Install a certificate →
  CA certificate.

### 7. Use it

1. Open `https://<mac-ip>:8443/admin` on the Mac (or any device).
   On first use, type a class name and click **Create & track**.
2. Scanning devices open `https://<mac-ip>:8443/` — the scanner page shows
   which class it is currently tracking for.
3. Scan student QR codes. Accepted scans appear on the dashboard instantly;
   repeat scans by the same student that day are flagged as duplicates.
4. Download a class's CSV from the **Scan archive** section — it also shows
   the directory (`data/csv/`) where the files live on the server.

## The scanning database & CSVs

- Every accepted scan is written to the SQLite database `data/scans.db`
  (the durable record of everything ever scanned).
- Each class also gets a live-updated CSV at `data/csv/<class>.csv`, ready to
  download or grab straight from Finder. Columns:
  `timestamp, class, first_name, surname, other_names, student_id, student_year, passport_picture`
- The admin dashboard's **Scan archive** section lists every CSV with its row
  count, size and last-modified time, and displays the absolute directory
  path on the server.
- Back up or copy the whole `data/` directory to move history between machines.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `QR_PORT` | `8443` | HTTPS port |
| `QR_HOST` | `0.0.0.0` | Bind address |
| `QR_DATA_DIR` | `./data` | Where the database + CSVs live |
| `QR_DEDUPE` | `1` | `0` disables duplicate-scan rejection |
| `ADMIN_PASSWORD` | *(unset)* | If set, the dashboard + admin APIs require login |

Example with a password:

```bash
ADMIN_PASSWORD='super-secret' python run.py
```

## Keeping it running (launchd)

To have the server start automatically at login, create
`~/Library/LaunchAgents/com.qrattendance.server.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.qrattendance.server</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/qr_scanner/.venv/bin/python</string>
        <string>run.py</string>
    </array>
    <key>WorkingDirectory</key><string>/path/to/qr_scanner</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>/tmp/qr-scanner.out</string>
    <key>StandardErrorPath</key><string>/tmp/qr-scanner.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <!-- set a password for the dashboard before going live -->
        <key>ADMIN_PASSWORD</key><string>change-me</string>
    </dict>
</dict>
</plist>
```

Then load it:

```bash
launchctl load ~/Library/LaunchAgents/com.qrattendance.server.plist
# to stop it later:
launchctl unload ~/Library/LaunchAgents/com.qrattendance.server.plist
```

Replace `/path/to/qr_scanner` with the real project path, and prefer running
`launchctl unload` before upgrading the code.

## Day-to-day operations

```bash
# start (manual, in a Terminal window / tmux session)
source .venv/bin/activate && python run.py

# stop the manual instance
Ctrl-C     (or kill $(cat scanner.pid))
```

Troubleshooting:

- **"TLS CERTIFICATES NOT FOUND"** → step 3 above.
- **Phones can't open the page** → check both devices are on the same Wi-Fi /
  hotspot, the Mac firewall allows Python, and the CA was trusted (step 6).
- **Certificate warning in Safari on the Mac** → also install and trust
  `ca.crt` on the Mac, or visit `https://localhost:8443` and accept the
  exception.
- **Dashboard says "No class is being tracked"** → pick a class on the admin
  dashboard; scanner devices pick this up within seconds.
