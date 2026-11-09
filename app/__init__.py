"""QR attendance server — application factory."""

from __future__ import annotations

import os
import secrets
from typing import Any

from flask import Flask

from . import database
from .config import Config


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)

    # Config values are class attributes; copy them into app.config so tests
    # and extensions can override them through the standard mechanism.
    app.config.from_object(Config)

    # A stable secret key so admin sessions survive restarts.
    app.config["SECRET_KEY"] = _load_or_create_secret_key()

    database.init_app(app)

    from .routes import admin, scans, static_files

    app.register_blueprint(static_files.bp)
    app.register_blueprint(scans.bp)
    app.register_blueprint(admin.bp)

    return app


def _load_or_create_secret_key() -> str:
    """Session signing key, persisted under the data directory."""
    Config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    key_file = Config.DATA_DIR / "secret_key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    key_file.write_text(key, encoding="utf-8")
    try:
        os.chmod(key_file, 0o600)  # POSIX only; harmless no-op on Windows
    except (OSError, NotImplementedError):
        pass
    return key
