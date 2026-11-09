"""SQLite storage for scans, classes and app settings.

The database is the source of truth. Per-class CSV files under
``Config.CSV_DIR`` are maintained alongside it on every accepted scan so the
CSVs on disk are always ready for download.
"""

from __future__ import annotations

import csv
import io
import re
import sqlite3
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import current_app, g

from .config import Config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    class            TEXT NOT NULL,
    timestamp        TEXT NOT NULL,
    first_name       TEXT NOT NULL DEFAULT '',
    surname          TEXT NOT NULL DEFAULT '',
    other_names      TEXT NOT NULL DEFAULT '',
    student_id       TEXT NOT NULL DEFAULT '',
    student_year     TEXT NOT NULL DEFAULT '',
    passport_picture TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS classes (
    name       TEXT PRIMARY KEY,
    slug       TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scans_class_time   ON scans (class, timestamp);
CREATE INDEX IF NOT EXISTS idx_scans_class_student ON scans (class, student_id);
"""

_SLUG_RE = re.compile(r"[^A-Za-z0-9_-]+")


def class_slug(name: str) -> str:
    """Filesystem-safe slug for a class name (used as the CSV filename)."""
    slug = _SLUG_RE.sub("_", name).strip("_").lower()
    return slug or "unnamed"


def get_db() -> sqlite3.Connection:
    """Per-request connection, stored on flask.g."""
    if "db" not in g:
        g.db = sqlite3.connect(Config.DATABASE_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc: BaseException | None = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app: Any) -> None:
    app.teardown_appcontext(close_db)


def init_db() -> None:
    """Create directories and tables. Safe to call on every startup."""
    Config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    Config.CSV_DIR.mkdir(parents=True, exist_ok=True)
    Config.PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(Config.DATABASE_PATH) as db:
        db.executescript(_SCHEMA)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_setting(key: str) -> str | None:
    row = get_db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    db = get_db()
    db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    db.commit()


def get_active_class() -> str | None:
    return get_setting("active_class")


def set_active_class(name: str) -> str:
    """Make ``name`` the class new scans are attributed to, registering it if needed."""
    db = get_db()
    db.execute(
        "INSERT INTO classes (name, slug, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(name) DO NOTHING",
        (name, class_slug(name), datetime.now().isoformat(timespec="seconds")),
    )
    db.commit()
    set_setting("active_class", name)
    return name


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------

def list_classes() -> list[dict[str, Any]]:
    """All known classes with scan counts and most-recent scan time."""
    rows = get_db().execute(
        """
        SELECT c.name, c.slug, c.created_at,
               (SELECT COUNT(*)      FROM scans s WHERE s.class = c.name)          AS scan_count,
               (SELECT MAX(s.timestamp) FROM scans s WHERE s.class = c.name)        AS last_scan
        FROM classes c
        ORDER BY c.name
        """
    ).fetchall()
    return [dict(row) for row in rows]


def delete_class(name: str) -> int:
    """Delete a class, all its scans and its CSV file. Returns scans removed."""
    db = get_db()
    removed = db.execute("SELECT COUNT(*) AS n FROM scans WHERE class = ?", (name,)).fetchone()["n"]
    slug_row = db.execute("SELECT slug FROM classes WHERE name = ?", (name,)).fetchone()
    db.execute("DELETE FROM scans WHERE class = ?", (name,))
    db.execute("DELETE FROM classes WHERE name = ?", (name,))
    if get_active_class() == name:
        set_setting("active_class", "")
    db.commit()

    if slug_row:
        with suppress(OSError):
            csv_file_for_class(name).unlink()
    return removed


def clear_all_scans() -> int:
    """Delete every scan, class and CSV file, and reset the active class.

    The database file itself is kept (schema intact); this empties it.
    Returns the number of scans removed.
    """
    db = get_db()
    removed = db.execute("SELECT COUNT(*) AS n FROM scans").fetchone()["n"]
    db.execute("DELETE FROM scans")
    db.execute("DELETE FROM classes")
    db.execute("DELETE FROM settings")
    db.commit()

    for path in Config.CSV_DIR.glob("*.csv"):
        with suppress(OSError):
            path.unlink()
    return removed


# ---------------------------------------------------------------------------
# Scans
# ---------------------------------------------------------------------------

def is_duplicate(class_name: str, student_id: str, timestamp: str) -> bool:
    """True if this student already scanned for this class on the same day."""
    if not student_id or not Config.DEDUPE_WITHIN_DAY:
        return False
    day = timestamp[:10]  # timestamps start with YYYY-MM-DD
    row = get_db().execute(
        "SELECT 1 FROM scans WHERE class = ? AND student_id = ? AND substr(timestamp, 1, 10) = ? LIMIT 1",
        (class_name, student_id, day),
    ).fetchone()
    return row is not None


def add_scan(entry: dict[str, Any], class_name: str, timestamp: str) -> dict[str, Any]:
    """Persist an accepted scan to the database and append it to the class CSV."""
    fields = {key: str(entry.get(key) or "") for key in Config.CSV_HEADER if key not in ("timestamp", "class")}
    record = {"timestamp": timestamp, "class": class_name, **fields}

    db = get_db()
    columns = ", ".join(record)
    placeholders = ", ".join("?" for _ in record)
    db.execute(f"INSERT INTO scans ({columns}) VALUES ({placeholders})", tuple(record.values()))
    db.commit()

    _append_csv(class_name, record)
    return record


def _append_csv(class_name: str, record: dict[str, str]) -> None:
    csv_path = csv_file_for_class(class_name)
    is_new = not csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(Config.CSV_HEADER)
        writer.writerow([record[column] for column in Config.CSV_HEADER])


def csv_file_for_class(class_name: str) -> Path:
    return Config.CSV_DIR / f"{class_slug(class_name)}.csv"


def recent_scans(class_name: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    """Most recent scans, newest first, optionally filtered by class."""
    if class_name:
        rows = get_db().execute(
            "SELECT * FROM scans WHERE class = ? ORDER BY id DESC LIMIT ?",
            (class_name, limit),
        )
    else:
        rows = get_db().execute("SELECT * FROM scans ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(row) for row in rows]


def csv_files_info() -> dict[str, Any]:
    """Metadata for every CSV in the archive directory, plus the directory itself."""
    files: list[dict[str, Any]] = []
    name_by_slug = {row["slug"]: row["name"] for row in get_db().execute("SELECT name, slug FROM classes")}

    for path in sorted(Config.CSV_DIR.glob("*.csv")):
        stat = path.stat()
        slug = path.stem
        files.append(
            {
                "class": name_by_slug.get(slug, slug),
                "slug": slug,
                "filename": path.name,
                "bytes": stat.st_size,
                "rows": _count_rows(path),
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            }
        )

    return {
        "directory": str(Config.CSV_DIR),
        "database": str(Config.DATABASE_PATH),
        "files": files,
    }


# ---------------------------------------------------------------------------
# Per-day attendance (generated from the database on demand)
# ---------------------------------------------------------------------------

def class_days(class_name: str | None = None) -> list[dict[str, Any]]:
    """One row per (class, day) that has scans: date, count, first/last scan.

    With class_name, only that class is listed; otherwise every class.
    """
    if class_name:
        rows = get_db().execute(
            """
            SELECT class, substr(timestamp, 1, 10) AS day,
                   COUNT(*) AS count, MIN(timestamp) AS first_scan, MAX(timestamp) AS last_scan
            FROM scans WHERE class = ?
            GROUP BY class, day ORDER BY day DESC
            """,
            (class_name,),
        )
    else:
        rows = get_db().execute(
            """
            SELECT class, substr(timestamp, 1, 10) AS day,
                   COUNT(*) AS count, MIN(timestamp) AS first_scan, MAX(timestamp) AS last_scan
            FROM scans GROUP BY class, day ORDER BY class, day DESC
            """
        )
    return [dict(row) for row in rows]


def day_csv(class_name: str, day: str) -> str | None:
    """CSV text for one class on one day (YYYY-MM-DD). None if no scans."""
    rows = get_db().execute(
        "SELECT * FROM scans WHERE class = ? AND substr(timestamp, 1, 10) = ? "
        "ORDER BY timestamp",
        (class_name, day),
    ).fetchall()
    if not rows:
        return None

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(Config.CSV_HEADER)
    for row in rows:
        writer.writerow([row[column] for column in Config.CSV_HEADER])
    return buf.getvalue()


def _count_rows(path: Path) -> int:
    """Data rows in a CSV (header excluded). Blank lines are ignored."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return max(sum(1 for line in f if line.strip()) - 1, 0)
