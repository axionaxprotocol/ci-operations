"""Detection of newly failed jobs, used to raise Windows notifications."""
import tempfile
import unittest
from pathlib import Path

import desktop_alerts
from desktop_history import HistoryStore


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
        self.store = HistoryStore(Path(self.directory.name) / 'history.db')
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

    def test_a_different_job_is_a_new_failure(self):
        desktop_alerts.new_failures(self.store, [job(job_id=10)])
        fresh = desktop_alerts.new_failures(self.store, [job(job_id=11)])
        self.assertEqual(len(fresh), 1)
        self.assertEqual(fresh[0]['job_id'], 11)

    def test_no_store_means_no_failures(self):
        self.assertEqual(desktop_alerts.new_failures(None, [job()]), [])

    def test_every_failure_conclusion_is_detected(self):
        for conclusion in ('failure', 'timed_out', 'action_required', 'startup_failure'):
            fresh = desktop_alerts.new_failures(self.store, [job(job_id=hash(conclusion) % 1000,
                                                                 conclusion=conclusion)])
            self.assertEqual(len(fresh), 1, conclusion)

    def test_the_description_mentions_the_workflow_and_repository(self):
        text = desktop_alerts.describe(job())
        self.assertIn('CI', text)
        self.assertIn('o/r', text)

    def test_the_description_copes_with_missing_fields(self):
        text = desktop_alerts.describe({})
        self.assertTrue(text)


if __name__ == '__main__':
    unittest.main()
