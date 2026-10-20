# Contributing

Thanks for helping improve CI Operations. Keep changes small, focused, and reviewed.

## Development setup (Windows)

```powershell
py -3.12 -m venv .venv-desktop
.venv-desktop/Scripts/python.exe -m pip install --upgrade pip
.venv-desktop/Scripts/python.exe -m pip install -r requirements-desktop.txt
```

The application also runs without the desktop dependencies for the browser-only mode using Python 3.10 or later.

## Test-driven changes

1. Write a failing test that reproduces the behavior or regression.
2. Confirm it fails for the expected reason.
3. Implement the smallest change that makes it pass.
4. Run the full suite before opening a pull request.

```powershell
.venv-desktop/Scripts/python.exe -m unittest discover -p 'test_*.py' -v
node --test test_frontend.cjs
.venv-desktop/Scripts/python.exe -m ruff check .   # optional lint
```

Some tests require Windows, tkinter, winreg, and DPAPI support. Tests must never read or overwrite the real OS clipboard, encrypted settings, live CI data, or repository screenshots. Use synthetic values such as `TEST-ONLY-NOT-REAL`.

## Pull requests

- Work on a branch and open a pull request against `main`; do not push directly to `main`.
- Describe the problem, the approach, and the tests you ran.
- Keep unsolicited refactors out of bug fixes and security changes.
- Update `CHANGELOG.md` under `Unreleased` for user-visible changes.
- Do not commit credentials, private repository names, live job snapshots, diagnostic reports, logs, or build artifacts.

## Security-sensitive changes

Changes to credential storage, token handling, HTTP boundaries, installers, or release signing require an explicit security note in the pull request. Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md) rather than in a public issue.

## Commit messages

Use short imperative subjects, for example `fix: reject malformed session cookies`. Squash merges keep history readable.
