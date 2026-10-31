import json
import sqlite3
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


class Repo:
    def __init__(self, path: Path):
        self.conn = connect(path)

    def get_or_create_user(self, name: str, garmin_token_dir: str | None = None) -> dict:
        row = self.conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
        if row is None:
            cursor = self.conn.execute(
                "INSERT INTO users (name, garmin_token_dir) VALUES (?, ?)",
                (name, garmin_token_dir),
            )
            self.conn.commit()
            user_id = cursor.lastrowid
        else:
            user_id = row["id"]
        return self._user(user_id)

    def _user(self, user_id: int) -> dict:
        row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return {"id": row["id"], "name": row["name"], "garmin_token_dir": row["garmin_token_dir"]}

    def get_plan(self, user_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM plans WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        return self._plan(row)

    def create_plan(self, user_id: int) -> dict:
        self.conn.execute(
            "INSERT INTO plans (user_id, status) VALUES (?, 'intake')",
            (user_id,),
        )
        self.conn.commit()
        return self.get_plan(user_id)

    def save_plan(self, plan: dict) -> dict:
        self.conn.execute(
            """
            UPDATE plans
            SET status = ?, race_json = ?, schedule_json = ?, snapshot_json = ?,
                plan_json = ?, pending_json = ?
            WHERE id = ?
            """,
            (
                plan["status"],
                _dump(plan["race"]),
                _dump(plan["schedule"]),
                _dump(plan["snapshot"]),
                _dump(plan["plan"]),
                _dump(plan["pending"]),
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
            pairs.append((self._user(row["user_id"]), self.get_plan(row["user_id"])))
        return pairs

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
        }
