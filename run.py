#!/usr/bin/env python3
"""QR attendance server entrypoint.

Usage:
    python run.py

Requires ./certs/server.crt and ./certs/server.key (see README.md for how to
generate them). The app itself lives in the ``app`` package.
"""

from __future__ import annotations

import atexit
import os
import signal
import sys
from contextlib import suppress

from app import create_app, database
from app.config import Config


def _write_pidfile() -> None:
    with suppress(OSError):
        Config.PID_FILE.write_text(str(os.getpid()), encoding="ascii")


def _remove_pidfile() -> None:
    with suppress(OSError):
        Config.PID_FILE.unlink(missing_ok=True)


def _handle_termination(signum: int, _frame: object) -> None:
    _remove_pidfile()
    sys.exit(0)


def _require_certs() -> None:
    if Config.SERVER_CERT.exists() and Config.SERVER_KEY.exists():
        return

    print("=== TLS CERTIFICATES NOT FOUND ===", file=sys.stderr)
    print(f"Place server.crt and server.key in: {Config.CERT_DIR}", file=sys.stderr)
    print("Full generation instructions (including the SAN setup for your Mac's "
          "LAN IP) are in README.md under 'Generate TLS certificates'.", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    _require_certs()

    app = create_app()
    database.init_db()

    # Write PID so external start/stop scripts can manage this process.
    atexit.register(_remove_pidfile)
    signal.signal(signal.SIGTERM, _handle_termination)
    signal.signal(signal.SIGINT, _handle_termination)
    _write_pidfile()

    print(f"Scanning database : {Config.DATABASE_PATH}")
    print(f"CSV archive dir   : {Config.CSV_DIR}")
    print(f"Scanner page      : https://<this-host>:{Config.PORT}/")
    print(f"Admin dashboard   : https://<this-host>:{Config.PORT}/admin")
    if app.config["ADMIN_PASSWORD"]:
        print("Admin auth       : enabled (ADMIN_PASSWORD is set)")
    else:
        print("Admin auth       : DISABLED (set ADMIN_PASSWORD to protect the dashboard)")

    app.run(
        host=Config.HOST,
        port=Config.PORT,
        ssl_context=(str(Config.SERVER_CERT), str(Config.SERVER_KEY)),
        threaded=True,  # required so the live SSE feed can stream alongside requests
    )


if __name__ == "__main__":
    main()
