# CI Operations

[![Windows tests](https://github.com/axionaxprotocol/ci-operations/actions/workflows/ci.yml/badge.svg)](https://github.com/axionaxprotocol/ci-operations/actions/workflows/ci.yml)
[![CodeQL](https://github.com/axionaxprotocol/ci-operations/actions/workflows/codeql.yml/badge.svg)](https://github.com/axionaxprotocol/ci-operations/actions/workflows/codeql.yml)
[![Latest release](https://img.shields.io/github/v/release/axionaxprotocol/ci-operations)](https://github.com/axionaxprotocol/ci-operations/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A local Windows desktop console for monitoring GitHub Actions runners and jobs. Includes first-run token setup, encrypted credential persistence, and a light, readable operations dashboard.

![CI Operations dashboard](docs/dashboard.png)

## Features

- Native GitHub setup with masked token entry, a Paste button, Ctrl+V across keyboard layouts, and a right-click Paste menu.
- Validate repository access before saving credentials.
- Remember settings using Windows DPAPI, bound to the current Windows account.
- Optional launch at Windows sign-in; off until explicitly selected.
- Runner fleet, active executions, pending jobs, repository health, a 60-minute execution timeline, and recent job results.
- Durable local job history in SQLite, so reliability data survives restarts. Stored at `%LOCALAPPDATA%\CIOperations\history.db` and never uploaded.
- A Reliability panel with success rate, failure count, median and 95th-percentile duration, and the steps that fail most often.
- An interactive 3D execution volume, drawn as an isometric technical illustration. Time runs along the X axis, each repository sits on its own slab, and every job is a cable that arcs from its start to its end, coloured by its result. Drag to orbit, scroll to zoom, shift-drag to pan, hover a job for its details.
- The 3D view is drawn with hand-written WebGL2 and no third-party library, so the packaged application stays self-contained and never reaches the network. Where WebGL2 is unavailable the dashboard falls back to the flat timeline and tables.
- History windows of 24 hours, 7 days, 30 days, or everything stored, plus CSV export of the selected window.
- Windows toast notifications when a job fails, so a red build is noticed without watching the window. Toggle them with **Notify me when a job fails** in settings.
- Adaptive polling that slows down when the GitHub rate limit runs low and speeds up while a job is running.
- Repository filtering and search, English application text, light theme, and 14px minimum dashboard text.
- Private WebView2 window backed by a loopback-only server on a random port with a session gate.
- An optional standard-library-only web server for development or local browser use.

No private repository names, live snapshots, user tokens, or local credential files are included in this repository.

## Windows desktop: build and install

### Requirements

- Windows x64; Windows 11 is recommended.
- Python 3.12 for building. The packaged application includes Python, so end users do not need a separate Python installation.
- Microsoft Edge WebView2 Runtime and .NET Framework 4.6.2 or later.
- Inno Setup 6 to build the installer. Check the packaging tool's licensing terms for your intended use.
- Node.js 24 or later to run frontend tests only.

From the project directory in PowerShell:

```powershell
py -3.12 -m venv .venv-desktop
.venv-desktop/Scripts/python.exe -m pip install -r requirements-desktop.txt
.venv-desktop/Scripts/python.exe build_desktop.py
```

The build produces:

- `dist/CI-Operations/CI-Operations.exe`: application and its companion runtime directory.
- `dist/CI-Operations-Setup.exe`: per-user installer with Desktop and Start menu shortcuts.

The same build runs in CI on every push and pull request, and tag pushes publish a verified installer release with a SHA-256 checksum and build-provenance attestation. Build products are intentionally excluded from Git. This repository does not require users to share credentials to build or test it. Locally built executables are unsigned and may trigger Windows SmartScreen.

### First launch

1. Open **CI Operations**.
2. Enter a fine-grained GitHub PAT and your repositories as comma-separated `owner/repo` names.
3. Use **Paste** if the keyboard shortcut is unavailable. Paste replaces the token field and trims copied leading/trailing whitespace.
4. Optionally select **Launch automatically when I sign in to Windows** and **Notify me when a job fails**.
5. Select **Save and open dashboard**.

On later launches, saved credentials are reused. An expired or revoked token must be replaced. Open **Application > GitHub settings** to change settings or forget credentials.

When a job fails, a Windows toast names the workflow and repository. Windows Focus Assist can suppress toasts; the dashboard shows the same failures in the Reliability panel regardless.

### Token permissions

Grant access only to the repositories you want to monitor:

| Permission | Access | Purpose |
| --- | --- | --- |
| Actions | Read | Workflow runs and jobs |
| Metadata | Read | Basic repository access |
| Administration | Read, optional | Registered runners, including idle/offline runners |

Without Administration access, runners can still be inferred from active jobs; the registered runner inventory may be incomplete. Organization approval and access policies may apply.

## Security model

- Encrypted settings are stored at `%LOCALAPPDATA%\CIOperations\settings.dat` using current-user Windows DPAPI. No plaintext-token fallback is used.
- Tokens are entered in native controls, not dashboard JavaScript, browser localStorage, URLs, or command-line arguments.
- Authorization headers are not forwarded across HTTP redirects. Configure the current name of a renamed private repository instead of relying on redirects.
- The desktop server binds to `127.0.0.1` on an ephemeral port and requires a random session cookie before returning the dashboard or API. Host and Origin are checked.
- GitHub job metadata is escaped before HTML rendering, and job links must use HTTPS.
- Startup is per-user and opt-in. Uninstall removes the app's saved credentials and startup value.

This is a local-account security boundary, **not** a defense against malware running as the same Windows user or an administrator. It is not an internet-facing service, enterprise SSO system, audited monitoring platform, or durable job-history database. See [SECURITY.md](SECURITY.md).

## Optional local web server

The browser-only mode uses the Python standard library. It does **not** use the desktop token setup, encrypted settings, or desktop session gate.

PowerShell:

```powershell
$env:GITHUB_TOKEN = "<your-token>"
$env:REPOS = "owner/repo,owner/another-repo"
python ci_dashboard.py
```

Bash:

```sh
GITHUB_TOKEN='<your-token>' REPOS='owner/repo,owner/another-repo' python ci_dashboard.py
```

Open `http://127.0.0.1:8787`. Keep tokens out of source control and shared shell history.

| Variable | Default | Purpose |
| --- | --- | --- |
| `GITHUB_TOKEN` | unset | GitHub token for the web-only collector |
| `REPOS` | `owner/repo` placeholder | Comma-separated repositories; replace before use |
| `HOST` | `127.0.0.1` | Bind address; do not expose private CI data to a network |
| `PORT` | `8787` | Browser-only HTTP port |
| `POLL` | `20` | GitHub poll interval in seconds, minimum 5 |
| `STATE_FILE` | unset | Load a local JSON snapshot without polling GitHub |

The desktop collector uses a 30-second polling interval; the dashboard fetches the current local state every 10 seconds. Refresh retrieves existing local state, not an immediate new GitHub poll. Conditional requests and pagination are supported, but API rate limits can still be reached on busy repositories.

For snapshot mode, set `STATE_FILE` to a JSON file containing `runners` and `jobs` arrays and an ISO-8601 `updated` timestamp with timezone. Timers and the timeline use that timestamp. Do not commit live private snapshots.

## Understanding the metrics

- **Online capacity**: online runner records divided by runner records in the current selection, including runners inferred from active jobs. Shared runner names across repositories are counted separately; this is not a physical-host or CPU utilization metric.
- **Active executions** and **Queue depth**: matching running and pending jobs. A waiting job may be awaiting approval or another condition, not just a runner.
- **Observed success**: successful completed jobs divided by all completed jobs retrieved for the selection, excluding skipped jobs but including cancelled/neutral jobs. It is not an SLA or a complete daily statistic.
- **Repository health**: runner availability and active/failed jobs in the retrieved data. Failed includes failure, timed_out, action_required, and startup_failure.
- **Execution timeline**: jobs with runner names and valid start times within the last 60 minutes; overlapping executions use separate tracks.
- **Reliability**: success rate, failure count, median duration, and 95th-percentile duration over the locally stored history for the selected window. This covers only jobs seen while the app was running, so it is not a complete historical record of the repository.
- **Most frequent failing steps**: the steps GitHub reported as failed, ranked by how often they broke. Steps are only recorded for jobs the app observed. Each recorded step is counted once per job, not once per poll, so the ranking reflects distinct failing jobs.
- **3D execution volume**: the same executions the timeline shows, placed in space. Time runs left to right across the 60-minute window, each repository gets its own slab, and each runner a row within it. A cable is one job: it starts where the job started, ends where it finished, and its colour is the result. The volume is an exploration aid: the timeline and results table remain the precise-reading surfaces.

Connection failures, incomplete API data, and stale data are shown separately from offline runner status. Data older than 90 seconds is marked stale. The collector retrieves active workflows plus recently created runs; this is not a complete historical archive.

## Releases

Tagged releases (`v*`) are built on GitHub-hosted Windows runners from the tagged commit. Each release includes `CI-Operations-Setup.exe` and `SHA256SUMS.txt`. Verify a download with:

```powershell
Get-FileHash .\CI-Operations-Setup.exe -Algorithm SHA256
gh attestation verify .\CI-Operations-Setup.exe --repo axionaxprotocol/ci-operations
```

Releases are signed only when the maintainer configures the `WINDOWS_SIGNING_CERTIFICATE` and `WINDOWS_SIGNING_PASSWORD` repository secrets. Unsigned installers trigger SmartScreen warnings; the release page states the signing status.

## Tests

On Windows, using the packaging virtual environment:

```powershell
.venv-desktop/Scripts/python.exe -m unittest discover -p 'test_*.py' -v
node --test test_frontend.cjs
```

Tests use synthetic credentials and mocked GitHub responses. Native clipboard tests replace the clipboard provider without reading or overwriting the OS clipboard. Some tests require Windows DPAPI, winreg, and tkinter.

The executable also exposes diagnostic modes that use isolated synthetic data and never load the user's saved token:

```powershell
CI-Operations.exe --self-test-report security-report.json
CI-Operations.exe --setup-smoke-report setup-report.json
CI-Operations.exe --ui-smoke-report webview-report.json
```

These modes exercise credential encryption, native setup controls, bundled resources, and the installed WebView2 window. They do not validate a real token or simulate a PC reboot.

## Project layout

| File | Role |
| --- | --- |
| `ci_dashboard.py` | GitHub collector and optional browser-only server |
| `index.html` | Dependency-free operations dashboard |
| `fleet3d.js` | WebGL2 execution-volume renderer: scene layout, camera, picking |
| `desktop_app.py` | Desktop launcher, single-instance lifecycle, application menu |
| `desktop_setup.py` | Native setup, validation, paste support, optional startup |
| `desktop_store.py` | Current-user DPAPI encrypted settings |
| `desktop_service.py` | Session-gated loopback adapter |
| `desktop_history.py` | Local SQLite history of finished jobs and their steps |
| `desktop_alerts.py` | Detects newly failed jobs from the recorded history |
| `desktop_notify.py` | Windows toast notifications, with no third-party dependency |
| `build_desktop.py`, `installer.iss` | Windows application and installer packaging |

## License

[MIT](LICENSE). Third-party dependencies retain their own licenses. Public visibility alone does not grant a general license to reuse or redistribute the code. Third-party dependencies retain their respective licenses; review their terms before distributing packaged builds.
