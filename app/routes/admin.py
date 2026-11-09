"""Admin dashboard: page, API and live attendance stream.

Authentication is optional: when the ADMIN_PASSWORD environment variable is
set, all admin pages and APIs require a logged-in session. When unset, the
dashboard is open (fine for an isolated LAN, not for hostile networks).
"""

from __future__ import annotations

import hmac
import queue
from typing import Any

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    redirect,
    render_template_string,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)

from .. import database
from ..config import Config
from ..events import broker

bp = Blueprint("admin", __name__)

_LOGIN_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin login</title>
<style>
 body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
      background:#f5f7fb;font-family:Inter,system-ui,sans-serif;}
 form{background:#fff;padding:2rem;border-radius:12px;box-shadow:0 6px 18px rgba(15,23,42,.06);
      display:flex;flex-direction:column;gap:.75rem;width:min(90vw,320px);}
 h1{font-size:1.1rem;margin:0;color:#0f172a;}
 input{padding:.6rem .75rem;border-radius:8px;border:1px solid #e6eefc;font-size:1rem;}
 button{padding:.6rem;border:0;border-radius:8px;background:#2563eb;color:#fff;
        font-size:1rem;cursor:pointer;}
 .err{color:#ef4444;font-size:.85rem;margin:0;}
</style>
</head>
<body>
<form method="post">
 <h1>Admin login</h1>
 {% if error %}<p class="err">{{ error }}</p>{% endif %}
 <input type="password" name="password" placeholder="Password" autofocus required>
 <button type="submit">Sign in</button>
</form>
</body>
</html>"""


def auth_enabled() -> bool:
    return bool(current_app.config.get("ADMIN_PASSWORD"))


def is_authenticated() -> bool:
    return bool(session.get("admin"))


@bp.before_request
def require_login():
    """Guard every admin route (except the login handlers themselves)."""
    if not auth_enabled():
        return None
    if request.endpoint in ("admin.login", "admin.logout"):
        return None
    if not is_authenticated():
        if request.path.startswith("/api/"):
            return jsonify({"error": "Authentication required"}), 401
        return redirect(url_for("admin.login"))

    return None


@bp.get("/admin")
def dashboard():
    # The page itself is static; everything is loaded via the API below.
    return send_from_directory(Config.PUBLIC_DIR, "admin.html")


@bp.route("/admin/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        if hmac.compare_digest(password, str(current_app.config.get("ADMIN_PASSWORD") or "")):
            session["admin"] = True
            session.permanent = True
            return redirect(url_for("admin.dashboard"))
        error = "Wrong password"
    return render_template_string(_LOGIN_PAGE, error=error)


@bp.get("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("admin.login"))


# ---------------------------------------------------------------------------
# Admin API
# ---------------------------------------------------------------------------

@bp.get("/api/classes")
def api_classes():
    return jsonify(
        {
            "classes": database.list_classes(),
            "active_class": database.get_active_class(),
        }
    )


@bp.post("/api/classes")
def api_set_active_class():
    """Select which class scanner devices are currently tracking for."""
    data: Any = request.get_json(silent=True)
    name = str((data or {}).get("name") or "").strip()
    if not name:
        return jsonify({"error": "Class name is required"}), 400
    database.set_active_class(name)
    current_app.logger.info("Active class set to %r", name)
    return jsonify({"active_class": name})


@bp.get("/api/csv")
def api_csv_files():
    """The scan archive: where the CSVs live and what is in them."""
    return jsonify(database.csv_files_info())


@bp.get("/api/csv/<slug>/download")
def api_download_csv(slug: str):
    """Download the CSV for one class, identified by its slug."""
    safe_name = database.class_slug(slug)
    csv_path = Config.CSV_DIR / f"{safe_name}.csv"
    if not csv_path.exists():
        return jsonify({"error": f"No CSV found for {slug!r}"}), 404
    return send_file(csv_path, as_attachment=True, download_name=csv_path.name)


@bp.get("/api/stream")
def api_stream():
    """Server-Sent Events feed of scans as they arrive."""
    from flask import stream_with_context

    q = broker.subscribe()

    @stream_with_context
    def generate():
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    message = q.get(timeout=15)
                except queue.Empty:
                    yield ": keep-alive\n\n"  # heartbeat so proxies don't drop the stream
                    continue
                yield f"event: scan\ndata: {message}\n\n"
        finally:
            broker.unsubscribe(q)

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response
