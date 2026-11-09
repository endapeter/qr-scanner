"""Scan intake endpoint used by the scanner page.

Everything here is reachable by unauthenticated scanning devices. Anything
containing student data lives in routes/admin.py behind its auth gate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

from .. import database
from ..events import broker

bp = Blueprint("scans", __name__)

# Fields the scanner may send. Anything else in the payload is ignored.
_ENTRY_FIELDS = ("first_name", "surname", "other_names", "student_id", "student_year", "passport_picture")


@bp.post("/log")
def log_scan() -> tuple[Response, int] | Response:
    """Record an incoming QR scan against the currently active class."""
    data: Any = request.get_json(silent=True)
    if not isinstance(data, dict) or not data:
        return jsonify({"error": "Expected a JSON object"}), 400

    class_name = database.get_active_class()
    if not class_name:
        return (
            jsonify(
                {
                    "error": "No class is being tracked. Set one on the admin dashboard first.",
                    "status": "no_class",
                }
            ),
            409,
        )

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    student_id = str(data.get("student_id") or "")

    if database.is_duplicate(class_name, student_id, timestamp):
        current_app.logger.info("Duplicate scan ignored: %s in %s", student_id, class_name)
        payload = {
            "status": "duplicate",
            "message": "Already recorded for this class today",
            "class": class_name,
            "entry": {"student_id": student_id, "first_name": data.get("first_name", ""),
                      "surname": data.get("surname", "")},
            "timestamp": timestamp,
        }
        broker.publish("duplicate", payload)
        return jsonify(payload), 200

    record = database.add_scan(data, class_name, timestamp)
    current_app.logger.info("Scan recorded: %s in %s", record["student_id"], class_name)

    payload = {"status": "ok", "class": class_name, "entry": record}
    broker.publish("scan", payload)
    return jsonify(payload), 200


@bp.get("/api/active-class")
def api_active_class() -> Response:
    """Scanner devices call this to show which class they are scanning for."""
    return jsonify({"class": database.get_active_class()})
