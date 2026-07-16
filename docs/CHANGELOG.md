# Changelog

## 0.1.1 - Organized project release

- Moved the Python package to `src/tmhi_watchdog/`.
- Removed duplicate root-level Python modules and accidental local files.
- Changed the recommended Compose deployment to a Docker named volume.
- Added a clearer installation and troubleshooting guide.
- Added project-structure and migration documentation.
- Preserved dashboard, API, watchdog, and gateway behavior.

All notable changes to this project will be documented here.

## [Unreleased]

### Added

- GitHub Actions tests and Docker build validation.
- Automated multi-architecture publishing to GitHub Container Registry.
- Issue and pull-request templates.

## [0.1.0] - 2026-07-16

### Added

- Multi-endpoint internet connectivity checks.
- Sustained-outage detection.
- Unified T-Mobile gateway API authentication and reboot support.
- Startup grace, post-reboot grace, cooldown, and 24-hour reboot limits.
- SQLite-backed event and reboot history.
- FastAPI status, event, test, and manual reboot endpoints.
- Docker and Docker Compose deployment files.
