"""Tests for the durable job history store."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

import desktop_history


def job(**overrides):
    base = {
        'repo': 'o/r', 'run_id': 1, 'job_id': 10, 'name': 'build', 'workflow': 'CI',
        'branch': 'main', 'conclusion': 'success', 'status': 'completed',
        'runner': 'w1', 'sha': 'abc1234', 'url': 'https://github.com/o/r/actions/runs/1',
        'created': '2026-10-20T10:00:00Z', 'started': '2026-10-20T10:00:10Z',
        'completed': '2026-10-20T10:05:10Z', 'steps': [],
    }
    base.update(overrides)
    return base


class HistoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'history.db'
        self.store = desktop_history.HistoryStore(self.path)
        # Cleanups run last-in-first-out, so the directory is removed only after
        # every database handle has been closed.
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.store.close)

    def test_completed_jobs_are_stored_and_survive_a_restart(self):
        self.store.record([job()])
        self.store.close()
        reopened = desktop_history.HistoryStore(self.path)
        self.addCleanup(reopened.close)
        rows = reopened.jobs()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['workflow'], 'CI')
        self.assertEqual(rows[0]['duration_ms'], 300000)

    def test_running_jobs_are_not_stored(self):
        self.store.record([job(status='in_progress', conclusion=None)])
        self.assertEqual(self.store.jobs(), [])

    def test_the_same_job_is_not_stored_twice(self):
        self.store.record([job()])
        self.store.record([job()])
        self.assertEqual(len(self.store.jobs()), 1)

    def test_distinct_jobs_are_both_stored(self):
        self.store.record([job()])
        self.store.record([job(run_id=2, job_id=11)])
        self.assertEqual(len(self.store.jobs()), 2)

    def test_summary_reports_success_rate_and_failures(self):
        self.store.record([job(), job(job_id=11, conclusion='failure')])
        summary = self.store.summary()
        self.assertEqual(summary['total'], 2)
        self.assertEqual(summary['failed'], 1)
        self.assertEqual(summary['successes'], 1)
        self.assertEqual(summary['success_rate'], 50)

    def test_summary_without_data_has_no_success_rate(self):
        self.assertIsNone(self.store.summary()['success_rate'])

    def test_failing_steps_are_ranked_by_frequency(self):
        install_step = {'name': 'install', 'conclusion': 'failure', 'number': 1,
                        'started': '2026-10-20T10:00:10Z', 'completed': '2026-10-20T10:01:10Z'}
        test_step = {'name': 'test', 'conclusion': 'success', 'number': 2,
                     'started': '2026-10-20T10:01:10Z', 'completed': '2026-10-20T10:05:10Z'}
        self.store.record([
            job(job_id=11, conclusion='failure', steps=[install_step, test_step]),
            job(job_id=12, conclusion='failure', steps=[install_step]),
        ])
        summary = self.store.summary()
        self.assertEqual(summary['failed'], 2)
        self.assertEqual(summary['failing_steps'][0]['step'], 'install')
        self.assertEqual(summary['failing_steps'][0]['failed'], 2)

    def test_workflow_breakdown_ranks_the_worst_offender_first(self):
        self.store.record([
            job(job_id=11, workflow='Deploy', conclusion='failure'),
            job(job_id=12, workflow='Deploy', conclusion='failure'),
            job(job_id=13, workflow='Tests', conclusion='success'),
        ])
        workflows = self.store.summary()['workflows']
        self.assertEqual(workflows[0]['workflow'], 'Deploy')
        self.assertEqual(workflows[0]['failed'], 2)
        self.assertEqual(workflows[0]['success_rate'], 0)

    def test_prune_removes_old_records(self):
        self.store.record([job()])
        self.store.prune(max_age_seconds=-1)
        self.assertEqual(self.store.jobs(), [])

    def test_export_json_includes_the_steps_of_each_job(self):
        self.store.record([job(steps=[
            {'name': 'install', 'conclusion': 'failure', 'number': 1,
             'started': '2026-10-20T10:00:10Z', 'completed': '2026-10-20T10:01:10Z'}])])
        exported = self.store.export_json()
        self.assertEqual(len(exported['jobs']), 1)
        self.assertEqual(exported['jobs'][0]['steps'][0]['name'], 'install')

    def test_export_csv_has_a_header_and_one_row_per_job(self):
        self.store.record([job(), job(job_id=11, conclusion='failure')])
        csv_text = self.store.export_csv()
        lines = csv_text.strip().split('\n')
        self.assertEqual(lines[0], 'repo,workflow,job,branch,runner,conclusion,started,completed,duration_seconds,url')
        self.assertEqual(len(lines), 3)
        self.assertIn('o/r,CI,build', lines[1])

    def test_csv_export_escapes_values_that_contain_commas(self):
        self.store.record([job(branch='feature,with-comma')])
        csv_text = self.store.export_csv()
        self.assertIn('"feature,with-comma"', csv_text)

    def test_jobs_can_be_filtered_by_repository(self):
        self.store.record([job(repo='o/a'), job(repo='o/b', job_id=11)])
        self.assertEqual(len(self.store.jobs(repo='o/a')), 1)

    def test_median_and_p95_durations_are_reported(self):
        self.store.record([
            job(job_id=11, started='2026-10-20T10:00:00Z', completed='2026-10-20T10:01:00Z'),
            job(job_id=12, started='2026-10-20T10:00:00Z', completed='2026-10-20T10:02:00Z'),
            job(job_id=13, started='2026-10-20T10:00:00Z', completed='2026-10-20T10:03:00Z'),
        ])
        summary = self.store.summary()
        self.assertEqual(summary['median_duration_ms'], 120000)
        self.assertEqual(summary['p95_duration_ms'], 180000)


class HelperTests(unittest.TestCase):
    def test_job_key_uses_repository_run_and_job_identity(self):
        self.assertEqual(desktop_history.job_key(job()), 'o/r:1:10')

    def test_job_key_falls_back_to_name_and_time(self):
        key = desktop_history.job_key({'repo': 'o/r', 'name': 'x', 'completed': '2026-10-20T10:00:00Z'})
        self.assertTrue(key.startswith('o/r:x:'))

    def test_invalid_timestamps_do_not_raise(self):
        self.assertIsNone(desktop_history._timestamp('not-a-date'))
        self.assertIsNone(desktop_history._timestamp(None))

    def test_load_store_returns_none_when_disabled(self):
        self.assertIsNone(desktop_history.load_store('unused.db', enabled=False))

    def test_load_store_creates_a_usable_store(self):
        with tempfile.TemporaryDirectory() as directory:
            store = desktop_history.load_store(Path(directory) / 'h.db')
            self.assertIsInstance(store, desktop_history.HistoryStore)
            store.close()


if __name__ == '__main__':
    unittest.main()
