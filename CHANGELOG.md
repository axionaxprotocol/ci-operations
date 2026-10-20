# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.9] - 2026-10-20

### Fixed

- "GitHub settings" did nothing. The dashboard menu item relaunched the app with `--check-update` instead of `--configure`, so the settings form never opened and the app exited silently.
- The settings form is now reachable while the dashboard is running: the dashboard window and the settings window use separate named locks, so a settings session is no longer refused with "CI Operations is already running".
- Changing the token or repositories from the Start menu "GitHub Settings" shortcut now applies to the running dashboard within a few seconds instead of requiring a restart.
- The dashboard menu opens the settings form in a separate process, so the Tk window always gets a main thread and the dashboard stays open while settings are edited.


## [1.0.8] - 2026-10-20

### Added

- Auto-update verifies the downloaded installer against the release's `SHA256SUMS.txt` and refuses to run unverified or mismatched bytes.
- `parse_checksums()` and `sha256_file()` helpers with unit tests.


## [1.0.7] - 2026-10-20

### Fixed

- In-app updates aborted with installer exit code 5 because Inno Setup tried to close the running application that was waiting on it. The updater now downloads the installer, schedules it through a detached helper, exits, and lets the helper install and relaunch the app.


## [1.0.6] - 2026-10-20

### Added

- Background release check at startup; the dashboard footer now shows "Update available: vX.Y.Z" when a newer release exists.
- `latest_release_version()` helper with tests covering success, failure, and no-update cases.


## [1.0.5] - 2026-10-20

### Fixed

- Auto-update failed with "name 'urllib' is not defined" because the updater used `urllib` without importing it. The module is now imported explicitly, so update checks and silent upgrades work.


## [1.0.4] - 2026-10-20

### Changed

- Auto-update now reports a distinct "update installed" result and relaunches the application after a successful silent upgrade.
- Installer wait timeout increased to 180 seconds for slower machines.


### Added

- In-app "Check for updates" menu action and visible version label in the dashboard footer.
- Documentation, contribution, and security processes; MIT license.
- Automated dependency updates and static analysis workflows.
- Diagnostic logging that never records credentials, request headers, or exception locals.

## [1.0.3] - 2026-10-20

### Added

- Automatic update check on startup against the latest GitHub release, with silent installer download and apply.
- "Check for updates" item in the application menu, with the running version shown in the menu title and dashboard footer.

## [1.0.2] - 2026-10-20

### Added

- Native Paste button, right-click Paste menu, and layout-independent Ctrl+V support for the token field.
- Workflow and PowerShell helpers for building, testing, and packaging locally.

### Changed

- English-only application interface, light theme, and 14px minimum dashboard text.
- Timestamps follow the viewer's system timezone instead of a hardcoded zone.
- Shared source no longer contains private repository defaults.

### Fixed

- Session cookie comparisons reject malformed input with a clean 401 response.
- Authorization headers are not forwarded across HTTP redirects.

## [1.0.1] - 2026-10-20

### Changed

- English-native setup form, menus, and error messages.

## [1.0.0] - 2026-10-20

### Added

- Loopback-only operations dashboard for GitHub Actions runners, pending jobs, and recent executions.
- Windows desktop application with Windows DPAPI-protected settings, optional startup, and a per-user installer.
