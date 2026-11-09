"""Configuration, driven entirely by environment variables."""

from __future__ import annotations

import os
from pathlib import Path

# Project root (the folder that contains run.py, public/, certs/, data/)
BASE_DIR = Path(__file__).resolve().parent.parent


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class Config:
    """App configuration. Every value can be overridden via environment variables."""

    # Paths
    BASE_DIR: Path = BASE_DIR
    PUBLIC_DIR: Path = BASE_DIR / "public"
    PHOTOS_DIR: Path = BASE_DIR / "public" / "photos"
    CERT_DIR: Path = BASE_DIR / "certs"
    DATA_DIR: Path = Path(os.environ.get("QR_DATA_DIR", BASE_DIR / "data"))
    CSV_DIR: Path = DATA_DIR / "csv"

    # Database
    DATABASE_PATH: Path = DATA_DIR / "scans.db"

    # TLS
    CA_CERT: Path = CERT_DIR / "ca.crt"
    SERVER_CERT: Path = CERT_DIR / "server.crt"
    SERVER_KEY: Path = CERT_DIR / "server.key"

    # Server
    HOST: str = os.environ.get("QR_HOST", "0.0.0.0")
    PORT: int = _env_int("QR_PORT", 8443)

    # PID file used by the Termux/macOS start/stop scripts
    PID_FILE: Path = BASE_DIR / "scanner.pid"

    # Admin dashboard password. Leave unset to disable authentication.
    ADMIN_PASSWORD: str | None = os.environ.get("ADMIN_PASSWORD") or None

    # Ignore duplicate scans of the same student within the same class and day.
    DEDUPE_WITHIN_DAY: bool = os.environ.get("QR_DEDUPE", "1") not in ("0", "false", "no")

    MAX_UNAUTH_LOGINS: int = 10

    # Column order used for both the CSVs and the database rows.
    CSV_HEADER: tuple[str, ...] = (
        "timestamp",
        "class",
        "first_name",
        "surname",
        "other_names",
        "student_id",
        "student_year",
        "passport_picture",
    )
