
import json
import sqlite3
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DB_PATH = Path(__file__).resolve().parent / "tripwise.db"


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS trips (
                id TEXT PRIMARY KEY,
                destination TEXT NOT NULL,
                travelers INTEGER NOT NULL,
                trip_days INTEGER NOT NULL,
                budget_limit REAL NOT NULL,
                fixed_costs_json TEXT NOT NULL,
                activities_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def create_trip(data: dict[str, Any]) -> dict[str, Any]:
    trip_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO trips (
                id, destination, travelers, trip_days,
                budget_limit, fixed_costs_json, activities_json,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trip_id,
                data["destination"],
                data["travelers"],
                data["trip_days"],
                data["budget_limit"],
                json.dumps(data["fixed_costs"]),
                json.dumps(data["activities"]),
                now,
                now,
            ),
        )

    return get_trip(trip_id)


def get_trip(trip_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM trips WHERE id = ?",
            (trip_id,),
        ).fetchone()

    if row is None:
        return None

    trip = dict(row)
    trip["fixed_costs"] = json.loads(trip.pop("fixed_costs_json"))
    trip["activities"] = json.loads(trip.pop("activities_json"))

    return trip


def update_trip(
    trip_id: str,
    fixed_costs: dict[str, float],
    activities: list[dict[str, Any]],
) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE trips
            SET fixed_costs_json = ?,
                activities_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(fixed_costs),
                json.dumps(activities),
                now,
                trip_id,
            ),
        )

        if cursor.rowcount == 0:
            return None

    return get_trip(trip_id)


initialize_db()
