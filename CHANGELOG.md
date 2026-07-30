# Changelog

All notable changes to this project will be documented here.

## [0.1.0] - 2026-07-29

### Added

- Read `HostUrl`, `ReferrerUrl`, and `ZoneId` from Windows download metadata.
- Scan a Downloads folder and preserve receipts in local SQLite storage.
- Search and filter receipts by file, source, date, and note.
- Add personal notes and open the original file, folder, or source page.
- Detect duplicate files with SHA-256 fingerprints up to 200 MB.
- Build a standalone Windows executable from a version tag on GitHub.
