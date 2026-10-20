"""Detect newly failed jobs so the console can notify without being watched.

The history database already records every job it has seen, so it can answer
"which failures are new?" exactly. A job keeps the same identity across polls,
so a repeated observation of the same failure is never reported twice.
"""
from desktop_history import FAILED_CONCLUSIONS, job_key


def new_failures(store, jobs):
    """Return the failed jobs in `jobs` that the store has not seen before.

    The reported jobs are recorded as seen, so calling this again with the same
    poll result returns nothing. A job keeps the same identity across polls, so
    a repeated observation of the same failure is never reported twice.
    """
    if store is None:
        return []
    fresh = []
    for job in jobs or []:
        if job.get('status') != 'completed':
            continue
        if job.get('conclusion') not in FAILED_CONCLUSIONS:
            continue
        if store.has_job(job_key(job)):
            continue
        fresh.append(job)
    if fresh:
        try:
            store.record(fresh)
        except Exception:
            pass
    return fresh


def describe(job):
    """Return a one-line, human-readable description of a failed job."""
    repo = (job or {}).get('repo') or 'unknown repository'
    workflow = (job or {}).get('workflow') or 'workflow'
    name = (job or {}).get('name') or 'job'
    return f'{workflow} · {name} failed in {repo}'
