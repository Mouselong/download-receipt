"""SQLite persistence for download receipts."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from .models import Receipt


class ReceiptRepository:
    """Repository with one short-lived connection per operation."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS receipts (
                    id INTEGER PRIMARY KEY,
                    path TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    file_name TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    modified_at TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    host_url TEXT,
                    referrer_url TEXT,
                    source_domain TEXT,
                    zone_id INTEGER,
                    sha256 TEXT,
                    note TEXT NOT NULL DEFAULT '',
                    is_missing INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_receipts_name
                    ON receipts(file_name);
                CREATE INDEX IF NOT EXISTS idx_receipts_domain
                    ON receipts(source_domain);
                CREATE INDEX IF NOT EXISTS idx_receipts_sha256
                    ON receipts(sha256);
                CREATE INDEX IF NOT EXISTS idx_receipts_seen
                    ON receipts(first_seen_at DESC);
                """
            )

    def upsert(
        self,
        *,
        path: str,
        file_name: str,
        file_size: int,
        modified_at: str,
        seen_at: str,
        host_url: str | None,
        referrer_url: str | None,
        source_domain: str | None,
        zone_id: int | None,
        sha256: str | None,
    ) -> int:
        """Insert a receipt or refresh metadata while preserving its note."""

        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO receipts (
                    path, file_name, file_size, modified_at, first_seen_at,
                    last_seen_at, host_url, referrer_url, source_domain,
                    zone_id, sha256, is_missing
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(path) DO UPDATE SET
                    file_name = excluded.file_name,
                    file_size = excluded.file_size,
                    modified_at = excluded.modified_at,
                    last_seen_at = excluded.last_seen_at,
                    host_url = COALESCE(excluded.host_url, receipts.host_url),
                    referrer_url = COALESCE(excluded.referrer_url, receipts.referrer_url),
                    source_domain = COALESCE(excluded.source_domain, receipts.source_domain),
                    zone_id = COALESCE(excluded.zone_id, receipts.zone_id),
                    sha256 = COALESCE(excluded.sha256, receipts.sha256),
                    is_missing = 0
                """,
                (
                    path,
                    file_name,
                    file_size,
                    modified_at,
                    seen_at,
                    seen_at,
                    host_url,
                    referrer_url,
                    source_domain,
                    zone_id,
                    sha256,
                ),
            )
            row = connection.execute(
                "SELECT id FROM receipts WHERE path = ? COLLATE NOCASE", (path,)
            ).fetchone()
        assert row is not None
        return int(row["id"])

    def get_by_path(self, path: str) -> Receipt | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                self._select_sql() + " WHERE r.path = ? COLLATE NOCASE", (path,)
            ).fetchone()
        return self._to_receipt(row) if row else None

    def get(self, receipt_id: int) -> Receipt | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                self._select_sql() + " WHERE r.id = ?", (receipt_id,)
            ).fetchone()
        return self._to_receipt(row) if row else None

    def list(self, search: str = "", filter_name: str = "all") -> list[Receipt]:
        clauses: list[str] = []
        parameters: list[object] = []

        if search.strip():
            pattern = f"%{search.strip()}%"
            clauses.append(
                "(r.file_name LIKE ? OR r.source_domain LIKE ? OR "
                "r.host_url LIKE ? OR r.referrer_url LIKE ? OR r.note LIKE ?)"
            )
            parameters.extend([pattern] * 5)

        if filter_name == "with_source":
            clauses.append("r.host_url IS NOT NULL OR r.referrer_url IS NOT NULL")
        elif filter_name == "needs_note":
            clauses.append("TRIM(r.note) = ''")
        elif filter_name == "duplicates":
            clauses.append(
                "r.sha256 IS NOT NULL AND EXISTS ("
                "SELECT 1 FROM receipts other WHERE other.sha256 = r.sha256 "
                "AND other.id <> r.id)"
            )

        sql = self._select_sql()
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY r.first_seen_at DESC LIMIT 1000"

        with closing(self._connect()) as connection, connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [self._to_receipt(row) for row in rows]

    def update_note(self, receipt_id: int, note: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE receipts SET note = ? WHERE id = ?", (note.strip(), receipt_id)
            )

    def delete(self, receipt_id: int) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))

    def stats(self) -> dict[str, int]:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN host_url IS NOT NULL OR referrer_url IS NOT NULL
                        THEN 1 ELSE 0 END) AS sourced,
                    SUM(CASE WHEN TRIM(note) <> '' THEN 1 ELSE 0 END) AS noted,
                    SUM(CASE WHEN is_missing = 1 THEN 1 ELSE 0 END) AS missing
                FROM receipts
                """
            ).fetchone()
        assert row is not None
        return {
            "total": int(row["total"] or 0),
            "sourced": int(row["sourced"] or 0),
            "noted": int(row["noted"] or 0),
            "missing": int(row["missing"] or 0),
        }

    @staticmethod
    def _select_sql() -> str:
        return """
            SELECT r.*,
                CASE WHEN r.sha256 IS NOT NULL AND EXISTS (
                    SELECT 1 FROM receipts duplicate
                    WHERE duplicate.sha256 = r.sha256 AND duplicate.id <> r.id
                ) THEN 1 ELSE 0 END AS is_duplicate
            FROM receipts r
        """

    @staticmethod
    def _to_receipt(row: sqlite3.Row) -> Receipt:
        return Receipt(
            id=int(row["id"]),
            path=str(row["path"]),
            file_name=str(row["file_name"]),
            file_size=int(row["file_size"]),
            modified_at=str(row["modified_at"]),
            first_seen_at=str(row["first_seen_at"]),
            last_seen_at=str(row["last_seen_at"]),
            host_url=row["host_url"],
            referrer_url=row["referrer_url"],
            source_domain=row["source_domain"],
            zone_id=row["zone_id"],
            sha256=row["sha256"],
            note=str(row["note"]),
            is_missing=bool(row["is_missing"]),
            is_duplicate=bool(row["is_duplicate"]),
        )
