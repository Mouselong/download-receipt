"""SQLite persistence for download receipts."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from .models import Receipt


SCHEMA_VERSION = 3


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
            table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'receipts'"
            ).fetchone()
            if table is None:
                self._create_table(connection)
            else:
                columns = {
                    str(row["name"])
                    for row in connection.execute("PRAGMA table_info(receipts)").fetchall()
                }
                if "is_current" not in columns:
                    self._migrate_v1(connection)
                elif "disposition" not in columns:
                    connection.execute(
                        "ALTER TABLE receipts ADD COLUMN disposition TEXT NOT NULL DEFAULT 'inbox'"
                    )
            self._create_indexes(connection)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @staticmethod
    def _create_table(connection: sqlite3.Connection, name: str = "receipts") -> None:
        connection.execute(
            f"""
            CREATE TABLE {name} (
                id INTEGER PRIMARY KEY,
                path TEXT NOT NULL COLLATE NOCASE,
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
                file_identity TEXT,
                disposition TEXT NOT NULL DEFAULT 'inbox',
                note TEXT NOT NULL DEFAULT '',
                is_missing INTEGER NOT NULL DEFAULT 0,
                is_current INTEGER NOT NULL DEFAULT 1,
                superseded_at TEXT
            )
            """
        )

    def _migrate_v1(self, connection: sqlite3.Connection) -> None:
        self._create_table(connection, "receipts_v2")
        connection.execute(
            """
            INSERT INTO receipts_v2 (
                id, path, file_name, file_size, modified_at, first_seen_at,
                last_seen_at, host_url, referrer_url, source_domain, zone_id,
                sha256, file_identity, disposition, note, is_missing, is_current,
                superseded_at
            )
            SELECT id, path, file_name, file_size, modified_at, first_seen_at,
                last_seen_at, host_url, referrer_url, source_domain, zone_id,
                sha256, NULL, 'inbox', note, is_missing, 1, NULL
            FROM receipts
            """
        )
        connection.execute("DROP TABLE receipts")
        connection.execute("ALTER TABLE receipts_v2 RENAME TO receipts")

    @staticmethod
    def _create_indexes(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_receipts_current_path
                ON receipts(path COLLATE NOCASE) WHERE is_current = 1;
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
        file_identity: str | None = None,
    ) -> int:
        """Save a scan, preserving an older receipt when the file changed."""

        with closing(self._connect()) as connection, connection:
            current = connection.execute(
                """
                SELECT id, file_size, modified_at, file_identity
                FROM receipts
                WHERE path = ? COLLATE NOCASE AND is_current = 1
                """,
                (path,),
            ).fetchone()
            same_identity = (
                current is not None
                and (
                    current["file_identity"] is None
                    or file_identity is None
                    or current["file_identity"] == file_identity
                )
            )
            same_version = (
                current is not None
                and same_identity
                and int(current["file_size"]) == file_size
                and str(current["modified_at"]) == modified_at
            )

            if same_version:
                receipt_id = int(current["id"])
                connection.execute(
                    """
                    UPDATE receipts SET
                        file_name = ?, last_seen_at = ?,
                        host_url = COALESCE(host_url, ?),
                        referrer_url = COALESCE(referrer_url, ?),
                        source_domain = COALESCE(source_domain, ?),
                        zone_id = COALESCE(zone_id, ?),
                        sha256 = COALESCE(sha256, ?),
                        file_identity = COALESCE(file_identity, ?),
                        is_missing = 0
                    WHERE id = ?
                    """,
                    (
                        file_name,
                        seen_at,
                        host_url,
                        referrer_url,
                        source_domain,
                        zone_id,
                        sha256,
                        file_identity,
                        receipt_id,
                    ),
                )
            else:
                if current is not None:
                    connection.execute(
                        """
                        UPDATE receipts
                        SET is_current = 0, is_missing = 1, superseded_at = ?
                        WHERE id = ?
                        """,
                        (seen_at, int(current["id"])),
                    )
                cursor = connection.execute(
                    """
                    INSERT INTO receipts (
                        path, file_name, file_size, modified_at, first_seen_at,
                        last_seen_at, host_url, referrer_url, source_domain,
                        zone_id, sha256, file_identity, is_missing, is_current
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1)
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
                        file_identity,
                    ),
                )
                receipt_id = int(cursor.lastrowid)
        return receipt_id

    def get_by_path(self, path: str) -> Receipt | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                self._select_sql()
                + " WHERE r.path = ? COLLATE NOCASE AND r.is_current = 1",
                (path,),
            ).fetchone()
        return self._to_receipt(row) if row else None

    def get(self, receipt_id: int) -> Receipt | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                self._select_sql() + " WHERE r.id = ?", (receipt_id,)
            ).fetchone()
        return self._to_receipt(row) if row else None

    def list(self, search: str = "", filter_name: str = "all") -> list[Receipt]:
        return self._list(search, filter_name, limit=1000)

    def export_all(self) -> list[Receipt]:
        return self._list("", "all", limit=None)

    def _list(
        self, search: str, filter_name: str, *, limit: int | None
    ) -> list[Receipt]:
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
                "r.is_current = 1 AND r.is_missing = 0 AND r.sha256 IS NOT NULL "
                "AND EXISTS (SELECT 1 FROM receipts other "
                "WHERE other.sha256 = r.sha256 AND other.id <> r.id "
                "AND other.is_current = 1 AND other.is_missing = 0)"
            )
        elif filter_name == "missing":
            clauses.append("r.is_current = 1 AND r.is_missing = 1")
        elif filter_name == "replaced":
            clauses.append("r.is_current = 0")
        elif filter_name == "inbox":
            clauses.append("r.is_current = 1 AND r.disposition = 'inbox'")
        elif filter_name == "remove":
            clauses.append("r.is_current = 1 AND r.disposition = 'remove'")

        sql = self._select_sql()
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY r.first_seen_at DESC"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"

        with closing(self._connect()) as connection, connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [self._to_receipt(row) for row in rows]

    def update_note(self, receipt_id: int, note: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE receipts SET note = ? WHERE id = ?", (note.strip(), receipt_id)
            )

    def update_disposition(self, receipt_id: int, disposition: str) -> None:
        if disposition not in {"inbox", "keep", "later", "remove"}:
            raise ValueError(f"Unknown disposition: {disposition}")
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE receipts SET disposition = ? WHERE id = ? AND is_current = 1",
                (disposition, receipt_id),
            )

    def delete(self, receipt_id: int) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))

    def relocate(
        self,
        receipt_id: int,
        *,
        new_path: str,
        file_size: int,
        modified_at: str,
        file_identity: str | None,
        sha256: str | None,
        seen_at: str,
    ) -> None:
        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute(
                    """
                    UPDATE receipts
                    SET path = ?, file_name = ?, file_size = ?, modified_at = ?,
                        file_identity = ?, sha256 = COALESCE(?, sha256),
                        last_seen_at = ?, is_missing = 0
                    WHERE id = ? AND is_current = 1
                    """,
                    (
                        new_path,
                        Path(new_path).name,
                        file_size,
                        modified_at,
                        file_identity,
                        sha256,
                        seen_at,
                        receipt_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Only a current receipt can be relocated.")
        except sqlite3.IntegrityError as error:
            raise ValueError("That file already has a current receipt.") from error

    def mark_missing_in_folder(
        self, folder: Path, present_paths: set[str], *, recursive: bool
    ) -> int:
        root = _canonical_path(folder)
        present = {_canonical_path(path) for path in present_paths}
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT id, path FROM receipts WHERE is_current = 1 AND is_missing = 0"
            ).fetchall()
            missing_ids: list[tuple[int]] = []
            for row in rows:
                candidate = _canonical_path(str(row["path"]))
                try:
                    in_scope = (
                        os.path.commonpath([root, candidate]) == root
                        if recursive
                        else os.path.dirname(candidate) == root
                    )
                except ValueError:
                    in_scope = False
                if in_scope and candidate not in present:
                    missing_ids.append((int(row["id"]),))
            connection.executemany(
                "UPDATE receipts SET is_missing = 1 WHERE id = ?", missing_ids
            )
        return len(missing_ids)

    def stats(self) -> dict[str, int]:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN is_current = 1 THEN 1 ELSE 0 END) AS active,
                    SUM(CASE WHEN host_url IS NOT NULL OR referrer_url IS NOT NULL
                        THEN 1 ELSE 0 END) AS sourced,
                    SUM(CASE WHEN TRIM(note) <> '' THEN 1 ELSE 0 END) AS noted,
                    SUM(CASE WHEN is_current = 1 AND is_missing = 1
                        THEN 1 ELSE 0 END) AS missing,
                    SUM(CASE WHEN is_current = 0 THEN 1 ELSE 0 END) AS replaced
                FROM receipts
                """
            ).fetchone()
        assert row is not None
        return {key: int(row[key] or 0) for key in row.keys()}

    @staticmethod
    def _select_sql() -> str:
        return """
            SELECT r.*,
                CASE WHEN r.is_current = 1 AND r.is_missing = 0
                    AND r.sha256 IS NOT NULL AND EXISTS (
                    SELECT 1 FROM receipts duplicate
                    WHERE duplicate.sha256 = r.sha256 AND duplicate.id <> r.id
                    AND duplicate.is_current = 1 AND duplicate.is_missing = 0
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
            file_identity=row["file_identity"],
            disposition=str(row["disposition"]),
            note=str(row["note"]),
            is_missing=bool(row["is_missing"]),
            is_current=bool(row["is_current"]),
            superseded_at=row["superseded_at"],
            is_duplicate=bool(row["is_duplicate"]),
        )


def _canonical_path(path: str | Path) -> str:
    """Normalize aliases such as Windows junctions before path comparison."""

    try:
        resolved = Path(path).resolve(strict=False)
    except OSError:
        resolved = Path(os.path.abspath(str(path)))
    return os.path.normcase(os.path.normpath(str(resolved)))
