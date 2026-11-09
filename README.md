# QR Attendance

A QR-code attendance system for classrooms: the **Mac generates its own Wi-Fi
network**, phones or tablets join it, open the **scanner page**, scan student
QR codes, and every scan is recorded against the class the admin is currently
tracking. The **admin dashboard** shows attendance coming in live, lets you
switch which class is being tracked, and gives you per-class CSV downloads.
No router or internet connection is needed — the whole system runs on the Mac.

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

- **Conda** (Miniforge or Miniconda). If you don't have it:
  ```bash
  brew install --cask miniforge
  ```
  (or download Miniconda from <https://docs.conda.io>) then restart your
  terminal so `conda` is on your PATH.
- OpenSSL — macOS ships LibreSSL, which works for all commands below

### 2. Set up the project

The repo ships an `environment.yml`; conda builds the environment from it:

```bash
cd /path/to/qr_scanner
conda env create -f environment.yml        # first time only
conda activate qr-attendance                # every new terminal session
```

If you later change `environment.yml`, update the environment with:

```bash
conda env update -f environment.yml --prune
```

### 3. Create the classroom network (Mac hotspot)

The Mac generates its own Wi-Fi network and the scanning devices join it
directly — no router, no campus Wi-Fi, and the Mac's IP never changes.

1. System Settings → **Sharing** → **Internet Sharing**:
   - **Share your connection from**: pick whatever currently gives the Mac
     internet (Ethernet, or Wi-Fi if the Mac is on Wi-Fi via a dongle)
   - **To computers using**: check **Wi-Fi**, then click the ⓘ to set the
     network name and password (use a name like `ATTENDANCE` and a strong
     password — this network is open to anyone in radio range)
2. Turn Internet Sharing **on** (macOS asks to confirm; it needs no reboot)
3. Verify the Mac's address on the new network:

   ```bash
   ipconfig getifaddr bridge100
   ```

   This prints the Mac's IP on the hotspot — it is **`192.168.2.1`** on
   virtually every Mac (Internet Sharing always hands the gateway that
   address). Devices that join get `192.168.2.x` from the Mac.

> If your Mac shows a different address, use that value everywhere below
> instead of `192.168.2.1`.

Joining devices: phones scan for Wi-Fi as usual and pick your network —
once they're on it, they can reach the Mac at `https://192.168.2.1:8443`.

> No internet on the Mac (offline classroom)? Internet Sharing still works
> without an uplink on recent macOS versions — leave "share from" set to any
> interface and turn it on; the Mac will still run the hotspot and the
> attendance server needs no internet at all.

### 4. Generate TLS certificates

Camera access on phones requires **HTTPS**, so the server refuses to start
without certificates. You'll create a small Certificate Authority (CA), then a
server certificate signed by it that includes your Mac's hotspot IP.

```bash
mkdir -p certs && cd certs

# 1) Create a local CA
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 \
    -out ca.crt -subj "/CN=LocalDevCA"

# 2) Create the server key and CSR
#    192.168.2.1 = the Mac's fixed address on the hotspot it generates
#    (use whatever `ipconfig getifaddr bridge100` printed if different)
SERVER_IP=192.168.2.1
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

### 5. Run the server

```bash
conda activate qr-attendance
python run.py
```

You'll see the data locations, URLs, and whether admin auth is on. The server
listens on `https://0.0.0.0:8443` (change with the `QR_PORT` / `QR_HOST`
environment variables) — the hotspot address is `https://192.168.2.1:8443`.

### 6. Open the firewall

System Settings → Network → Firewall → Options → allow **Python** incoming
connections (or temporarily disable the firewall while testing). If macOS
prompts on first run, choose *Allow*. Make sure the allow applies on the
hotspot connection too — when devices can't reach the page but the Mac itself
can (`https://192.168.2.1:8443` in Safari on the Mac), the firewall is the
usual culprit.

### 7. Trust the CA on scanning devices

Each phone/tablet needs to trust your CA **before** opening the scanner page:

Devices must first join the hotspot Wi-Fi (step 3), then:

- **iOS**: Safari → `https://192.168.2.1:8443/ca.crt` → allow download →
  Settings → Profile Downloaded → Install → then
  Settings → General → About → Certificate Trust Settings → enable trust
  for *LocalDevCA*.
- **Android**: Chrome → `https://192.168.2.1:8443/ca.crt` → download →
  Settings → Security → Encryption & credentials → Install a certificate →
  CA certificate.

### 8. Use it

1. Open `https://192.168.2.1:8443/admin` on the Mac (or any device).
   On first use, type a class name and click **Create & track**.
2. Scanning devices open `https://192.168.2.1:8443/` — the scanner page shows
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
`~/Library/LaunchAgents/com.qrattendance.server.plist`.

launchd does not run your shell, so `conda activate` is not available — use the
environment's absolute python path instead. Find it with:

```bash
conda env list               # shows e.g. ~/miniforge3/envs/qr-attendance
CONDA_PYTHON="$(conda info --base)/envs/qr-attendance/bin/python"
echo "$CONDA_PYTHON"          # paste this into ProgramArguments below
```

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.qrattendance.server</string>
    <key>ProgramArguments</key>
    <array>
        <!-- conda env python, found with the command above -->
        <string>/Users/YOURUSER/miniforge3/envs/qr-attendance/bin/python</string>
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

Replace `/path/to/qr_scanner` and the python path with the real values, and
prefer running `launchctl unload` before upgrading the code.

## Day-to-day operations

```bash
# start (manual, in a Terminal window / tmux session)
conda activate qr-attendance && python run.py

# stop the manual instance
Ctrl-C     (or kill $(cat scanner.pid))

# remove the environment entirely (e.g. to rebuild from scratch)
conda deactivate && conda env remove -n qr-attendance
```

Troubleshooting:

- **"TLS CERTIFICATES NOT FOUND"** → step 4 above.
- **`CondaEnvException: Environment already exists`** → the env was created
  before; run `conda activate qr-attendance`, or recreate it with
  `conda env remove -n qr-attendance && conda env create -f environment.yml`.
- **`conda: command not found`** → conda isn't initialized in that shell; run
  `source ~/miniforge3/etc/profile.d/conda.sh` (or `conda init` once and
  restart the terminal).
- **Hotspot not visible to phones** → System Settings → Sharing → make sure
  Internet Sharing is actually toggled on (the settings stick, but the toggle
  silently turns off after some macOS updates); check with
  `ipconfig getifaddr bridge100`.
- **Devices connect but page won't load** → the phone is on the hotspot
  (not cellular or another Wi-Fi), and the Mac firewall allows Python
  (step 6). If the Mac can load `https://192.168.2.1:8443` but phones can't,
  it's the firewall.
- **Phones can't open the page** → check the device is on the hotspot, the
  Mac firewall allows Python, and the CA was trusted (step 7).
- **Certificate warning in Safari on the Mac** → also install and trust
  `ca.crt` on the Mac, or visit `https://localhost:8443` and accept the
  exception.
- **Dashboard says "No class is being tracked"** → pick a class on the admin
  dashboard; scanner devices pick this up within seconds.
