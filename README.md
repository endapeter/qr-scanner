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

### 3. Create the classroom network

The scanning devices and the Mac must be on one Wi-Fi network. The attendance
server needs **no internet** — any isolated LAN works. Two options:

**Option A — iPhone Personal Hotspot (recommended; works everywhere)**

1. On the iPhone: Settings → **Personal Hotspot** → *Allow Others to Join*
   → set a strong Wi-Fi password
2. **Join the Mac to the hotspot first**, then verify its address — on this
   setup the Mac is `172.20.10.6`:

   ```bash
   ipconfig getifaddr en3     # → 172.20.10.6 on this Mac (en1 on some Macs)
   ```

   > Don't assume the address — always confirm with this command after
   > joining. The hotspot's DHCP pool (`172.20.10.1`–`.14`) shifts with
   > join order and which clients are already connected.

3. Join every scanning device to the same hotspot
4. Devices reach the Mac at `https://172.20.10.6:8443` (use whatever the
   command above printed)

> The cellular uplink is irrelevant — the hotspot is just an access point
> for the LAN. If the IP ever changes (different join order), regenerate the
> certs with the new IP (step 4) — or use the Mac's `.local` name, which
> follows the IP automatically (see the IP-changed troubleshooting section).

**Option B — Mac generates the network (Internet Sharing)**

Works on many macOS versions, but **on macOS 26/27 the old Internet Sharing
stack has been reworked and often silently fails** (the toggle reports
"on", but no network is ever broadcast — `ifconfig bridge100` shows nothing
and no `InternetSharing` daemon runs). If that's you, use Option A.

If you want to try it anyway:

1. System Settings → **Sharing** → **Internet Sharing**:
   - **Share your connection from**: any interface (the source is
     irrelevant to the server — it never uses the uplink)
   - **To computers using**: **Wi-Fi** → set network name, WPA2 password,
     **channel 11** (2.4 GHz — the 5 GHz default is invisible to many
     devices and is the #1 cause of "enabled but not visible")
2. Toggle **on**, then toggle the Mac's Wi-Fi off and back on (the AP only
   broadcasts reliably after this reset)
3. Verify: `ifconfig bridge100` must exist with `inet 192.168.2.1`
4. Devices reach the Mac at `https://192.168.2.1:8443`

### 4. Generate TLS certificates

Camera access on phones requires **HTTPS**, so the server refuses to start
without certificates. You'll create a small Certificate Authority (CA), then a
server certificate signed by it that names the Mac's address on the classroom
network.

Set two variables first:

```bash
# The Mac's address on the classroom network — from step 3:
#   Option A (iPhone hotspot): SERVER_IP=172.20.10.6   # what ipconfig getifaddr en0 printed
#   Option B (Mac hotspot):    SERVER_IP=192.168.2.1
SERVER_IP=172.20.10.6

# The Mac's mDNS name (survives IP changes; works in Safari on iOS and macOS):
LOCAL_NAME=$(hostname)        # e.g. huangbook.local
```

```bash
mkdir -p certs && cd certs

# 1) Create a local CA
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 \
    -out ca.crt -subj "/CN=LocalDevCA"

# 2) Create the server key and CSR
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr -subj "/CN=${SERVER_IP}"

# 3) Create a SAN config covering the IP and the mDNS name
cat > san.cnf <<EOF
[req]
distinguished_name = req_distinguished_name
[req_distinguished_name]
[ v3_req ]
subjectAltName = @alt_names
[alt_names]
IP.1 = ${SERVER_IP}
DNS.1 = localhost
DNS.2 = ${LOCAL_NAME}
EOF

# (The mDNS name is what saves you when the IP later changes —
#  see "Troubleshooting: the Mac's IP changed" near the end of this README.)

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
environment variables). On devices, use the Mac's address from step 3 —
e.g. `https://172.20.10.6:8443` (iPhone hotspot) or
`https://192.168.2.1:8443` (Mac hotspot). On the Mac itself, the mDNS name
from step 4 also works: `https://huangbook.local:8443`.

### 6. Open the firewall

System Settings → Network → Firewall → Options → allow **Python** incoming
connections (or temporarily disable the firewall while testing). If macOS
prompts on first run, choose *Allow*. When devices can't reach the page but
the Mac itself can (same URL in Safari on the Mac), the firewall is the usual
culprit.

### 7. Trust the CA on scanning devices

Each phone/tablet needs to trust your CA **before** opening the scanner page.
Devices must first join the classroom network (step 3), then browse to
`https://<mac-address-from-step-3>:8443/ca.crt`:

- **iOS**: Safari → allow download →
  Settings → Profile Downloaded → Install → then
  Settings → General → About → Certificate Trust Settings → enable trust
  for *LocalDevCA*.
- **Android**: Chrome → download →
  Settings → Security → Encryption & credentials → Install a certificate →
  CA certificate.

### 8. Use it

1. Open `https://<mac-address>:8443/admin` on the Mac (or any device).
   On first use, type a class name and click **Create & track**.
2. Scanning devices open `https://<mac-address>:8443/` — the scanner page shows
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
- The dashboard's **Daily attendance** section lists each day per class
  (scan count, first/last scan time) with a **Download** button that exports
  just that day's attendance as `<class>_<date>.csv` — generated from the
  database on demand, so past days stay accurate even after edits.
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
- **Mac's Internet Sharing is "on" but no network appears** → on macOS 26/27
  the old Internet Sharing stack has been reworked and often silently fails
  (toggle on, no `bridge100`, no daemon — `launchctl print
  system/com.apple.InternetSharing` says the service doesn't exist). This is
  an OS-level regression, not a config problem: use the iPhone Personal
  Hotspot topology instead (step 3, Option A). On older macOS: reboot and
  re-enable, set channel 11 (2.4 GHz), and toggle the Mac's Wi-Fi off/on
  after enabling.
- **Certificate error on devices but the Mac loads the page fine** → almost
  always the Mac's IP changed since the cert was generated. Full diagnosis:
  see **"Troubleshooting: the Mac's IP changed"** below.
- **Devices connect but page won't load** → the device is on the classroom
  network (not cellular or another Wi-Fi), and the Mac firewall allows
  Python (step 6). If the Mac loads the page but phones can't, it's the
  firewall.
- **Phones can't open the page** → check the device is on the classroom
  network, the Mac firewall allows Python, and the CA was trusted (step 7).
- **Certificate warning in Safari on the Mac** → also install and trust
  `ca.crt` on the Mac, or visit `https://localhost:8443` and accept the
  exception.
- **Dashboard says "No class is being tracked"** → pick a class on the admin
  dashboard; scanner devices pick this up within seconds.

## Troubleshooting: the Mac's IP changed

The most common failure after "it worked yesterday": the Mac's address on
the classroom network is different from the one baked into the TLS
certificate, so phones get a certificate error and the page won't load.
Devices that joined in a different order, a restarted hotspot, or a
different source network can all shift the DHCP assignment.

**What it looks like:** Safari/Chrome on the *device* shows a certificate
warning ("this server's identity cannot be verified") or refuses to connect
— but the Mac itself loads the page fine at the same URL. It is *not* the
usual untrusted-CA warning you saw on first setup: you already trusted the
CA, and it's now complaining about the *name* on the certificate.

**Step 1 — check what IP the Mac has now:**

```bash
ipconfig getifaddr en0        # Wi-Fi (use en1 if your Mac uses that for Wi-Fi)
```

Compare with the `SERVER_IP` you used in step 4. On the iPhone hotspot the
Mac is normally `172.20.10.6`; on a Mac-generated hotspot, `192.168.2.1`.
If it differs (say the hotspot handed out `172.20.10.9`), that's your
answer — the cert is stale.

**Step 2 — confirm the cert is the problem:**

```bash
# On the Mac — what names/IPs is the cert actually valid for?
openssl x509 -in certs/server.crt -noout -text | grep -A2 "Subject Alternative Name"
```

If the IP printed by `ipconfig getifaddr` is **not** in that list, the
certificate is stale. (This command is also the fastest way to verify a
freshly generated cert before handing phones to students.)

**Step 3 — pick a fix:**

1. **Easiest, no tools:** browse to the Mac's **`.local` name** instead of
   the IP — `https://huangbook.local:8443` — on Safari (iOS/macOS). The
   cert already includes the Mac's `.local` name (step 4 puts it in the
   SAN), and mDNS resolves to whatever the current IP is, so it survives
   address changes with no work at all. *Caveat:* Android Chrome often
   can't resolve `.local` names — use this for Apple devices.
2. **Regenerate the cert for the new IP** (step 4, ~1 minute): set
   `SERVER_IP` to today's address, re-run the two openssl commands and the
   sign command, restart `python run.py`. Existing CA-trust on the phones
   stays valid — you're only re-issuing the *server* certificate, not the
   CA — so no phone reconfiguration is needed.
3. **Prevent it instead:** make the Mac join the hotspot **first** every
   time (consistent join order keeps its address stable), or switch the
   whole flow to `.local` URLs on Apple devices.

**Step 4 — if it's NOT the cert**, walk this chain in order:

| Symptom | Likely cause | Check |
|---|---|---|
| Mac itself can't load `https://<ip>:8443` | server not running | `ps aux \| grep run.py`; start it |
| Mac loads via `127.0.0.1` but not its LAN IP | server bound to wrong host | restart with default `QR_HOST` (`0.0.0.0`) |
| Mac loads fine, device times out (no cert warning at all) | firewall or wrong network | device is on the classroom Wi-Fi? firewall allows Python? (step 6) |
| Device gets cert warning but IP matches the cert | the device trusted a *different/old* CA | re-download `https://<ip>:8443/ca.crt` on that device (step 7) |
