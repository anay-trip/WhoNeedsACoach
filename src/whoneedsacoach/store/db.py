import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    garmin_token_dir TEXT
);

CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE,
    status TEXT NOT NULL,
    race_json TEXT,
    schedule_json TEXT,
    snapshot_json TEXT,
    plan_json TEXT,
    pending_json TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""


ACTIVITIES = """
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    plan_id INTEGER NOT NULL,
    session_date TEXT NOT NULL,
    garmin_activity_id INTEGER NOT NULL,
    distance_km REAL NOT NULL,
    duration_seconds REAL,
    workout_id INTEGER,
    UNIQUE(user_id, garmin_activity_id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (plan_id) REFERENCES plans(id)
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.executescript(ACTIVITIES)
    return conn
