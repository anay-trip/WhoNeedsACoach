import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT,
    display_name TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    token_hash TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    revoked_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS provider_connections (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    token_dir TEXT,
    status TEXT NOT NULL,
    connected_at TEXT,
    UNIQUE(user_id, provider),
    FOREIGN KEY (user_id) REFERENCES users(id)
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
    error_message TEXT,
    failed_at TEXT,
    updated_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

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


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring older coach.db files up to the current schema without wiping data."""
    tables = _table_names(conn)
    if "users_new" in tables and "users" in tables:
        # Recover from a previously interrupted migration.
        conn.execute("DROP TABLE IF EXISTS users_new")
        tables = _table_names(conn)

    if "users" not in tables:
        return

    cols = _column_names(conn, "users")
    if "email" in cols:
        # Already on the new users shape; only ensure plan columns.
        _migrate_plan_columns(conn)
        return

    if "name" not in cols:
        return

    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        """
        CREATE TABLE users_new (
            id INTEGER PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            display_name TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS provider_connections (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            token_dir TEXT,
            status TEXT NOT NULL,
            connected_at TEXT,
            UNIQUE(user_id, provider),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    rows = conn.execute("SELECT id, name, garmin_token_dir FROM users").fetchall()
    for row in rows:
        email = f"{row['name'].strip().lower()}@cli.local"
        conn.execute(
            """
            INSERT INTO users_new (id, email, password_hash, display_name, created_at)
            VALUES (?, ?, NULL, ?, datetime('now'))
            """,
            (row["id"], email, row["name"]),
        )
        if row["garmin_token_dir"]:
            conn.execute(
                """
                INSERT OR IGNORE INTO provider_connections
                    (user_id, provider, token_dir, status, connected_at)
                VALUES (?, 'garmin', ?, 'connected', datetime('now'))
                """,
                (row["id"], row["garmin_token_dir"]),
            )
    conn.execute("DROP TABLE users")
    conn.execute("ALTER TABLE users_new RENAME TO users")
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")
    _migrate_plan_columns(conn)


def _migrate_plan_columns(conn: sqlite3.Connection) -> None:
    if "plans" not in _table_names(conn):
        return
    cols = _column_names(conn, "plans")
    for column, ddl in (
        ("error_message", "TEXT"),
        ("failed_at", "TEXT"),
        ("updated_at", "TEXT"),
        ("pending_json", "TEXT"),
    ):
        if column not in cols:
            conn.execute(f"ALTER TABLE plans ADD COLUMN {column} {ddl}")
    conn.commit()


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _migrate(conn)
    conn.executescript(SCHEMA)
    return conn
