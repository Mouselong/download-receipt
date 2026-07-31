from __future__ import annotations

import unittest

from download_receipt.provenance import (
    domain_from_url,
    parse_zone_identifier,
    safe_source_url,
)


class ZoneIdentifierTests(unittest.TestCase):
    def test_parses_browser_urls_and_zone(self) -> None:
        result = parse_zone_identifier(
            """[ZoneTransfer]
ZoneId=3
ReferrerUrl=https://example.com/downloads?id=10%20off
HostUrl=https://cdn.example.com/files/manual.pdf
"""
        )

        self.assertEqual(result.zone_id, 3)
        self.assertEqual(result.referrer_url, "https://example.com/downloads?id=10%20off")
        self.assertEqual(result.host_url, "https://cdn.example.com/files/manual.pdf")

    def test_malformed_payload_returns_empty_result(self) -> None:
        result = parse_zone_identifier("not an ini document")

        self.assertIsNone(result.zone_id)
        self.assertIsNone(result.host_url)

    def test_domain_is_normalized(self) -> None:
        self.assertEqual(domain_from_url("https://www.Example.COM/path"), "example.com")

    def test_only_http_and_https_sources_are_openable(self) -> None:
        self.assertEqual(
            safe_source_url(" https://example.com/file "), "https://example.com/file"
        )
        self.assertIsNone(safe_source_url("file://server/share/file.exe"))
        self.assertIsNone(safe_source_url("ms-settings:privacy"))
        self.assertIsNone(safe_source_url("javascript:alert(1)"))

    def test_domain_rejects_non_web_protocols(self) -> None:
        self.assertIsNone(domain_from_url("file://server/share/file.exe"))
        self.assertIsNone(domain_from_url("not-a-url"))
        self.assertIsNone(domain_from_url(None))


if __name__ == "__main__":
    unittest.main()
