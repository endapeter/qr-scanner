"""Static file serving: scanner page, assets, passport photos and the CA cert."""

from __future__ import annotations

from flask import Blueprint, jsonify, send_from_directory

from ..config import Config

bp = Blueprint("static_files", __name__)


@bp.get("/")
def scanner_page():
    return send_from_directory(Config.PUBLIC_DIR, "scanner.html")


@bp.get("/public/<path:filename>")
def public_file(filename: str):
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
