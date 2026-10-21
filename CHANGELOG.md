# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.3.1] - 2026-10-21

### Fixed

- Relaunching straight after an auto-update could fail to create the dashboard window with `RPC_E_CALL_REJECTED` (`0x8001010d`). The old process is terminated by the installer, but its WebView2 COM server can still be registered a moment later, so the new window was initialised against a COM object that was on its way out. The update helper now waits a few seconds between installing and relaunching, and the application recovers instead of logging a fatal exception.

## [1.3.0] - 2026-10-20

### Added

- An interactive 3D execution volume, reachable from **3D volume** in the navigation. Time runs along the X axis, each repository occupies its own depth plane, and each runner gets a row inside that plane. Every job is a bar whose length is its duration and whose colour is its result, so a cluster of failures on one repository is visible as a shape rather than a number.
- The camera can be orbited by dragging, zoomed with the scroll wheel, and panned with shift-drag. Hovering or clicking a bar shows the job, its repository, its runner and its result. **Reset view** returns to the framed overview, and the arrow keys, `+`, `-` and `Home` do the same from the keyboard.
- The renderer is hand-written WebGL2 with no third-party library, so the packaged application stays self-contained and never makes an external request. The engine is served from the same loopback origin under the same session gate and the same content-security policy as the dashboard.
- Axis labels for the time ticks and the repository planes are drawn over the canvas, so the scene stays readable without a legend to decode.

### Fixed

- A separator inside a repository or runner name could make two different jobs collide onto the same row. Job and row keys are now built with `JSON.stringify`, which cannot collide.

## [1.2.1] - 2026-10-20

### Fixed

- The new notification checkbox made the setup form taller than its window, which clipped the **Forget credentials**, **Cancel** and **Save and open dashboard** buttons. The window is taller and the smoke test now reports the position of the action row so a clipped button fails the build instead of shipping.

## [1.2.0] - 2026-10-20

### Added

- Windows toast notifications when a job fails. The notification names the workflow, the job and the repository, and includes a link to the failing run. The toast is raised through the Windows notification platform, so no new dependency is added.
- A **Notify me when a job fails** toggle in the settings window. Notifications are on by default and can be switched off without uninstalling.
- Adaptive polling. The collector reads the remaining GitHub rate limit from every response and lengthens the poll interval when the budget is thin, so the app stops itself from exhausting the limit. The current interval is shown in the dashboard footer.

### Fixed

- Job steps were recorded once per poll instead of once per job, so a single failure was counted repeatedly and the "most frequent failing steps" ranking was inflated. The step table is now keyed on the job and step number, and existing databases are migrated to the corrected shape. The failing-step counts published with 1.1.0 were therefore higher than the real numbers and are corrected here.
- Job history was never pruned. The history store now prunes aged entries during the watch cycle, so the database no longer grows without bound.
- The history endpoint returned every stored job on every request. It now returns a bounded page of 50 jobs; the reliability summary still covers the full window.
- The collector issued four workflow-run requests per repository per poll. It now issues one, which brings a two-repository setup from 5,760 to 5,040 requests per hour against GitHub's 5,000/hour limit, and the adaptive interval covers the remaining margin.

## [1.1.0] - 2026-10-20

### Added

- Durable local job history in SQLite. Finished jobs and the steps inside them are recorded as they are observed, so reliability data survives an application restart. The database stays at `%LOCALAPPDATA%\CIOperations\history.db` and is never uploaded.
- A Reliability panel showing success rate, failure count, median duration, and 95th-percentile duration for the selected window.
- A breakdown of the steps that fail most often, so the usual cause of a red build is visible without opening GitHub.
- History windows of 24 hours, 7 days, 30 days, or everything stored.
- CSV export of the selected history window.

### Fixed

- A request that was rejected for using a mutating HTTP method could reset the connection instead of returning a clean 405 response. The request body is now read before the socket is closed.


## [1.0.12] - 2026-10-20

### Fixed

- Removing the saved token from the settings window left the running dashboard polling with the old token. The dashboard now drops the credentials and asks the user to configure the app again.


## [1.0.11] - 2026-10-20

### Fixed

- Version comparison used raw string ordering, so `1.0.10` was treated as older than `1.0.9` and the auto-update never offered it. Versions are now compared numerically in the updater, the startup probe, and the dashboard footer.
- The settings integration test no longer depends on a settings file or a running application on the machine executing it.


## [1.0.10] - 2026-10-20

### Fixed

- The settings watcher now starts only for live dashboard sessions, so headless test runs never touch the saved credentials file.
- The settings integration test no longer depends on a settings file existing on the machine running it.


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
