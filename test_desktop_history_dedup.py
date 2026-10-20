"""Steps must be recorded once per job, not once per poll."""
import sqlite3
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

    def test_steps_without_a_number_are_still_deduplicated(self):
        without_number = job()
        without_number['steps'][0]['number'] = None
        self.store.record([without_number])
        self.store.record([without_number])
        self.assertEqual(len(self.store.steps_for(['o/r:1:10'])), 1)

    def test_a_legacy_database_is_migrated_and_deduplicated(self):
        legacy = Path(self.directory.name) / 'legacy.db'
        connection = sqlite3.connect(str(legacy))
        connection.executescript(
            'CREATE TABLE steps ('
            'id INTEGER PRIMARY KEY AUTOINCREMENT, job_key TEXT NOT NULL, name TEXT, '
            'conclusion TEXT, number INTEGER, started TEXT, completed TEXT, '
            'duration_ms INTEGER, recorded_at REAL NOT NULL);')
        # A legacy database holds one copy of the same step per poll.
        for index in range(4):
            connection.execute(
                'INSERT INTO steps (job_key,name,conclusion,number,started,completed,duration_ms,recorded_at) '
                'VALUES (?,?,?,?,?,?,?,?)',
                ('o/r:1:10', 'install', 'failure', 1, '2026-10-20T10:00:00Z',
                 '2026-10-20T10:00:30Z', 30000, 1.0 + index))
        connection.commit()
        connection.close()

        store = desktop_history.HistoryStore(legacy)
        self.addCleanup(store.close)
        steps = store.steps_for(['o/r:1:10'])
        self.assertEqual(len(steps), 1, 'the legacy duplicate rows were not collapsed')
        self.assertEqual(steps[0]['name'], 'install')

    def test_migrating_twice_is_harmless(self):
        legacy = Path(self.directory.name) / 'twice.db'
        connection = sqlite3.connect(str(legacy))
        connection.executescript(
            'CREATE TABLE steps ('
            'id INTEGER PRIMARY KEY AUTOINCREMENT, job_key TEXT NOT NULL, name TEXT, '
            'conclusion TEXT, number INTEGER, started TEXT, completed TEXT, '
            'duration_ms INTEGER, recorded_at REAL NOT NULL);')
        connection.execute(
            'INSERT INTO steps (job_key,name,conclusion,number,started,completed,duration_ms,recorded_at) '
            'VALUES (?,?,?,?,?,?,?,?)',
            ('o/r:1:10', 'install', 'failure', 1, '2026-10-20T10:00:00Z',
             '2026-10-20T10:00:30Z', 30000, 1.0))
        connection.commit()
        connection.close()

        store = desktop_history.HistoryStore(legacy)
        store._migrate_steps()
        store._migrate_steps()
        self.addCleanup(store.close)
        self.assertEqual(len(store.steps_for(['o/r:1:10'])), 1)


if __name__ == '__main__':
    unittest.main()
