from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


MAX_RECENT_EVENTS = 10


class EventStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    async def initialize(self) -> None:
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)

        def _initialize() -> None:
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL NOT NULL,
                        kind TEXT NOT NULL,
                        message TEXT NOT NULL,
                        details_json TEXT NOT NULL DEFAULT '{}'
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_kind_timestamp ON events(kind, timestamp)"
                )

        async with self._lock:
            await asyncio.to_thread(_initialize)

    async def record(
        self,
        kind: str,
        message: str,
        details: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        timestamp = timestamp or datetime.now(timezone.utc)
        details_json = json.dumps(details or {}, separators=(",", ":"), default=str)

        def _record() -> None:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO events(timestamp, kind, message, details_json) VALUES (?, ?, ?, ?)",
                    (timestamp.timestamp(), kind, message, details_json),
                )

        async with self._lock:
            await asyncio.to_thread(_record)

    async def recent(self, limit: int = MAX_RECENT_EVENTS) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, MAX_RECENT_EVENTS))

        def _recent() -> list[dict[str, Any]]:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT id, timestamp, kind, message, details_json "
                    "FROM events ORDER BY timestamp DESC LIMIT ?",
                    (safe_limit,),
                ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                result.append(
                    {
                        "id": row["id"],
                        "timestamp": datetime.fromtimestamp(
                            row["timestamp"], timezone.utc
                        ).isoformat(),
                        "kind": row["kind"],
                        "message": row["message"],
                        "details": json.loads(row["details_json"]),
                    }
                )
            return result

        async with self._lock:
            return await asyncio.to_thread(_recent)

    async def count_since(self, kinds: Iterable[str], since: datetime) -> int:
        kind_list = tuple(kinds)
        if not kind_list:
            return 0
        placeholders = ",".join("?" for _ in kind_list)

        def _count() -> int:
            with self._connect() as connection:
                row = connection.execute(
                    f"SELECT COUNT(*) AS count FROM events "
                    f"WHERE kind IN ({placeholders}) AND timestamp >= ?",
                    (*kind_list, since.timestamp()),
                ).fetchone()
                return int(row["count"])

        async with self._lock:
            return await asyncio.to_thread(_count)

    async def latest_timestamp(self, kinds: Iterable[str]) -> datetime | None:
        kind_list = tuple(kinds)
        if not kind_list:
            return None
        placeholders = ",".join("?" for _ in kind_list)

        def _latest() -> datetime | None:
            with self._connect() as connection:
                row = connection.execute(
                    f"SELECT MAX(timestamp) AS timestamp FROM events "
                    f"WHERE kind IN ({placeholders})",
                    kind_list,
                ).fetchone()
            value = row["timestamp"]
            return datetime.fromtimestamp(value, timezone.utc) if value else None

        async with self._lock:
            return await asyncio.to_thread(_latest)

    async def reboots_last_24h(self, now: datetime) -> int:
        return await self.count_since(
            {"reboot_requested", "reboot_uncertain"}, now - timedelta(hours=24)
        )
