# Changelog

All notable changes to dash are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Service favicons: each service shows its own icon, fetched server-side from the
  service itself (offline-safe on a LAN) and cached, with a colored-initial fallback
  and a status badge.
- Export / import links as JSON (gear menu → Data). Export downloads a file; import
  adds links from a file and skips duplicates. New endpoint `POST /api/links/import`.

## [0.1.2] - 2026-06-29

### Added
- Tag picker on the Add/Edit service form: click existing tags to toggle them, or
  type new ones (Enter/comma to commit, Backspace removes the last).

### Project
- Repo hardening: MIT license, CONTRIBUTING/SECURITY docs, issue/PR templates, a CI
  workflow (build + smoke test + gitleaks), and Dependabot.

## [0.1.1] - 2026-06-26

### Added
- Installer records the install directory (and whether `sudo` is needed) in the
  in-app update command, so the "update available" notice shows the exact command.
- Installer offers to add the user to the `docker` group; re-running it pulls the
  latest image.
- `uninstall.sh` — stops/removes dash (keeps data by default; `--purge` / `--rmi`).

### Fixed
- Installer no longer re-prompts for values passed as flags; `-y` now means
  "yes to all" instead of "take the default".

## [0.1.0] - 2026-06-26

### Added
- Initial release: FastAPI + SQLite + vanilla-JS dashboard served over HTTPS with a
  self-signed certificate.
- Server-side `tcp`/`http` status checks with latency and DNS discovery.
- Tiles/rows views, search, tag filters, and an Auto/Dark/Light theme.
- User accounts (pbkdf2) with first-run admin setup and admin user management.
- Optional GitHub-release update notifications.
- Docker + Compose, a one-line installer, and a GHCR publish workflow.

[Unreleased]: https://github.com/preston-peterson/dash/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/preston-peterson/dash/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/preston-peterson/dash/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/preston-peterson/dash/releases/tag/v0.1.0
