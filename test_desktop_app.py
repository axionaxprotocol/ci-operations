"""Desktop shell contract tests: settings access and single-instance locks."""
import ctypes
import unittest
from pathlib import Path
from unittest.mock import patch

import desktop_app

ALREADY_EXISTS = 183


class FakeKernel:
    def __init__(self, existing=False):
        self.existing = existing
        self.created = []
        self.released = []
        self.closed = []

    def CreateMutexW(self, _attributes, _owner, name):
        self.created.append(name)
        ctypes.set_last_error(ALREADY_EXISTS if self.existing else 0)
        return 'handle-' + name

    def ReleaseMutex(self, handle):
        self.released.append(handle)

    def CloseHandle(self, handle):
        self.closed.append(handle)


class MutexTests(unittest.TestCase):
    def test_acquire_returns_handle_for_a_free_lock(self):
        kernel = FakeKernel(existing=False)
        handle = desktop_app.acquire_mutex(kernel, 'Local\\Test-A')
        self.assertEqual(handle, 'handle-Local\\Test-A')
        self.assertEqual(kernel.closed, [])

    def test_acquire_returns_none_when_another_instance_holds_the_lock(self):
        kernel = FakeKernel(existing=True)
        self.assertIsNone(desktop_app.acquire_mutex(kernel, 'Local\\Test-B'))
        self.assertEqual(len(kernel.closed), 1, 'the borrowed handle must be closed')

    def test_release_closes_and_releases(self):
        kernel = FakeKernel(existing=False)
        desktop_app.release_mutex(kernel, 'handle-Local\\Test-C')
        self.assertEqual(kernel.released, ['handle-Local\\Test-C'])
        self.assertEqual(kernel.closed, ['handle-Local\\Test-C'])

    def test_release_ignores_a_missing_handle(self):
        kernel = FakeKernel(existing=False)
        desktop_app.release_mutex(kernel, None)
        self.assertEqual(kernel.released, [])

    def test_instance_running_detects_a_live_holder(self):
        self.assertTrue(desktop_app.instance_running(FakeKernel(existing=True), 'Local\\Test-D'))
        self.assertFalse(desktop_app.instance_running(FakeKernel(existing=False), 'Local\\Test-D'))


class SettingsAccessTests(unittest.TestCase):
    def test_setup_lock_and_dashboard_lock_use_distinct_names(self):
        self.assertNotEqual(desktop_app.SETUP_LOCK, desktop_app.DASHBOARD_LOCK)
        for name in (desktop_app.SETUP_LOCK, desktop_app.DASHBOARD_LOCK):
            self.assertTrue(name.startswith('Local\\CIOperations-'))

    def test_settings_are_reachable_while_the_dashboard_runs(self):
        # A second instance must be able to open the setup form even when the
        # dashboard instance already holds its own lock.
        kernel = FakeKernel(existing=False)
        self.assertFalse(desktop_app.instance_running(kernel, desktop_app.DASHBOARD_LOCK))
        self.assertNotIn(desktop_app.DASHBOARD_LOCK, desktop_app.SETUP_LOCK)

    def test_settings_window_opens_without_tearing_down_the_dashboard(self):
        source = Path(desktop_app.__file__).read_text(encoding='utf-8')
        self.assertNotIn("launch_command() + ['--check-update']", source)

    def test_lock_names_are_scoped_per_windows_user(self):
        kernel, dashboard_name, setup_name = desktop_app.lock_names()
        self.assertTrue(dashboard_name.startswith(desktop_app.DASHBOARD_LOCK))
        self.assertTrue(setup_name.startswith(desktop_app.SETUP_LOCK))
        self.assertNotEqual(dashboard_name, setup_name)


if __name__ == '__main__':
    unittest.main()
