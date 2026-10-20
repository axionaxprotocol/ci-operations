"""Durable local history of completed jobs, stored in SQLite.

The collector overwrites its in-memory state on every poll, so nothing that
happened before the last restart survives. This module keeps a local record
of finished jobs so the dashboard can show failure trends and the steps that
broke, without ever sending anything to GitHub.
"""
import json
import sqlite3
import threading
import time
from pathlib import Path

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

MAX_AGE_SECONDS = 90 * 24 * 3600
FAILED_CONCLUSIONS = ('failure', 'timed_out', 'action_required', 'startup_failure')


def job_key(job):
    """Stable identity for a job across polls."""
    repo = job.get('repo') or ''
    run_id = job.get('run_id')
    job_id = job.get('job_id')
    if run_id is not None and job_id is not None:
        return f'{repo}:{run_id}:{job_id}'
    return f"{repo}:{job.get('name') or ''}:{job.get('completed') or job.get('created') or ''}"


def _timestamp(value):
    """Parse an ISO-8601 timestamp into epoch seconds, or None."""
    if not value:
        return None
    try:
        from datetime import datetime
        text = str(value).replace('Z', '+00:00')
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            from datetime import timezone
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError):
        return None


def _duration_ms(job):
    start = _timestamp(job.get('started'))
    end = _timestamp(job.get('completed'))
    if start is None or end is None:
        return None
    return max(0, int((end - start) * 1000))


class HistoryStore:
    """SQLite-backed record of finished jobs and the steps inside them."""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self._migrate_steps()
        self.connection.commit()

    def _migrate_steps(self):
        """Rebuild a legacy steps table that used a surrogate id and no unique key.

        The legacy table appended a fresh copy of every step on every poll, so the
        same failure was counted once per poll. Rebuilding collapses those rows.
        """
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

    def close(self):
        with self.lock:
            self.connection.close()

    def record(self, jobs):
        """Store completed jobs and their steps. Returns the number of new rows."""
        now = time.time()
        inserted = 0
        rows = []
        step_rows = []
        for job in jobs or []:
            if job.get('status') != 'completed':
                continue
            key = job_key(job)
            rows.append((
                key, job.get('repo') or '', job.get('run_id'), job.get('job_id'),
                job.get('name'), job.get('workflow'), job.get('branch'), job.get('conclusion'),
                job.get('status'), job.get('runner'), job.get('sha'), job.get('url'),
                job.get('created'), job.get('started'), job.get('completed'),
                _duration_ms(job), now))
            for step in job.get('steps') or []:
                step_rows.append((
                    key, step.get('number') or 0, step.get('name'), step.get('conclusion'),
                    step.get('started'), step.get('completed'),
                    _duration_ms(step), now))
        if not rows and not step_rows:
            return 0
        with self.lock:
            before = self.connection.total_changes
            self.connection.executemany(
                'INSERT OR REPLACE INTO jobs (key,repo,run_id,job_id,name,workflow,branch,conclusion,'
                'status,runner,sha,url,created,started,completed,duration_ms,recorded_at) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
            self.connection.executemany(
                'INSERT OR REPLACE INTO steps (job_key,number,name,conclusion,started,completed,duration_ms,recorded_at) '
                'VALUES (?,?,?,?,?,?,?,?)', step_rows)
            self.connection.commit()
            inserted = self.connection.total_changes - before
        return inserted

    def prune(self, max_age_seconds=MAX_AGE_SECONDS):
        """Delete records older than the retention window."""
        cutoff = time.time() - max_age_seconds
        with self.lock:
            self.connection.execute('DELETE FROM steps WHERE job_key NOT IN (SELECT key FROM jobs)')
            self.connection.execute('DELETE FROM jobs WHERE recorded_at < ?', (cutoff,))
            self.connection.commit()

    def jobs(self, repo=None, since=None, limit=500):
        """Return stored jobs, newest first."""
        query = 'SELECT * FROM jobs'
        clauses = []
        params = []
        if repo:
            clauses.append('repo = ?')
            params.append(repo)
        if since is not None:
            clauses.append('recorded_at >= ?')
            params.append(since)
        if clauses:
            query += ' WHERE ' + ' AND '.join(clauses)
        query += ' ORDER BY recorded_at DESC LIMIT ?'
        params.append(int(limit))
        with self.lock:
            rows = self.connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def steps_for(self, keys):
        """Return the recorded steps for the given job keys."""
        keys = list(keys)
        if not keys:
            return []
        placeholders = ','.join('?' for _ in keys)
        with self.lock:
            rows = self.connection.execute(
                f'SELECT * FROM steps WHERE job_key IN ({placeholders})', keys).fetchall()
        return [dict(row) for row in rows]

    def summary(self, since=None):
        """Aggregate success rate, failure counts, and the worst failing steps."""
        jobs = self.jobs(since=since, limit=100000)
        total = len(jobs)
        failures = [job for job in jobs if job.get('conclusion') in FAILED_CONCLUSIONS]
        successes = [job for job in jobs if job.get('conclusion') == 'success']
        durations = sorted(job['duration_ms'] for job in jobs if job.get('duration_ms') is not None)
        by_workflow = {}
        for job in jobs:
            name = job.get('workflow') or 'Unknown workflow'
            entry = by_workflow.setdefault(name, {'workflow': name, 'total': 0, 'failed': 0})
            entry['total'] += 1
            if job.get('conclusion') in FAILED_CONCLUSIONS:
                entry['failed'] += 1
        workflows = sorted(
            (dict(entry, success_rate=round((entry['total'] - entry['failed']) / entry['total'] * 100))
             for entry in by_workflow.values()),
            key=lambda item: (-item['failed'], item['workflow']))
        step_counts = {}
        for step in self.steps_for([job['key'] for job in failures]):
            if step.get('conclusion') not in FAILED_CONCLUSIONS:
                continue
            name = step.get('name') or 'Unknown step'
            entry = step_counts.setdefault(name, {'step': name, 'failed': 0})
            entry['failed'] += 1
        failing_steps = sorted(step_counts.values(), key=lambda item: (-item['failed'], item['step']))
        return {
            'total': total,
            'failed': len(failures),
            'successes': len(successes),
            'success_rate': round(len(successes) / total * 100) if total else None,
            'median_duration_ms': durations[len(durations) // 2] if durations else None,
            'p95_duration_ms': durations[min(len(durations) - 1, int(len(durations) * 0.95))] if durations else None,
            'workflows': workflows,
            'failing_steps': failing_steps[:10],
            'generated_at': time.time(),
        }

    def export_json(self, since=None):
        """Return the stored history as a JSON-serialisable structure."""
        jobs = self.jobs(since=since, limit=100000)
        keys = [job['key'] for job in jobs]
        steps_by_job = {}
        for step in self.steps_for(keys):
            steps_by_job.setdefault(step['job_key'], []).append(step)
        for job in jobs:
            job['steps'] = steps_by_job.get(job['key'], [])
        return {'jobs': jobs, 'generated_at': time.time()}

    def export_csv(self, since=None):
        """Return the stored history as CSV text."""
        import csv
        import io
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator='\n')
        writer.writerow(['repo', 'workflow', 'job', 'branch', 'runner', 'conclusion',
                         'started', 'completed', 'duration_seconds', 'url'])
        for job in self.jobs(since=since, limit=100000):
            duration = job.get('duration_ms')
            writer.writerow([
                job.get('repo') or '', job.get('workflow') or '', job.get('name') or '',
                job.get('branch') or '', job.get('runner') or '', job.get('conclusion') or '',
                job.get('started') or '', job.get('completed') or '',
                round(duration / 1000) if duration is not None else '',
                job.get('url') or ''])
        return buffer.getvalue()


def load_store(path, enabled=True):
    """Return a HistoryStore, or None when history is disabled or unavailable."""
    if not enabled:
        return None
    try:
        return HistoryStore(path)
    except (OSError, sqlite3.Error):
        return None


def serialise_summary(summary):
    """Return a JSON-safe copy of a summary."""
    return json.loads(json.dumps(summary, default=str))
