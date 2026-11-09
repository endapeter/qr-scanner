"""Static file serving: scanner page, assets, passport photos and the CA cert.

Only files the scanning devices need are served here. The admin dashboard page
is NOT one of them — it is served exclusively at /admin by the admin blueprint.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, send_from_directory
from werkzeug.exceptions import NotFound

from ..config import Config

bp = Blueprint("static_files", __name__)

# Files that must never be reachable through the public /public/ route.
# Everything else in public/ (scanner page, JS, photos) is device-facing.
_ADMIN_ONLY_FILES = frozenset({"admin.html"})


@bp.get("/")
def scanner_page():
    return send_from_directory(Config.PUBLIC_DIR, "scanner.html")


@bp.get("/public/<path:filename>")
def public_file(filename: str):
    if filename in _ADMIN_ONLY_FILES:
        raise NotFound()  # admin page is only served at /admin, never raw
    return send_from_directory(Config.PUBLIC_DIR, filename)


@bp.get("/ca.crt")
def ca_cert():
    """Download endpoint so client devices can install the CA certificate."""
    if not Config.CA_CERT.exists():
        return (
            jsonify({"error": "CA certificate not found on server. Place ca.crt in ./certs/."}),
            404,
        )
    return send_from_directory(Config.CERT_DIR, "ca.crt", as_attachment=True)
