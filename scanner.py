from flask import Flask, request, jsonify, send_from_directory
import csv
import os
import base64
from datetime import datetime
import ssl
import sys
import atexit
import signal

# Initialize Flask app
app = Flask(__name__)

# Define the CSV file name
CSV_FILE = "log.csv"

# Certificate paths (expect files in ./certs/)
CERT_DIR = os.path.join(os.getcwd(), "certs")
CA_CERT = os.path.join(CERT_DIR, "ca.crt")
SERVER_CERT = os.path.join(CERT_DIR, "server.crt")
SERVER_KEY = os.path.join(CERT_DIR, "server.key")

# PID file used by Termux start/stop scripts
PID_FILE = "scanner.pid"

# Ensure the CSV file exists, and write headers if it's newly created
def initialize_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode='w', newline='') as file:
            writer = csv.writer(file)
            # Columns: timestamp first_name surname other_names student_id student_year passport_picture
            writer.writerow(["timestamp", "first_name", "surname", "other_names", "student_id", "student_year", "passport_picture"])

# Initialize CSV file on server launch
initialize_csv()

def _write_pidfile():
    try:
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass

def _remove_pidfile():
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception:
        pass

def _handle_exit(signum, frame):
    _remove_pidfile()
    # allow default termination after cleanup
    sys.exit(0)

# register cleanup handlers
atexit.register(_remove_pidfile)
signal.signal(signal.SIGTERM, _handle_exit)
signal.signal(signal.SIGINT, _handle_exit)

# Route to handle incoming JSON data
@app.route('/log', methods=['POST'])
def log_data():
    try:
        # Get JSON data from the request
        data = request.json

        # Log received payload to server console
        print("Received QR JSON:", data)

        if not data:
            return jsonify({"error": "No JSON data received"}), 400

        # Add a timestamp to the data
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Parse the schema keys
        first_name = data.get("first_name", "") or ""
        surname = data.get("surname", "") or ""
        other_names = data.get("other_names", "") or ""
        student_id = data.get("student_id", "") or ""
        student_year = data.get("student_year", "") or ""
        passport_picture = data.get("passport_picture", "") or ""

        # Append data to the CSV file in the same order as the header
        with open(CSV_FILE, mode='a', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([timestamp, first_name, surname, other_names, student_id, student_year, passport_picture])

        # Load photo by passport_picture field
        image_data = None
        if passport_picture:
            photos_dir = os.path.join(os.getcwd(), "public", "photos")
            image_path = os.path.join(photos_dir, passport_picture)
            print("Looking for passport picture:", image_path)
            if os.path.exists(image_path) and os.path.isfile(image_path):
                with open(image_path, 'rb') as img_file:
                    image_data = base64.b64encode(img_file.read()).decode('utf-8')
            else:
                print("Passport picture not found:", image_path)

        return jsonify({"message": "Data logged successfully", "image": image_data}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Route to serve the scanner.html file
@app.route('/')
def serve_scanner():
    return send_from_directory('public', 'scanner.html')

# Serve any file from the public directory at /public/<path:...>
@app.route('/public/<path:filename>', methods=['GET'])
def serve_public_file(filename):
    public_dir = os.path.join(os.getcwd(), 'public')
    file_path = os.path.join(public_dir, filename)
    print("Serving public file:", file_path)
    if not os.path.exists(file_path):
        print("Public file not found:", file_path)
    return send_from_directory(public_dir, filename)

# Add route to serve static photos (serve from project public/photos)
@app.route('/public/photos/<path:filename>', methods=['GET'])
def serve_photo(filename):
    public_photos = os.path.join(os.getcwd(), 'public', 'photos')
    file_path = os.path.join(public_photos, filename)
    print("Request for photo:", file_path)   # Debug log
    if not os.path.exists(file_path):
        print("Photo not found:", file_path)  # Debug log
    return send_from_directory(public_photos, filename)

# New: endpoint to download the CA certificate (so client devices can install it)
@app.route('/ca.crt', methods=['GET'])
def serve_ca_cert():
    """
    If you create a local CA and place ca.crt in ./certs/ this endpoint
    lets client devices download the CA certificate for installation.
    """
    if not os.path.exists(CA_CERT):
        return jsonify({"error": "CA certificate not found on server. Create ./certs/ca.crt and retry."}), 404
    return send_from_directory(CERT_DIR, 'ca.crt', as_attachment=True)

# Run the server with TLS if certs exist
if __name__ == '__main__':
    # Default port for HTTPS here
    PORT = 8443
    HOST = '0.0.0.0'

    # Check certificate presence
    certs_present = os.path.exists(SERVER_CERT) and os.path.exists(SERVER_KEY)
    if not certs_present:
        print("\n=== TLS CERTIFICATES NOT FOUND ===")
        print("To serve HTTPS you must create a CA and a server certificate (signed by that CA) that includes your phone's hotspot IP in the SAN.")
        print("Create a directory named 'certs' in the project root and place ca.crt, server.crt and server.key there.")
        print("\nExample OpenSSL commands (replace 192.168.43.1 with your phone hotspot IP):\n")
        print("  mkdir certs && cd certs")
        print("  # 1) Create a local CA")
        print("  openssl genrsa -out ca.key 4096")
        print("  openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt -subj \"/CN=LocalDevCA\"")
        print("\n  # 2) Create server key & CSR")
        print("  openssl genrsa -out server.key 2048")
        print("  openssl req -new -key server.key -out server.csr -subj \"/CN=192.168.43.1\"")
        print("\n  # 3) Create an OpenSSL config file 'san.cnf' with your phone IP as SAN:")
        print("  Create a file named san.cnf with the following contents (replace the IP with your phone hotspot IP):")
        print("  ----- san.cnf start -----")
        print("[req]")
        print("distinguished_name = req_distinguished_name")
        print("[req_distinguished_name]")
        print("[ v3_req ]")
        print("subjectAltName = @alt_names")
        print("[alt_names]")
        print("IP.1 = 192.168.43.1")
        print("  ----- san.cnf end -----")
        print("  # 4) Sign the CSR with your CA (adds the SAN to the cert):")
        print("  openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 365 -sha256 -extfile san.cnf -extensions v3_req")
        print("\nAfter that, move server.crt and server.key (and ca.crt) into the project ./certs directory.")
        print("You can then use the /ca.crt endpoint to download the CA certificate to client devices for trust installation.")
        print("\nNote: On Android you must install the CA as a trusted certificate (Settings -> Security -> Install from storage).")
        print("On iOS you must install the profile and then explicitly enable trust for the root in Settings -> About -> Certificate Trust Settings.\n")
        print("Because this approach requires trusting your local CA on each client, modern mobile OSes may restrict apps/browsers — test on your target devices.\n")
        print("Server will NOT start until server.crt and server.key are present. Place them in:", CERT_DIR, "\n")
        sys.exit(1)

    # Write PID so external scripts can control this process
    _write_pidfile()

    # Run Flask with SSL context
    ssl_context = (SERVER_CERT, SERVER_KEY)
    print(f"Starting HTTPS Flask server on https://{HOST}:{PORT}")
    print("Make sure clients install the CA certificate from https://<server_ip>:{PORT}/ca.crt")
    app.run(host=HOST, port=PORT, ssl_context=ssl_context)
    # PID file will be removed on exit via atexit / signal handlers