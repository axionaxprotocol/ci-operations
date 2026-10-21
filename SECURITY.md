# Security

CI Operations is a local Windows application, not an internet-facing service.

## Reporting a problem

Do not include real tokens, encrypted settings, clipboard contents, private repository names, live API responses, screenshots of private job data, or personal machine paths in public issues.

For a suspected vulnerability, contact the repository maintainer privately through their GitHub profile before sharing sensitive details. Use synthetic data and describe the affected version and reproduction steps.

## Boundaries and limitations

- Windows DPAPI protects saved credentials for the current Windows user. It does not protect against malicious software running as that user, an administrator, or a compromised OS.
- The desktop API is loopback-only and session-gated. The optional browser-only server does not use that gate and must not be exposed to untrusted networks.
- The 3D execution volume is drawn by a local WebGL2 renderer served from the same loopback origin, under the same session gate and content-security policy as the dashboard. It makes no external request and loads no third-party script.
- The application does not implement SSO, role-based access, audit logs, or remote multi-user access.
- Job history is stored in an unencrypted SQLite database at `%LOCALAPPDATA%\CIOperations\history.db`. It holds job metadata only — repository names, workflow names, step names, conclusions and timings — and never a token. Entries older than the retention window are pruned automatically. Anyone who can read the current user's profile can read this file.
- Failure notifications are raised through the Windows notification platform. The notification text contains the workflow, job and repository names, and the job URL.
- Executables built locally are unsigned. Verify the source and build environment before distributing them.
- GitHub token scopes should be limited to the repositories and read permissions needed for monitoring. Revoke and replace any token accidentally disclosed.
- Never commit `.env` files, saved credentials, live snapshots, private CI screenshots, build logs, or local runtime directories.

No real credentials are required to run automated tests. Native clipboard tests use a synthetic provider rather than reading or overwriting the user's OS clipboard.
