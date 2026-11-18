import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from whoneedsacoach.store.db import connect


def _load(value: str | None):
    if value is None:
        return None
    return json.loads(value)


def _dump(value) -> str | None:
    if value is None:
        return None
    return json.dumps(value)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Repo:
    def __init__(self, path: Path):
        self.conn = connect(path)

    # --- users (app auth) ---

    def create_user(self, email: str, password_hash: str, display_name: str | None = None) -> dict:
        email = email.strip().lower()
        cursor = self.conn.execute(
            """
            INSERT INTO users (email, password_hash, display_name, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (email, password_hash, display_name, _now()),
        )
        self.conn.commit()
        return self.get_user(cursor.lastrowid)

    def get_user_by_email(self, email: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()
        if row is None:
            return None
        return self._user_row(row)

    def get_user(self, user_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        return self._user_row(row)

    def _user_row(self, row: sqlite3.Row) -> dict:
        connection = self.get_provider_connection(row["id"], "garmin")
        token_dir = connection["token_dir"] if connection and connection["status"] == "connected" else None
        return {
            "id": row["id"],
            "email": row["email"],
            "password_hash": row["password_hash"],
            "display_name": row["display_name"],
            "created_at": row["created_at"],
            # CLI / flow compatibility
            "name": row["display_name"] or row["email"],
            "garmin_token_dir": token_dir,
        }

    # --- CLI compatibility: name-based bootstrap ---

    def get_or_create_user(self, name: str, garmin_token_dir: str | None = None) -> dict:
        """CLI helper. Identity is display_name; email is synthesized as name@cli.local."""
        row = self.conn.execute(
            "SELECT * FROM users WHERE display_name = ? OR email = ?",
            (name, f"{name.strip().lower()}@cli.local"),
        ).fetchone()
        if row is None:
            cursor = self.conn.execute(
                """
                INSERT INTO users (email, password_hash, display_name, created_at)
                VALUES (?, NULL, ?, ?)
                """,
                (f"{name.strip().lower()}@cli.local", name, _now()),
            )
            self.conn.commit()
            user_id = cursor.lastrowid
        else:
            user_id = row["id"]
        if garmin_token_dir is not None:
            self.upsert_provider_connection(
                user_id,
                "garmin",
                token_dir=garmin_token_dir,
                status="connected",
            )
        return self.get_user(user_id)

    # --- refresh tokens ---

    def store_refresh_token(self, user_id: int, token_hash: str) -> None:
        self.conn.execute(
            """
            INSERT INTO refresh_tokens (user_id, token_hash, created_at, revoked_at)
            VALUES (?, ?, ?, NULL)
            """,
            (user_id, token_hash, _now()),
        )
        self.conn.commit()

    def get_refresh_token(self, token_hash: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM refresh_tokens WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "token_hash": row["token_hash"],
            "created_at": row["created_at"],
            "revoked_at": row["revoked_at"],
        }

    def revoke_refresh_token(self, token_hash: str) -> bool:
        cursor = self.conn.execute(
            """
            UPDATE refresh_tokens
            SET revoked_at = ?
            WHERE token_hash = ? AND revoked_at IS NULL
            """,
            (_now(), token_hash),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    # --- provider connections ---

    def upsert_provider_connection(
        self,
        user_id: int,
        provider: str,
        *,
        token_dir: str | None,
        status: str,
    ) -> dict:
        existing = self.get_provider_connection(user_id, provider)
        connected_at = _now() if status == "connected" else (existing["connected_at"] if existing else None)
        if existing is None:
            self.conn.execute(
                """
                INSERT INTO provider_connections
                    (user_id, provider, token_dir, status, connected_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, provider, token_dir, status, connected_at),
            )
        else:
            if status != "connected":
                connected_at = existing["connected_at"]
            self.conn.execute(
                """
                UPDATE provider_connections
                SET token_dir = ?, status = ?, connected_at = ?
                WHERE user_id = ? AND provider = ?
                """,
                (token_dir, status, connected_at, user_id, provider),
            )
        self.conn.commit()
        return self.get_provider_connection(user_id, provider)

    def get_provider_connection(self, user_id: int, provider: str) -> dict | None:
        row = self.conn.execute(
            """
            SELECT * FROM provider_connections
            WHERE user_id = ? AND provider = ?
            """,
            (user_id, provider),
        ).fetchone()
        if row is None:
            return None
        return self._provider_row(row)

    def list_provider_connections(self, user_id: int) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT * FROM provider_connections
            WHERE user_id = ?
            ORDER BY provider
            """,
            (user_id,),
        ).fetchall()
        return [self._provider_row(row) for row in rows]

    def disconnect_provider(self, user_id: int, provider: str) -> dict | None:
        existing = self.get_provider_connection(user_id, provider)
        if existing is None:
            return None
        self.conn.execute(
            """
            UPDATE provider_connections
            SET status = 'disconnected', token_dir = NULL
            WHERE user_id = ? AND provider = ?
            """,
            (user_id, provider),
        )
        self.conn.commit()
        return self.get_provider_connection(user_id, provider)

    def _provider_row(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "provider": row["provider"],
            "token_dir": row["token_dir"],
            "status": row["status"],
            "connected_at": row["connected_at"],
        }

    # --- plans ---

    def get_plan(self, user_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM plans WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        return self._plan(row)

    def create_plan(self, user_id: int, status: str = "intake") -> dict:
        self.conn.execute(
            """
            INSERT INTO plans (user_id, status, updated_at)
            VALUES (?, ?, ?)
            """,
            (user_id, status, _now()),
        )
        self.conn.commit()
        return self.get_plan(user_id)

    def upsert_plan_for_build(
        self,
        user_id: int,
        *,
        race: dict,
        schedule: dict,
        snapshot: dict,
        generation_id: str,
    ) -> dict:
        """Create or overwrite the user's plan row for an async build (always pending)."""
        existing = self.get_plan(user_id)
        snapshot = dict(snapshot)
        snapshot["generation_id"] = generation_id
        if existing is None:
            self.conn.execute(
                """
                INSERT INTO plans (
                    user_id, status, race_json, schedule_json, snapshot_json,
                    plan_json, pending_json, error_message, failed_at, updated_at
                ) VALUES (?, 'pending', ?, ?, ?, NULL, NULL, NULL, NULL, ?)
                """,
                (user_id, _dump(race), _dump(schedule), _dump(snapshot), _now()),
            )
        else:
            self.conn.execute(
                """
                UPDATE plans
                SET status = 'pending',
                    race_json = ?,
                    schedule_json = ?,
                    snapshot_json = ?,
                    plan_json = NULL,
                    pending_json = NULL,
                    error_message = NULL,
                    failed_at = NULL,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (_dump(race), _dump(schedule), _dump(snapshot), _now(), user_id),
            )
        self.conn.commit()
        return self.get_plan(user_id)

    def set_plan_status(
        self,
        user_id: int,
        status: str,
        *,
        plan_json=None,
        error_message: str | None = None,
        clear_error: bool = False,
        snapshot=None,
    ) -> dict | None:
        plan = self.get_plan(user_id)
        if plan is None:
            return None
        new_plan = plan["plan"] if plan_json is None else plan_json
        new_snapshot = plan["snapshot"] if snapshot is None else snapshot
        if status == "failed":
            new_error = error_message
            failed_at = _now()
        elif clear_error or status in {"pending", "building", "active"}:
            new_error = None
            failed_at = None
        else:
            new_error = plan.get("error_message")
            failed_at = plan.get("failed_at")
        self.conn.execute(
            """
            UPDATE plans
            SET status = ?,
                plan_json = ?,
                snapshot_json = ?,
                error_message = ?,
                failed_at = ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (
                status,
                _dump(new_plan),
                _dump(new_snapshot),
                new_error,
                failed_at,
                _now(),
                user_id,
            ),
        )
        self.conn.commit()
        return self.get_plan(user_id)

    def save_plan(self, plan: dict) -> dict:
        self.conn.execute(
            """
            UPDATE plans
            SET status = ?, race_json = ?, schedule_json = ?, snapshot_json = ?,
                plan_json = ?, pending_json = ?, error_message = ?, failed_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                plan["status"],
                _dump(plan.get("race")),
                _dump(plan.get("schedule")),
                _dump(plan.get("snapshot")),
                _dump(plan.get("plan")),
                _dump(plan.get("pending")),
                plan.get("error_message"),
                plan.get("failed_at"),
                _now(),
                plan["id"],
            ),
        )
        self.conn.commit()
        return self.get_plan(plan["user_id"])

    def plans_with_status(self, status: str) -> list[tuple[dict, dict]]:
        rows = self.conn.execute(
            """
            SELECT plans.id AS plan_id, users.id AS user_id
            FROM plans JOIN users ON users.id = plans.user_id
            WHERE plans.status = ?
            """,
            (status,),
        ).fetchall()
        pairs = []
        for row in rows:
            pairs.append((self.get_user(row["user_id"]), self.get_plan(row["user_id"])))
        return pairs

    def upsert_activity(self, activity: dict) -> None:
        self.conn.execute(
            """
            INSERT INTO activities (
                user_id, plan_id, session_date, garmin_activity_id,
                distance_km, duration_seconds, workout_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, garmin_activity_id) DO UPDATE SET
                plan_id = excluded.plan_id,
                session_date = excluded.session_date,
                distance_km = excluded.distance_km,
                duration_seconds = excluded.duration_seconds,
                workout_id = excluded.workout_id
            """,
            (
                activity["user_id"],
                activity["plan_id"],
                activity["session_date"],
                activity["garmin_activity_id"],
                activity["distance_km"],
                activity.get("duration_seconds"),
                activity.get("workout_id"),
            ),
        )
        self.conn.commit()

    def activities_between(self, user_id: int, start, end) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT * FROM activities
            WHERE user_id = ? AND session_date >= ? AND session_date <= ?
            ORDER BY session_date, id
            """,
            (user_id, start.isoformat(), end.isoformat()),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "plan_id": row["plan_id"],
                "session_date": row["session_date"],
                "garmin_activity_id": row["garmin_activity_id"],
                "distance_km": row["distance_km"],
                "duration_seconds": row["duration_seconds"],
                "workout_id": row["workout_id"],
            }
            for row in rows
        ]

    def _plan(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "status": row["status"],
            "race": _load(row["race_json"]),
            "schedule": _load(row["schedule_json"]),
            "snapshot": _load(row["snapshot_json"]),
            "plan": _load(row["plan_json"]),
            "pending": _load(row["pending_json"]),
            "error_message": row["error_message"] if "error_message" in row.keys() else None,
            "failed_at": row["failed_at"] if "failed_at" in row.keys() else None,
            "updated_at": row["updated_at"] if "updated_at" in row.keys() else None,
        }
