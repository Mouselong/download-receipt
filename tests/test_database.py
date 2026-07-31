from __future__ import annotations

import tempfile
import unittest
import sqlite3
from contextlib import closing
from pathlib import Path

from download_receipt.database import ReceiptRepository


class ReceiptRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "receipts.db"
        self.repository = ReceiptRepository(database_path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def add_receipt(
        self,
        path: str = r"C:\Downloads\guide.pdf",
        sha256: str | None = "abc123",
        *,
        file_size: int = 1024,
        modified_at: str = "2026-07-29T10:00:00+00:00",
        file_identity: str | None = "1:1",
    ) -> int:
        return self.repository.upsert(
            path=path,
            file_name=Path(path).name,
            file_size=file_size,
            modified_at=modified_at,
            seen_at="2026-07-29T10:01:00+00:00",
            host_url="https://cdn.example.com/guide.pdf",
            referrer_url="https://example.com/guides",
            source_domain="example.com",
            zone_id=3,
            sha256=sha256,
            file_identity=file_identity,
        )

    def test_upsert_preserves_note(self) -> None:
        receipt_id = self.add_receipt()
        self.repository.update_note(receipt_id, "Read before Friday")
        second_id = self.add_receipt()

        receipt = self.repository.get(second_id)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertEqual(receipt_id, second_id)
        self.assertEqual(receipt.note, "Read before Friday")

    def test_searches_notes_and_domains(self) -> None:
        receipt_id = self.add_receipt()
        self.repository.update_note(receipt_id, "expense report")

        self.assertEqual(len(self.repository.list("expense")), 1)
        self.assertEqual(len(self.repository.list("example.com")), 1)
        self.assertEqual(self.repository.list("missing"), [])

    def test_duplicate_filter_uses_sha256(self) -> None:
        self.add_receipt()
        self.add_receipt(r"C:\Downloads\guide (1).pdf")

        duplicates = self.repository.list(filter_name="duplicates")
        self.assertEqual(len(duplicates), 2)
        self.assertTrue(all(item.is_duplicate for item in duplicates))

    def test_delete_removes_only_receipt(self) -> None:
        receipt_id = self.add_receipt()
        self.repository.delete(receipt_id)

        self.assertIsNone(self.repository.get(receipt_id))

    def test_download_inbox_disposition_can_be_updated_and_filtered(self) -> None:
        inbox_id = self.add_receipt()
        remove_id = self.add_receipt(r"C:\Downloads\old-installer.exe")

        self.repository.update_disposition(remove_id, "remove")

        self.assertEqual(
            [item.id for item in self.repository.list(filter_name="inbox")], [inbox_id]
        )
        self.assertEqual(
            [item.id for item in self.repository.list(filter_name="remove")], [remove_id]
        )

    def test_changed_file_keeps_old_receipt_as_replaced_version(self) -> None:
        old_id = self.add_receipt()
        self.repository.update_note(old_id, "old installer")
        new_id = self.add_receipt(
            file_size=2048,
            modified_at="2026-07-30T10:00:00+00:00",
            file_identity="1:2",
            sha256="new-hash",
        )

        self.assertNotEqual(old_id, new_id)
        old = self.repository.get(old_id)
        new = self.repository.get(new_id)
        assert old is not None and new is not None
        self.assertFalse(old.is_current)
        self.assertTrue(old.is_missing)
        self.assertEqual(old.note, "old installer")
        self.assertTrue(new.is_current)
        self.assertEqual(new.note, "")
        self.assertEqual(
            [item.id for item in self.repository.list(filter_name="replaced")], [old_id]
        )

    def test_missing_reconciliation_only_affects_selected_folder(self) -> None:
        missing_id = self.add_receipt(r"C:\Downloads\gone.pdf")
        other_id = self.add_receipt(r"C:\Elsewhere\keep.pdf")

        changed = self.repository.mark_missing_in_folder(
            Path(r"C:\Downloads"), set(), recursive=False
        )

        self.assertEqual(changed, 1)
        missing = self.repository.get(missing_id)
        other = self.repository.get(other_id)
        assert missing is not None and other is not None
        self.assertTrue(missing.is_missing)
        self.assertFalse(other.is_missing)

    def test_v1_database_is_migrated_without_losing_notes(self) -> None:
        self.temporary_directory.cleanup()
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "legacy.db"
        with closing(sqlite3.connect(database_path)) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE receipts (
                    id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    file_name TEXT NOT NULL, file_size INTEGER NOT NULL,
                    modified_at TEXT NOT NULL, first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL, host_url TEXT, referrer_url TEXT,
                    source_domain TEXT, zone_id INTEGER, sha256 TEXT,
                    note TEXT NOT NULL DEFAULT '', is_missing INTEGER NOT NULL DEFAULT 0
                );
                INSERT INTO receipts VALUES (
                    1, 'C:\\Downloads\\old.pdf', 'old.pdf', 12, 'modified',
                    'first', 'last', NULL, NULL, NULL, 3, 'hash', 'keep me', 0
                );
                """
            )

        migrated = ReceiptRepository(database_path)
        receipt = migrated.get(1)

        assert receipt is not None
        self.assertEqual(receipt.note, "keep me")
        self.assertTrue(receipt.is_current)
        self.assertIsNone(receipt.file_identity)

    def test_v2_database_receives_default_download_inbox_state(self) -> None:
        self.temporary_directory.cleanup()
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "version-two.db"
        with closing(sqlite3.connect(database_path)) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE receipts (
                    id INTEGER PRIMARY KEY, path TEXT NOT NULL COLLATE NOCASE,
                    file_name TEXT NOT NULL, file_size INTEGER NOT NULL,
                    modified_at TEXT NOT NULL, first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL, host_url TEXT, referrer_url TEXT,
                    source_domain TEXT, zone_id INTEGER, sha256 TEXT,
                    file_identity TEXT, note TEXT NOT NULL DEFAULT '',
                    is_missing INTEGER NOT NULL DEFAULT 0,
                    is_current INTEGER NOT NULL DEFAULT 1, superseded_at TEXT
                );
                INSERT INTO receipts VALUES (
                    1, 'C:\\Downloads\\v2.pdf', 'v2.pdf', 12, 'modified',
                    'first', 'last', NULL, NULL, NULL, 3, 'hash', '1:1',
                    'note', 0, 1, NULL
                );
                """
            )

        migrated = ReceiptRepository(database_path)
        receipt = migrated.get(1)

        assert receipt is not None
        self.assertEqual(receipt.disposition, "inbox")
        self.assertEqual(receipt.note, "note")


if __name__ == "__main__":
    unittest.main()
