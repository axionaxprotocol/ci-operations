"""End-to-end proof that the settings form opens while a dashboard instance runs.

Uses the real Tk setup form and the real Windows named locks, with no network:
the token is validated against a stubbed GitHub API.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import desktop_app
import desktop_setup

ROOT = Path(__file__).resolve().parent


class SettingsWindowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.kernel, self.dashboard_name, self.setup_name = desktop_app.lock_names()
        self.dashboard_handle = desktop_app.acquire_mutex(self.kernel, self.dashboard_name)
        self.assertIsNotNone(self.dashboard_handle, 'the dashboard lock must be acquirable')
        self.addCleanup(desktop_app.release_mutex, self.kernel, self.dashboard_handle)

    def test_setup_window_opens_while_the_dashboard_lock_is_held(self):
        # The setup lock is independent, so the settings form still opens.
        handle = desktop_app.acquire_mutex(self.kernel, self.setup_name)
        self.assertIsNotNone(handle, 'the setup lock must not be blocked by the dashboard lock')
        desktop_app.release_mutex(self.kernel, handle)

    def test_settings_form_renders_and_can_be_cancelled(self):
        report = Path(tempfile.gettempdir()) / 'ci-operations-setup-smoke.json'
        script = (
            'import json, sys\n'
            'sys.path.insert(0, %r)\n'
            'import desktop_app\n'
            'desktop_app.show_setup(smoke_report=%r)\n'
        ) % (str(ROOT), str(report))
        completed = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stderr[-2000:])
        data = json.loads(report.read_text(encoding='utf-8'))
        self.assertTrue(data['native_setup'])
        self.assertTrue(data['english_labels'])
        self.assertTrue(data['paste_button_visible'])
        self.assertTrue(data['masked'], 'the token field must stay masked')
        report.unlink(missing_ok=True)

    def test_dashboard_reloads_credentials_saved_by_another_process(self):
        import desktop_service
        service = desktop_service.DesktopService({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, poll=False)
        try:
            updated = {'token': 'TEST-ONLY-NOT-REAL', 'repos': ['fresh/repo'], 'poll': 30}
            with patch.object(desktop_service, 'load_settings', return_value=updated):
                service.settings_stamp = (service._settings_stamp() or 0) - 1
                service.watch_settings()
            self.assertEqual(desktop_service.dashboard.REPOS, ['fresh/repo'])
        finally:
            service.close()


if __name__ == '__main__':
    unittest.main()
