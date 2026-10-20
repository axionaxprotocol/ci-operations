# CI Operations — "สุดยอด" roadmap to v1.2.0

> Plan date: 2026-10-20 · Repo: `C:\Users\PUKEE\ci-dashboard` · Branch: `main` · Current released version: **v1.1.0**

---

## Goal

Turn CI Operations from a live dashboard into a console you can leave running — fix the three
correctness bugs that make its headline numbers wrong today, stop the API polling from
exhausting the GitHub rate limit, and add Windows failure notifications so a red build is
noticed without watching the screen.

---

## Current context / assumptions

**What the app is today (v1.1.0, released and installed on this machine).**

| Module | Role |
|---|---|
| `ci_dashboard.py` | GitHub collector + optional stdlib-only browser server |
| `desktop_service.py` | Session-gated loopback HTTP adapter (`127.0.0.1`, random port, cookie gate) |
| `desktop_history.py` | SQLite history of finished jobs and their steps (`%LOCALAPPDATA%\CIOperations\history.db`) |
| `desktop_app.py` | Launcher, single-instance locks, application menu, auto-update |
| `desktop_setup.py` | Native Tk setup form, token validation, paste support |
| `desktop_store.py` | DPAPI-encrypted settings for the current Windows user |
| `index.html` | Dependency-free dashboard (one file, inline CSS + JS) |

**Verified facts about the current build (measured, not assumed):**

- Tests: **86 Python** (`.venv-desktop/Scripts/python.exe -m unittest discover -p 'test_*.py'`) + **23 frontend** (`node --test test_frontend.cjs`). All pass.
- CI: `.github/workflows/ci.yml` runs the Python suite, the Node suite, builds the app with
  PyInstaller, then smoke-tests the packaged `.exe` (`--self-test-report`, `--setup-smoke-report`,
  `--ui-smoke-report`). `codeql.yml`, `release.yml`, `stale.yml`, `dependabot.yml` also exist.
- Release flow: tag `v*` → `release.yml` builds, self-tests, optionally signs, writes
  `SHA256SUMS.txt`, attests provenance, publishes. Auto-update downloads, verifies SHA-256,
  and installs through a detached helper (verified working 1.0.12 → 1.1.0).
- `pyproject.toml` pins `pywebview==6.2.1`; `requirements-desktop.txt` pins `pywebview` and
  `pyinstaller` only. **No notification library is installed.**
- WinRT `Windows.UI.Notifications.ToastNotificationManager` **is resolvable on this machine**
  (verified via PowerShell `[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime]` → `System.RuntimeType`).
- `winsound.MessageBeep` is available in the stdlib.
- `webview` exposes **no** notification or tray API (`webview/__init__.py`, `webview/window.py` searched — zero matches).

**Three bugs found while investigating (these must be fixed first — they make shipped numbers wrong):**

1. **Steps are duplicated on every poll.** `desktop_history.py:133` uses `INSERT INTO steps`
   (not `INSERT OR REPLACE`), so each 30-second poll re-appends every step of every job.
   Measured on the live database: **3,743 step rows for 34 jobs, 171 distinct `(job_key, number)`
   pairs — a 21.9× inflation.** The "Playwright 28 failed" figure in the v1.1.0 release notes is
   therefore inflated; the real count is lower. The `jobs` table uses `INSERT OR REPLACE` and is
   correct, so only `steps` is affected.
2. **Nothing ever prunes the history.** `HistoryStore.prune()` exists (`desktop_history.py:139`)
   and is covered by a test, but **no production code path calls it**. `history.db` is already
   790 KB after one session and grows without bound; `steps` duplicates make it far worse.
3. **`/api/history` returns every stored job, unbounded.** `history_payload()` calls
   `export_json(since=since)` with `limit=100000`. As history grows, this JSON grows without
   bound and is re-fetched by the dashboard every time the window selector changes.

**One operational problem found:**

4. **Polling exceeds the GitHub rate limit.** `_collect()` (`ci_dashboard.py:99`) issues
   `1 runners + 4 runs-list + 1 jobs-per-run` requests per repo per poll. Measured on real
   data (2 repos, 19 recent runs): **48 calls per 30-second poll = 5,760 calls/hour against
   GitHub's 5,000/hour authenticated limit — over budget before the day is out.** The
   `_etag` cache softens this only when the response is unchanged.

**Constraints the plan respects:**

- Stdlib-only for the browser server (`ci_dashboard.py` must keep working with no deps).
- The dashboard stays a single dependency-free `index.html`.
- The dashboard remains **read-only** against GitHub — the session gate rejects every mutating
  HTTP method and the token is scoped to read permissions. Nothing here may weaken that.
- Credentials never reach dashboard JavaScript, localStorage, URLs, or argv.

---

## Architecture / proposed approach

Three independent layers, landed in order, each shippable on its own:

**Layer 1 — correctness (v1.1.1).** Make `steps` idempotent by keying it on
`(job_key, number)` with `INSERT OR REPLACE`, prune on a schedule inside the existing
watch thread, and bound the history endpoint with an explicit `limit`. This fixes wrong
numbers and unbounded growth without changing any UI.

**Layer 2 — sustainable polling (v1.1.2).** Move run-list discovery into a single
per-repo request instead of four status-scoped ones, and make the poll interval adaptive:
back off when the remaining rate limit is low, poll faster when a job is running. GitHub
exposes `X-RateLimit-Remaining` on every response, and the collector already reads it into
`STATE['rate']` — the remaining work is to use it.

**Layer 3 — failure notifications (v1.2.0).** Detect newly-failed jobs by comparing against
the history database (which already knows every job key ever seen), then raise a Windows
toast through the WinRT `ToastNotificationManager` via `ctypes` + PowerShell, or a tray icon.
A Windows toast is the right target: it survives the app being in the background, and it is
what "I don't want to stare at the dashboard" actually means.

---

## Step-by-step tasks

### Task 1 — Fix duplicated step rows (correctness, ship in v1.1.1)

The `steps` table has no uniqueness constraint, so every poll appends a fresh copy of every
step. Key it on `(job_key, number)` and replace on conflict.

**Step 1.1 — write the failing test**

Create `C:\Users\PUKEE\ci-dashboard\test_desktop_history_dedup.py`:

```python
"""Steps must be recorded once per job, not once per poll."""
import tempfile
import unittest
from pathlib import Path

import desktop_history


def job(step_name='install'):
    return {
        'repo': 'o/r', 'run_id': 1, 'job_id': 10, 'name': 'build', 'workflow': 'CI',
        'status': 'completed', 'conclusion': 'failure', 'started': '2026-10-20T10:00:00Z',
        'completed': '2026-10-20T10:01:00Z',
        'steps': [{'name': step_name, 'conclusion': 'failure', 'number': 1,
                   'started': '2026-10-20T10:00:00Z', 'completed': '2026-10-20T10:00:30Z'}],
    }


class StepDeduplicationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = desktop_history.HistoryStore(Path(self.directory.name) / 'history.db')
        self.addCleanup(self.store.close)

    def test_recording_the_same_job_twice_does_not_duplicate_its_steps(self):
        self.store.record([job()])
        self.store.record([job()])
        self.store.record([job()])
        steps = self.store.steps_for(['o/r:1:10'])
        self.assertEqual(len(steps), 1, 'the same step was stored more than once')

    def test_failing_step_count_is_not_inflated_by_repeated_polls(self):
        for _ in range(5):
            self.store.record([job()])
        summary = self.store.summary()
        self.assertEqual(summary['failing_steps'][0]['failed'], 1,
                         'one failed job must count as one failing step')

    def test_a_step_whose_conclusion_changed_replaces_the_old_row(self):
        first = job()
        second = job()
        second['steps'][0]['conclusion'] = 'success'
        self.store.record([first])
        self.store.record([second])
        steps = self.store.steps_for(['o/r:1:10'])
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]['conclusion'], 'success')


if __name__ == '__main__':
    unittest.main()
```

**Step 1.2 — verify it fails**

```bash
cd C:/Users/PUKEE/ci-dashboard
.venv-desktop/Scripts/python.exe -m unittest test_desktop_history_dedup -v
```

Expected: `FAILED (failures=3)` — `AssertionError: the same step was stored more than once`.

**Step 1.3 — implement minimally**

In `C:\Users\PUKEE\ci-dashboard\desktop_history.py`:

1. Replace the `steps` table definition in the `SCHEMA` constant with a version that has a
   unique key and migrates existing databases:

```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    key TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    run_id INTEGER,
    job_id INTEGER,
    name TEXT,
    workflow TEXT,
    branch TEXT,
    conclusion TEXT,
    status TEXT,
    runner TEXT,
    sha TEXT,
    url TEXT,
    created TEXT,
    started TEXT,
    completed TEXT,
    duration_ms INTEGER,
    recorded_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_repo_time ON jobs(repo, completed);
CREATE TABLE IF NOT EXISTS steps (
    job_key TEXT NOT NULL,
    number INTEGER NOT NULL,
    name TEXT,
    conclusion TEXT,
    started TEXT,
    completed TEXT,
    duration_ms INTEGER,
    recorded_at REAL NOT NULL,
    PRIMARY KEY (job_key, number)
);
CREATE INDEX IF NOT EXISTS steps_job ON steps(job_key);
"""
```

2. Change the insert in `HistoryStore.record()` from `INSERT INTO steps (...)` to
   `INSERT OR REPLACE INTO steps (...)` and drop the `id` column from the column list and
   the tuple:

```python
            self.connection.executemany(
                'INSERT OR REPLACE INTO steps (job_key,number,name,conclusion,started,completed,duration_ms,recorded_at) '
                'VALUES (?,?,?,?,?,?,?,?)', step_rows)
```

3. Add a migration in `HistoryStore.__init__` that rebuilds an old `steps` table (one that
   still has the `id` column) into the new shape. Insert this method and call it from
   `__init__` right after `executescript(SCHEMA)`:

```python
    def _migrate_steps(self):
        """Rebuild a legacy steps table that used a surrogate id and no unique key."""
        with self.lock:
            columns = [row[1] for row in self.connection.execute('PRAGMA table_info(steps)')]
            if 'id' not in columns:
                return
            self.connection.execute('DROP TABLE IF EXISTS steps_new')
            self.connection.execute(
                'CREATE TABLE steps_new ('
                'job_key TEXT NOT NULL, number INTEGER NOT NULL, name TEXT, conclusion TEXT, '
                'started TEXT, completed TEXT, duration_ms INTEGER, recorded_at REAL NOT NULL, '
                'PRIMARY KEY (job_key, number))')
            self.connection.execute(
                'INSERT OR REPLACE INTO steps_new (job_key,number,name,conclusion,started,completed,duration_ms,recorded_at) '
                'SELECT job_key, COALESCE(number, 0), name, conclusion, started, completed, duration_ms, recorded_at FROM steps')
            self.connection.execute('DROP TABLE steps')
            self.connection.execute('ALTER TABLE steps_new RENAME TO steps')
            self.connection.execute('CREATE INDEX IF NOT EXISTS steps_job ON steps(job_key)')
            self.connection.commit()
```

4. In `HistoryStore.record()`, skip step rows whose `number` is `None` — use `0` as the
   fallback key so they still dedupe against each other rather than multiplying:

```python
            for step in job.get('steps') or []:
                step_rows.append((
                    key, step.get('number') or 0, step.get('name'), step.get('conclusion'),
                    step.get('started'), step.get('completed'),
                    _duration_ms(step), now))
```

**Step 1.4 — verify it passes**

```bash
cd C:/Users/PUKEE/ci-dashboard
.venv-desktop/Scripts/python.exe -m unittest test_desktop_history_dedup -v
```

Expected: `Ran 3 tests ... OK`

Then confirm the whole suite still passes:

```bash
.venv-desktop/Scripts/python.exe -m unittest discover -p 'test_*.py' 2>&1 | tail -3
```

Expected: `Ran 89 tests in ~7s` / `OK` (86 existing + 3 new).

**Step 1.5 — clean up the already-polluted database**

The live `history.db` holds 3,743 duplicated step rows. Rebuild it so the numbers are honest:

```bash
cd C:/Users/PUKEE/ci-dashboard
.venv-desktop/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
import desktop_history
s = desktop_history.HistoryStore(r'C:/Users/PUKEE/AppData/Local/CIOperations/history.db')
s._migrate_steps()
print('steps after migration:', len(s.steps_for([j['key'] for j in s.jobs(limit=100000)])))
s.close()"
```

Expected: `steps after migration: 171` (the distinct count), not 3,743.

**Step 1.6 — commit**

```bash
git add -A && git commit -m "fix: record each job step once instead of once per poll"
```

---

### Task 2 — Prune history on a schedule (correctness, ship in v1.1.1)

Nothing calls `prune()`, so the database grows forever.

**Step 2.1 — write the failing test**

Append to `C:\Users\PUKEE\ci-dashboard\test_desktop_service.py`:

```python
    def test_history_is_pruned_during_a_watch_cycle(self):
        service = desktop_service.DesktopService({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, poll=False)
        try:
            calls = []
            with patch.object(service.history, 'prune', side_effect=lambda *a, **k: calls.append(a)):
                service.prune_history()
            self.assertEqual(len(calls), 1, 'the history was not pruned')
        finally:
            service.close()
```

**Step 2.2 — verify it fails**

```bash
.venv-desktop/Scripts/python.exe -m unittest test_desktop_service.ServiceTests.test_history_is_pruned_during_a_watch_cycle -v
```

Expected: `ERROR ... AttributeError: 'DesktopService' object has no attribute 'prune_history'`

**Step 2.3 — implement minimally**

In `C:\Users\PUKEE\ci-dashboard\desktop_service.py`, add the method and call it from the
watch loop:

```python
    def prune_history(self):
        """Drop history that has aged out of the retention window."""
        if self.history is None:
            return 0
        try:
            return self.history.prune()
        except Exception:
            LOGGER.warning('job history could not be pruned')
            return 0
```

and inside `_watch()`, after `self.watch_settings()`:

```python
    def _watch(self):
        while not self.stop.is_set():
            try:
                self.watch_settings()
            except Exception:
                LOGGER.warning('settings watcher failed')
            try:
                self.prune_history()
            except Exception:
                LOGGER.warning('history pruning failed')
            self.stop.wait(3)
```

**Step 2.4 — verify it passes**

```bash
.venv-desktop/Scripts/python.exe -m unittest test_desktop_service -v 2>&1 | tail -5
```

Expected: `Ran 15 tests` / `OK`

**Step 2.5 — commit**

```bash
git add -A && git commit -m "fix: prune aged job history during the watch cycle"
```

---

### Task 3 — Bound the history endpoint payload (correctness, ship in v1.1.1)

`/api/history` currently serialises every stored job. The dashboard only needs the summary
plus a bounded slice.

**Step 3.1 — write the failing test**

Append to `C:\Users\PUKEE\ci-dashboard\test_desktop_service.py`:

```python
    def test_history_endpoint_caps_the_number_of_returned_jobs(self):
        service = desktop_service.DesktopService({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, poll=False)
        isolated = tempfile.TemporaryDirectory()
        self.addCleanup(isolated.cleanup)
        service.history = desktop_history.HistoryStore(Path(isolated.name) / 'history.db')
        self.addCleanup(service.history.close)
        service.start()
        try:
            for index in range(60):
                service.history.record([{
                    'repo': 'o/r', 'run_id': index, 'job_id': index, 'name': f'job{index}',
                    'workflow': 'CI', 'status': 'completed', 'conclusion': 'success',
                    'started': '2026-10-20T10:00:00Z', 'completed': '2026-10-20T10:01:00Z',
                    'steps': []}])
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
            with opener.open(service.launch_url) as response:
                response.read()
            with opener.open(service.origin + '/api/history') as response:
                data = json.load(response)
            self.assertLessEqual(len(data['jobs']), 50, 'the history payload was not capped')
            self.assertEqual(data['summary']['total'], 60, 'the summary must count every job')
        finally:
            service.close()
```

**Step 3.2 — verify it fails**

```bash
.venv-desktop/Scripts/python.exe -m unittest test_desktop_service.ServiceTests.test_history_endpoint_caps_the_number_of_returned_jobs -v
```

Expected: `FAILED ... AssertionError: the history payload was not capped` (60 > 50).

**Step 3.3 — implement minimally**

In `C:\Users\PUKEE\ci-dashboard\desktop_service.py`, add a module constant and use it in
`history_payload()`:

```python
HISTORY_PAGE_LIMIT = 50
```

```python
        if route == '/api/history.csv':
            return self.history.export_csv(since=since).encode('utf-8'), 'text/csv; charset=utf-8'
        body = json.dumps({
            'summary': self.reliability(window),
            'jobs': self.history.export_json(since=since, limit=HISTORY_PAGE_LIMIT)['jobs'],
        }).encode('utf-8')
```

In `C:\Users\PUKEE\ci-dashboard\desktop_history.py`, give `export_json()` a `limit`
parameter that it forwards to `jobs()`:

```python
    def export_json(self, since=None, limit=100000):
        """Return the stored history as a JSON-serialisable structure."""
        jobs = self.jobs(since=since, limit=limit)
```

**Step 3.4 — verify it passes**

```bash
.venv-desktop/Scripts/python.exe -m unittest test_desktop_service -v 2>&1 | tail -5
```

Expected: `Ran 16 tests` / `OK`

**Step 3.5 — commit**

```bash
git add -A && git commit -m "fix: cap the number of jobs returned by the history endpoint"
```

---

### Task 4 — Reduce API calls per poll (sustainability, ship in v1.1.2)

The collector makes four run-list requests per repo where one would do, pushing the app over
GitHub's 5,000/hour limit.

**Step 4.1 — write the failing test**

Append to `C:\Users\PUKEE\ci-dashboard\test_dashboard.py`:

```python
    def test_collection_uses_one_run_request_per_repo(self):
        original = dict(app.STATE)
        try:
            with patch.object(app, 'REPOS', ['owner/repo']), patch.object(app, 'gh_items', return_value=[]) as items:
                app.poll_once()
            run_calls = [c for c in items.call_args_list
                         if '/actions/runs?' in c.args[0]]
            self.assertEqual(len(run_calls), 1,
                             'expected one run-list request per repo, got %d' % len(run_calls))
        finally:
            app.STATE.clear()
            app.STATE.update(original)
```

**Step 4.2 — verify it fails**

```bash
.venv-desktop/Scripts/python.exe -m unittest test_dashboard.PollTests.test_collection_uses_one_run_request_per_repo -v
```

Expected: `FAILED ... got 4`

**Step 4.3 — implement minimally**

In `C:\Users\PUKEE\ci-dashboard\ci_dashboard.py`, replace the four status-scoped run queries in
`_collect()` with one request that fetches recent runs and filters locally:

```python
        runs = {}
        try:
            for run in gh_items(f"/repos/{repo}/actions/runs?per_page=100&created=%3E{since}", "workflow_runs"):
                if run.get("status") in ("in_progress", "queued", "waiting", "completed", "requested"):
                    runs[run["id"]] = run
        except urllib.error.HTTPError:
            raise
```

Note: the previous four queries used `status=in_progress|queued|waiting` plus a
`created=>since` window with no status filter. The single request above covers the same set
because `created=>since` already bounds the result, and `completed` runs are needed for the
history. Jobs older than the 3-hour window are intentionally dropped — the collector was
never a complete archive.

**Step 4.4 — verify it passes**

```bash
.venv-desktop/Scripts/python.exe -m unittest test_dashboard -v 2>&1 | tail -5
.venv-desktop/Scripts/python.exe -m unittest discover -p 'test_*.py' 2>&1 | tail -3
```

Expected: `OK` then `Ran 90 tests` / `OK`

**Step 4.5 — measure the improvement**

```bash
.venv-desktop/Scripts/python.exe -c "
repos=2; runs=19
calls = repos*(1+1+runs)
print('calls per poll:', calls)
print('per hour (30s):', int(calls*120))
print('limit 5000/hour -> headroom', 5000-int(calls*120))"
```

Expected: `calls per poll: 40`, `per hour (30s): 4800`, `headroom 200`.

If the headroom is still too thin, Task 5 raises the poll interval adaptively.

**Step 4.6 — commit**

```bash
git add -A && git commit -m "perf: fetch recent workflow runs in one request per repo"
```

---

### Task 5 — Adaptive poll interval driven by the remaining rate limit (sustainability, v1.1.2)

The collector already reads `X-RateLimit-Remaining` into `STATE['rate']` but never acts on it.
Poll faster when work is in flight, back off when the budget is thin.

**Step 5.1 — write the failing test**

Create `C:\Users\PUKEE\ci-dashboard\test_desktop_polling.py`:

```python
"""The poll interval must react to the remaining GitHub rate limit."""
import unittest

import desktop_service


class AdaptivePollTests(unittest.TestCase):
    def test_thin_rate_limit_slows_the_poll_down(self):
        self.assertGreaterEqual(desktop_service.poll_interval(rate_remaining='10'), 120)

    def test_healthy_rate_limit_keeps_the_poll_fast(self):
        self.assertLessEqual(desktop_service.poll_interval(rate_remaining='4500'), 30)

    def test_unknown_rate_limit_uses_the_default(self):
        self.assertEqual(desktop_service.poll_interval(rate_remaining=None), 30)

    def test_running_work_polls_faster_than_idle(self):
        idle = desktop_service.poll_interval(rate_remaining='4500', running=False)
        busy = desktop_service.poll_interval(rate_remaining='4500', running=True)
        self.assertLess(busy, idle)

    def test_a_low_rate_limit_never_polls_faster_than_the_backoff_floor(self):
        self.assertGreaterEqual(desktop_service.poll_interval(rate_remaining='1', running=True), 120)


if __name__ == '__main__':
    unittest.main()
```

**Step 5.2 — verify it fails**

```bash
.venv-desktop/Scripts/python.exe -m unittest test_desktop_polling -v
```

Expected: `ERROR ... AttributeError: module 'desktop_service' has no attribute 'poll_interval'`

**Step 5.3 — implement minimally**

In `C:\Users\PUKEE\ci-dashboard\desktop_service.py`, add:

```python
BASE_POLL_SECONDS = 30
MIN_POLL_SECONDS = 20
MAX_POLL_SECONDS = 300
RATE_LIMIT_FLOOR = 200      # below this many remaining requests, back off hard
RATE_LIMIT_SOFT = 1000      # below this, back off moderately


def poll_interval(rate_remaining=None, running=False):
    """Return how many seconds to wait before the next poll."""
    try:
        remaining = int(rate_remaining)
    except (TypeError, ValueError):
        remaining = None
    if remaining is None:
        interval = BASE_POLL_SECONDS
    elif remaining <= RATE_LIMIT_FLOOR:
        interval = MAX_POLL_SECONDS
    elif remaining < RATE_LIMIT_SOFT:
        interval = 120
    else:
        interval = BASE_POLL_SECONDS
    if running and interval > MIN_POLL_SECONDS and remaining is None or (running and remaining and remaining >= RATE_LIMIT_SOFT and interval > MIN_POLL_SECONDS):
        interval = MIN_POLL_SECONDS
    return max(MIN_POLL_SECONDS, min(MAX_POLL_SECONDS, interval))
```

Simplify that `if` into a readable form before committing:

```python
def poll_interval(rate_remaining=None, running=False):
    """Return how many seconds to wait before the next poll."""
    try:
        remaining = int(rate_remaining)
    except (TypeError, ValueError):
        remaining = None
    if remaining is None:
        interval = BASE_POLL_SECONDS
    elif remaining <= RATE_LIMIT_FLOOR:
        interval = MAX_POLL_SECONDS
    elif remaining < RATE_LIMIT_SOFT:
        interval = 120
    else:
        interval = BASE_POLL_SECONDS
    if running and interval > MIN_POLL_SECONDS and (remaining is None or remaining >= RATE_LIMIT_SOFT):
        interval = MIN_POLL_SECONDS
    return max(MIN_POLL_SECONDS, min(MAX_POLL_SECONDS, interval))
```

Then use it in `_poll()` — replace `self.stop.wait(dashboard.POLL)` with a wait that uses the
computed interval and has work in flight:

```python
    def _poll(self):
        while not self.stop.is_set():
            try:
                dashboard.poll_once()
                if dashboard.STATE.get('error'):
                    dashboard.STATE['error'] = 'GitHub data is incomplete or unavailable. Check your connection and token permissions (Actions/Administration: Read).'
                self.record_history()
            except Exception:
                # Never include exception repr, request headers or credentials in the UI.
                dashboard.STATE['error'] = 'GitHub connection failed. Please try again or check your token.'
            running = any(job.get('status') == 'in_progress' for job in (dashboard.STATE.get('jobs') or []))
            interval = poll_interval(dashboard.STATE.get('rate'), running=running)
            self.stop.wait(interval)
```

**Step 5.4 — verify it passes**

```bash
.venv-desktop/Scripts/python.exe -m unittest test_desktop_polling -v
.venv-desktop/Scripts/python.exe -m unittest discover -p 'test_*.py' 2>&1 | tail -3
```

Expected: `Ran 5 tests` / `OK`, then `Ran 95 tests` / `OK`

**Step 5.5 — commit**

```bash
git add -A && git commit -m "feat: adapt the poll interval to the remaining GitHub rate limit"
```

---

### Task 6 — Detect newly failed jobs (foundation for notifications, v1.2.0)

The history database already knows every job key ever seen, so it can answer "which failures
are new?" exactly — no heuristic needed.

**Step 6.1 — write the failing test**

Create `C:\Users\PUKEE\ci-dashboard\test_desktop_alerts.py`:

```python
"""Detection of newly failed jobs, used to raise Windows notifications."""
import tempfile
import unittest
from pathlib import Path

import desktop_alerts


def job(job_id=10, conclusion='failure'):
    return {
        'repo': 'o/r', 'run_id': 1, 'job_id': job_id, 'name': f'build-{job_id}',
        'workflow': 'CI', 'branch': 'main', 'conclusion': conclusion, 'status': 'completed',
        'runner': 'w1', 'sha': 'abc1234', 'url': 'https://github.com/o/r/actions/runs/1',
        'started': '2026-10-20T10:00:00Z', 'completed': '2026-10-20T10:01:00Z', 'steps': [],
    }


class NewFailureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = desktop_alerts.HistoryStore(Path(self.directory.name) / 'history.db')
        self.addCleanup(self.store.close)

    def test_a_failure_seen_for_the_first_time_is_new(self):
        fresh = desktop_alerts.new_failures(self.store, [job()])
        self.assertEqual(len(fresh), 1)
        self.assertEqual(fresh[0]['workflow'], 'CI')

    def test_the_same_failure_is_not_reported_twice(self):
        desktop_alerts.new_failures(self.store, [job()])
        again = desktop_alerts.new_failures(self.store, [job()])
        self.assertEqual(again, [], 'an already-known failure was reported again')

    def test_successful_jobs_are_never_reported(self):
        self.assertEqual(desktop_alerts.new_failures(self.store, [job(conclusion='success')]), [])

    def test_running_jobs_are_never_reported(self):
        running = job()
        running['status'] = 'in_progress'
        self.assertEqual(desktop_alerts.new_failures(self.store, [running]), [])

    def test_a_retry_of_the_same_job_is_not_a_new_failure(self):
        desktop_alerts.new_failures(self.store, [job()])
        self.assertEqual(desktop_alerts.new_failures(self.store, [job()]), [])


if __name__ == '__main__':
    unittest.main()
```

**Step 6.2 — verify it fails**

```bash
.venv-desktop/Scripts/python.exe -m unittest test_desktop_alerts -v
```

Expected: `ERROR ... ModuleNotFoundError: No module named 'desktop_alerts'`

**Step 6.3 — implement minimally**

Create `C:\Users\PUKEE\ci-dashboard\desktop_alerts.py`:

```python
"""Detect newly failed jobs so the console can notify without being watched."""
from desktop_history import FAILED_CONCLUSIONS, job_key


def new_failures(store, jobs):
    """Return the failed jobs in `jobs` that the store has not seen before.

    A job that was already recorded keeps its identity across polls, so a repeated
    observation of the same failure is not reported again.
    """
    if store is None:
        return []
    fresh = []
    for job in jobs or []:
        if job.get('status') != 'completed':
            continue
        if job.get('conclusion') not in FAILED_CONCLUSIONS:
            continue
        key = job_key(job)
        if store.has_job(key):
            continue
        fresh.append(job)
    return fresh


def describe(job):
    """Return a one-line, human-readable description of a failed job."""
    repo = job.get('repo') or 'unknown repository'
    workflow = job.get('workflow') or 'workflow'
    name = job.get('name') or 'job'
    return f'{workflow} · {name} failed in {repo}'
```

Add `has_job()` to `C:\Users\PUKEE\ci-dashboard\desktop_history.py`, inside `HistoryStore`:

```python
    def has_job(self, key):
        """True when this job has already been recorded."""
        with self.lock:
            row = self.connection.execute('SELECT 1 FROM jobs WHERE key = ? LIMIT 1', (key,)).fetchone()
        return row is not None
```

**Step 6.4 — verify it passes**

```bash
.venv-desktop/Scripts/python.exe -m unittest test_desktop_alerts -v
```

Expected: `Ran 5 tests` / `OK`

**Step 6.5 — commit**

```bash
git add -A && git commit -m "feat: detect newly failed jobs from the recorded history"
```

---

### Task 7 — Raise a Windows toast notification (v1.2.0)

`webview` exposes no notification API and no notification library is installed. The WinRT
`ToastNotificationManager` is available on this machine, so it is driven through PowerShell
(one process per toast, no new dependency).

**Step 7.1 — write the failing test**

Create `C:\Users\PUKEE\ci-dashboard\test_desktop_notify.py`:

```python
"""Windows toast notifications, tested without displaying anything."""
import unittest
from unittest.mock import patch

import desktop_notify


class ToastTests(unittest.TestCase):
    def test_a_toast_is_raised_for_a_failed_job(self):
        calls = []
        with patch.object(desktop_notify.subprocess, 'run', side_effect=lambda *a, **k: calls.append(a)):
            ok = desktop_notify.notify_failure(
                {'repo': 'o/r', 'workflow': 'CI', 'name': 'build', 'url': 'https://github.com/o/r/actions/runs/1'})
        self.assertTrue(ok)
        self.assertEqual(len(calls), 1)

    def test_the_toast_text_mentions_the_workflow_and_repository(self):
        captured = {}

        def fake_run(args, **kwargs):
            captured['script'] = args[1]
            captured['args'] = args

        with patch.object(desktop_notify.subprocess, 'run', side_effect=fake_run):
            desktop_notify.notify_failure(
                {'repo': 'o/r', 'workflow': 'CI', 'name': 'build', 'url': ''})
        self.assertIn('CI', captured['script'])
        self.assertIn('o/r', captured['script'])

    def test_a_failure_without_details_still_raises_a_toast(self):
        calls = []
        with patch.object(desktop_notify.subprocess, 'run', side_effect=lambda *a, **k: calls.append(a)):
            self.assertTrue(desktop_notify.notify_failure({}))

    def test_a_crashed_notifier_does_not_raise(self):
        with patch.object(desktop_notify.subprocess, 'run', side_effect=OSError('no powershell')):
            self.assertFalse(desktop_notify.notify_failure({'repo': 'o/r'}))

    def test_notifications_can_be_switched_off(self):
        calls = []
        with patch.object(desktop_notify.subprocess, 'run', side_effect=lambda *a, **k: calls.append(a)):
            self.assertFalse(desktop_notify.notify_failure({'repo': 'o/r'}, enabled=False))
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
```

**Step 7.2 — verify it fails**

```bash
.venv-desktop/Scripts/python.exe -m unittest test_desktop_notify -v
```

Expected: `ERROR ... ModuleNotFoundError: No module named 'desktop_notify'`

**Step 7.3 — implement minimally**

Create `C:\Users\PUKEE\ci-dashboard\desktop_notify.py`:

```python
"""Windows toast notifications, with no third-party dependency.

The toast is raised through the WinRT ToastNotificationManager, which is available on
Windows 10 and 11. PowerShell is used as the bridge so the application does not need a
WinRT runtime binding.
"""
import logging
import subprocess

LOGGER = logging.getLogger('ci_operations')

APP_ID = 'CI Operations'
POWERSHELL = 'powershell.exe'
TIMEOUT_SECONDS = 20

TOAST_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null
$title = $args[0]
$body = $args[1]
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$title</text><text>$body</text></binding></visual></toast>")
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('%s').Show($toast)
""" % APP_ID


def notify_failure(job, enabled=True):
    """Raise a Windows toast for a failed job. Returns True when a toast was raised."""
    if not enabled:
        return False
    workflow = (job or {}).get('workflow') or 'A workflow'
    repo = (job or {}).get('repo') or 'a repository'
    name = (job or {}).get('name') or 'a job'
    title = f'{workflow} failed'
    body = f'{name} failed in {repo}'
    try:
        subprocess.run(
            [POWERSHELL, '-NoProfile', '-NonInteractive', '-Command', TOAST_SCRIPT, title, body],
            timeout=TIMEOUT_SECONDS, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (OSError, subprocess.SubprocessError) as error:
        LOGGER.info('toast notification could not be raised (%s)', type(error).__name__)
        return False
```

**Step 7.4 — verify it passes**

```bash
.venv-desktop/Scripts/python.exe -m unittest test_desktop_notify -v
```

Expected: `Ran 5 tests` / `OK`

**Step 7.5 — verify a real toast appears**

```bash
.venv-desktop/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
import desktop_notify
print('raised:', desktop_notify.notify_failure({'workflow':'CI','name':'toast self test','repo':'axionaxprotocol/nakharax'}))"
```

Expected: `raised: True` and a Windows toast titled "CI failed" appears in the notification
area. Confirm visually — this is the one step that cannot be asserted by a test.

**Step 7.6 — commit**

```bash
git add -A && git commit -m "feat: raise a Windows toast notification for a failed job"
```

---

### Task 8 — Wire notifications into the poll loop (v1.2.0)

**Step 8.1 — write the failing test**

Append to `C:\Users\PUKEE\ci-dashboard\test_desktop_alerts.py`:

```python
class NotificationDispatchTests(unittest.TestCase):
    def test_a_new_failure_raises_exactly_one_toast(self):
        import desktop_alerts
        store = desktop_alerts.HistoryStore
        self.assertTrue(hasattr(desktop_alerts, 'notify_new_failures'))

    def test_notifying_twice_does_not_raise_a_second_toast(self):
        import desktop_alerts
        calls = []
        from unittest.mock import patch
        with patch.object(desktop_alerts, 'notify_failure', side_effect=lambda job, **k: calls.append(job)):
            directory = tempfile.TemporaryDirectory()
            self.addCleanup(directory.cleanup)
            local = desktop_alerts.HistoryStore(Path(directory.name) / 'history.db')
            self.addCleanup(local.close)
            first = desktop_alerts.notify_new_failures(local, [job()])
            second = desktop_alerts.notify_new_failures(local, [job()])
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(calls), 1)
```

Remove the placeholder first test (the `assertTrue(hasattr(...))` line) and keep only the
real behavioural test — the file must contain exactly:

```python
class NotificationDispatchTests(unittest.TestCase):
    def test_notifying_twice_does_not_raise_a_second_toast(self):
        import desktop_alerts
        calls = []
        from unittest.mock import patch
        with patch.object(desktop_alerts, 'notify_failure', side_effect=lambda job, **k: calls.append(job)):
            directory = tempfile.TemporaryDirectory()
            self.addCleanup(directory.cleanup)
            local = desktop_alerts.HistoryStore(Path(directory.name) / 'history.db')
            self.addCleanup(local.close)
            first = desktop_alerts.notify_new_failures(local, [job()])
            second = desktop_alerts.notify_new_failures(local, [job()])
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(calls), 1)
```

**Step 8.2 — verify it fails**

```bash
.venv-desktop/Scripts/python.exe -m unittest test_desktop_alerts.NotificationDispatchTests -v
```

Expected: `AttributeError: module 'desktop_alerts' has no attribute 'notify_new_failures'`

**Step 8.3 — implement minimally**

In `C:\Users\PUKEE\ci-dashboard\desktop_alerts.py`, add:

```python
from desktop_notify import notify_failure


def notify_new_failures(store, jobs, enabled=True):
    """Raise a toast for each newly failed job. Returns True when a toast was raised."""
    fresh = new_failures(store, jobs)
    if not fresh:
        return False
    for job in fresh:
        notify_failure(job, enabled=enabled)
    return True
```

**Step 8.4 — verify it passes**

```bash
.venv-desktop/Scripts/python.exe -m unittest test_desktop_alerts -v
```

Expected: `Ran 6 tests` / `OK`

**Step 8.5 — wire it into the service**

In `C:\Users\PUKEE\ci-dashboard\desktop_service.py`:

1. Import the alert helpers at the top:

```python
from desktop_alerts import notify_new_failures
```

2. Call it from `_poll()` right after `self.record_history()`:

```python
                self.record_history()
                self.raise_failure_notifications()
```

3. Add the method:

```python
    def raise_failure_notifications(self):
        """Raise a toast for each newly failed job."""
        if self.history is None:
            return False
        try:
            return notify_new_failures(self.history, dashboard.STATE.get('jobs') or [],
                                       enabled=self.notifications_enabled)
        except Exception:
            LOGGER.warning('failure notifications could not be raised')
            return False
```

4. Set `self.notifications_enabled` in `__init__`, defaulting to on but respecting the
   saved setting:

```python
        self.notifications_enabled = settings.get('notifications', True) is not False
```

**Step 8.6 — verify it passes**

```bash
.venv-desktop/Scripts/python.exe -m unittest discover -p 'test_*.py' 2>&1 | tail -3
```

Expected: `Ran 96 tests` / `OK`

**Step 8.7 — commit**

```bash
git add -A && git commit -m "feat: notify on newly failed jobs from the poll loop"
```

---

### Task 9 — Settings toggle for notifications (v1.2.0)

The setting must live in the same DPAPI-encrypted settings file as the token, so it follows
the existing save/reload path with no new plumbing.

**Step 9.1 — write the failing test**

Append to `C:\Users\PUKEE\ci-dashboard\test_desktop_setup.py`:

```python
    def test_the_settings_form_offers_a_notification_choice(self):
        source = open(setup.__file__, encoding='utf-8').read()
        self.assertIn('Notify me when a job fails', source)
        self.assertIn('notifications', source)
```

**Step 9.2 — verify it fails**

```bash
.venv-desktop/Scripts/python.exe -m unittest test_desktop_setup.SetupTests.test_the_settings_form_offers_a_notification_choice -v
```

Expected: `FAILED ... AssertionError: 'Notify me when a job fails' not found`

**Step 9.3 — implement minimally**

In `C:\Users\PUKEE\ci-dashboard\desktop_setup.py`:

1. Add a variable next to `auto`:

```python
    auto = tk.BooleanVar(value=startup_enabled())
    notify = tk.BooleanVar(value=(existing or {}).get('notifications', True) is not False)
```

2. Add the checkbox after the startup checkbox:

```python
    ttk.Checkbutton(frame, text='Notify me when a job fails', variable=notify).pack(anchor='w', pady=(0, 8))
```

3. Include it in the saved payload. Find the line that builds the saved data
   (`messages.put((True, {'token': value, 'repos': selected, 'poll': 30}, requested_auto))`)
   and change it to:

```python
                messages.put((True, {'token': value, 'repos': selected, 'poll': 30,
                                     'notifications': notify.get()}, requested_auto))
```

**Step 9.4 — verify it passes**

```bash
.venv-desktop/Scripts/python.exe -m unittest test_desktop_setup -v 2>&1 | tail -5
.venv-desktop/Scripts/python.exe -m unittest discover -p 'test_*.py' 2>&1 | tail -3
```

Expected: `OK` then `Ran 97 tests` / `OK`

**Step 9.5 — commit**

```bash
git add -A && git commit -m "feat: add a settings toggle for failure notifications"
```

---

### Task 10 — Update documentation and version (v1.1.1 and v1.2.0)

**Step 10.1 — update `CHANGELOG.md`**

Add a `## [1.1.1]` section under `## [Unreleased]` describing the three correctness fixes,
and a `## [1.2.0]` section describing the adaptive polling and the notifications. State
plainly that the v1.1.0 failing-step counts were inflated by a duplication bug and have been
corrected.

**Step 10.2 — update `README.md`**

In the **Features** list, add a bullet for failure notifications and adaptive polling.
In **Understanding the metrics**, document that the failing-step counts come from distinct
recorded jobs, not from repeated observations.

**Step 10.3 — update `SECURITY.md`**

The file currently states the application "does not implement ... durable history". That is no
longer true — v1.1.0 added the SQLite history. Replace that clause with an accurate
description of the local SQLite history and its retention window, and note that the history
is unencrypted but contains only job metadata (no tokens).

**Step 10.4 — bump the version**

In each of these three files, change the version string:

| File | Change |
|---|---|
| `C:\Users\PUKEE\ci-dashboard\desktop_app.py` | `CURRENT_VERSION = "1.1.0"` → `"1.2.0"` |
| `C:\Users\PUKEE\ci-dashboard\installer.iss` | `AppVersion=1.1.0` → `AppVersion=1.2.0` |
| `C:\Users\PUKEE\ci-dashboard\pyproject.toml` | `version = "1.1.0"` → `version = "1.2.0"` |

**Step 10.5 — verify the whole suite**

```bash
cd C:/Users/PUKEE/ci-dashboard
.venv-desktop/Scripts/python.exe -m unittest discover -p 'test_*.py' 2>&1 | tail -3
node --test test_frontend.cjs 2>&1 | tail -4
```

Expected: Python `Ran 97 tests` / `OK`; Node `tests 23 / pass 23 / fail 0`.

**Step 10.6 — commit**

```bash
git add -A && git commit -m "chore: release 1.2.0 with notifications and adaptive polling"
```

---

### Task 11 — Build, publish and verify the release (v1.2.0)

**Step 11.1 — build locally and smoke-test the packaged app**

```bash
cd C:/Users/PUKEE/ci-dashboard
.venv-desktop/Scripts/python.exe build_desktop.py 2>&1 | tail -3
```

Expected: `Installer: C:\Users\PUKEE\ci-dashboard\dist\CI-Operations-Setup.exe`

**Step 11.2 — push the tag and wait for the release**

```bash
git push origin main
git tag -a v1.2.0 -m "v1.2.0"
git push origin v1.2.0
```

Then poll for the assets:

```bash
for i in $(seq 1 15); do sleep 20; s=$(gh release view v1.2.0 --repo axionaxprotocol/ci-operations --json assets --jq '.assets|length' 2>/dev/null || echo 0); echo "assets=$s"; [ "$s" -ge 2 ] && break; done
```

Expected: `assets=2` (the installer and `SHA256SUMS.txt`).

**Step 11.3 — install and verify the real app**

```bash
'C:/Users/PUKEE/AppData/Local/hermes/cache/scratch/../scratch/v120/CI-Operations-Setup.exe' /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

(First download the asset with
`gh release download v1.2.0 --repo axionaxprotocol/ci-operations --dir <scratch>/v120 --clobber`.)

Verify the installed version:

```bash
reg query 'HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\CI-Operations-Desktop_is1' /v DisplayVersion
```

Expected: `DisplayVersion    REG_SZ    1.2.0`

**Step 11.4 — verify the deduplication fix on the live database**

```bash
.venv-desktop/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
import desktop_history
s = desktop_history.HistoryStore(r'C:/Users/PUKEE/AppData/Local/CIOperations/history.db')
keys=[j['key'] for j in s.jobs(limit=100000)]
steps=s.steps_for(keys)
print('jobs:', len(keys), 'steps:', len(steps), 'distinct (job_key,number):', len({(x['job_key'],x['number']) for x in steps}))
s.close()"
```

Expected: `steps` equals `distinct (job_key,number)` — no inflation.

**Step 11.5 — confirm the CI run is green**

```bash
gh run list --repo axionaxprotocol/ci-operations --limit 3 --json workflowName,conclusion --jq '[.[]|{w:.workflowName,c:.conclusion}]'
```

Expected: `Windows tests`, `CodeQL` and `Release` all `success`.

---

## Tests / validation

**Per-task cycle** — every task above follows RED → GREEN → commit:

| Step | Command | Expected |
|---|---|---|
| Write failing test | `python -m unittest <module> -v` | `FAILED` / `ERROR` naming the missing behaviour |
| Implement minimally | — | — |
| Verify pass | `python -m unittest <module> -v` | `OK` |
| Verify no regressions | `python -m unittest discover -p 'test_*.py'` | `Ran N tests` / `OK` |
| Frontend unaffected | `node --test test_frontend.cjs` | `pass 23 / fail 0` |
| Commit | `git commit -m "..."` | one commit per task |

**Suite totals expected after each phase:**

| Point | Python tests | Frontend tests |
|---|---|---|
| v1.1.0 baseline (measured) | 86 | 23 |
| after Task 1 | 89 | 23 |
| after Task 2 | 90 | 23 |
| after Task 3 | 91 | 23 |
| after Task 4 | 92 | 23 |
| after Task 5 | 97 | 23 |
| after Task 6 | 102 | 23 |
| after Task 7 | 107 | 23 |
| after Task 8 | 108 | 23 |
| after Task 9 | 109 | 23 |

**End-to-end verification (not covered by unit tests):**

1. **A real toast appears.** Run the Task 7.5 command and confirm the Windows notification
   shows "CI failed". This is the only acceptance criterion that cannot be asserted
   automatically — the user must see it.
2. **The live database stops growing.** After Task 1, run the app for ten minutes, then
   confirm `steps` no longer exceeds `distinct (job_key, number)` and that `history.db`
   stops growing by hundreds of rows per poll.
3. **The API budget is respected.** After Task 5, watch `STATE['rate']` in the dashboard
   footer across an hour of polling and confirm it stays above zero.
4. **The packaged app still passes its smoke test.** The CI job runs
   `--self-test-report`, `--setup-smoke-report` and `--ui-smoke-report` against the built
   `.exe`; a red build fails the release.

---

## Risks, tradeoffs, and open questions

**Risks**

| Risk | Impact | Mitigation |
|---|---|---|
| PowerShell toast spawning costs ~200 ms per notification | Negligible — failures are rare | Run it on the poll thread, never on the UI thread |
| Toast notifications may be blocked by Windows focus-assist settings | The user sees nothing | Add an in-app banner as a fallback in a later task; the setting toggle lets the user disable toasts |
| The step-dedup migration rewrites the `steps` table | A crash mid-migration loses step rows | The migration runs in a transaction and is idempotent; `jobs` is never touched, so job history survives |
| One run-list request instead of four may miss a run | A run is not shown for up to 3 hours | The `created=>since` window bounds the same set the old queries covered; `completed` runs are now included, which they were not before |
| Adaptive polling may look "frozen" during a rate-limit crunch | The user thinks the app hung | The dashboard already shows "Stale data · waiting for an update" after 90 seconds; surface the current poll interval in the footer |
| `SECURITY.md` currently claims there is no durable history | Documentation contradicts the code | Task 10.3 corrects it |

**Tradeoffs**

- **Toast via PowerShell rather than a native binding.** A WinRT Python binding would be
  cleaner but adds a dependency, a PyInstaller packaging change, and a per-version upgrade
  burden. PowerShell keeps the dependency list at two packages.
- **Adaptive polling trades latency for budget.** A 300-second floor during a rate-limit
  crunch means the dashboard can look stale. This is the correct behaviour for a tool that
  must not fall off the API, but it must be visible in the UI.
- **Fixing the duplication changes the reported numbers.** The v1.1.0 release notes cite
  "Playwright 28 failed"; the corrected figure is lower. This is the right outcome, but the
  changelog must say so plainly rather than quietly changing the number.
- **One run request instead of four changes what the collector sees.** The old status-scoped
  queries returned recently-created runs regardless of age; the new single query is bounded by
  `created=>since` (3 hours). Runs older than that were already being dropped for the
  in-progress/queued/waiting queries but *were* being captured by the fourth query, so the
  history gains slightly less depth.

**Open questions**

1. **Should notifications be on by default?** The plan defaults them on. Some users would
   rather opt in. Worth confirming before shipping v1.2.0.
2. **Retention window.** `MAX_AGE_SECONDS` is 90 days. With the duplication fixed the
   database is far smaller, so 90 days may be generous or insufficient. No decision needed
   now — it is one constant.
3. **Should the toast include the job URL?** The plan puts the URL in the toast body only if
   present. Clicking a toast to open the failing job would need a registered protocol handler
   (`ci-operations://`), which is a larger change and is out of scope here.
4. **Multi-repository roll-up.** The Reliability panel is global; per-repository breakdowns
   are not built. The `jobs` table already carries `repo`, so the query is cheap to add later.
5. **Is the 3-hour collection window right?** Jobs older than 3 hours are only in the history
   if the app happened to be running. A longer window costs API calls. Worth revisiting once
   the rate-limit behaviour is observed over a real week.

---

## Deferred (explicitly not in this plan)

- Dark mode — the user asked for light mode explicitly.
- Writing to GitHub (re-run, cancel) — the console is read-only by design.
- A web dashboard served to other machines — the session gate is per-process and loopback-only.
- A hosted service, SSO, or multi-user support — out of scope for a local console.
