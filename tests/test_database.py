from __future__ import annotations

import tempfile
import unittest
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
    ) -> int:
        return self.repository.upsert(
            path=path,
            file_name=Path(path).name,
            file_size=1024,
            modified_at="2026-07-29T10:00:00+00:00",
            seen_at="2026-07-29T10:01:00+00:00",
            host_url="https://cdn.example.com/guide.pdf",
            referrer_url="https://example.com/guides",
            source_domain="example.com",
            zone_id=3,
            sha256=sha256,
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


if __name__ == "__main__":
    unittest.main()
