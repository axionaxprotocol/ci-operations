"""Auto-update contract tests: no network, no real installer execution."""
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import desktop_app


def release(tag, assets):
    return io.BytesIO(json.dumps({'tag_name': tag, 'assets': assets}).encode())


class AutoUpdateTests(unittest.TestCase):
    def test_updater_module_has_urllib_available(self):
        # Regression: the updater referenced urllib without importing it.
        self.assertTrue(hasattr(desktop_app, 'urllib'))
        self.assertTrue(hasattr(desktop_app.urllib, 'request'))
        self.assertTrue(hasattr(desktop_app.urllib, 'error'))

    def test_already_latest_returns_zero_without_download(self):
        body = release('v' + desktop_app.CURRENT_VERSION,
                       [{'name': 'CI-Operations-Setup.exe', 'browser_download_url': 'https://example.invalid/x.exe'}])
        with patch.object(desktop_app.urllib.request, 'urlopen', return_value=body), \
             patch.object(desktop_app.urllib.request, 'urlretrieve') as download, \
             patch.object(desktop_app.subprocess, 'run') as run:
            self.assertEqual(desktop_app.run_auto_update(), 0)
        download.assert_not_called()
        run.assert_not_called()

    def test_newer_release_downloads_and_schedules_detached_install(self):
        body = release('v99.0.0',
                       [{'name': 'CI-Operations-Setup.exe', 'browser_download_url': 'https://example.invalid/setup.exe'}])
        with patch.object(desktop_app.urllib.request, 'urlopen', return_value=body), \
             patch.object(desktop_app.urllib.request, 'urlretrieve') as download, \
             patch.object(desktop_app.subprocess, 'Popen') as popen, \
             patch.object(desktop_app.subprocess, 'run') as run:
            self.assertEqual(desktop_app.run_auto_update(), 2)
        download.assert_called_once()
        # The installer must not run while this process still holds its own files open.
        run.assert_not_called()
        popen.assert_called_once()
        args = popen.call_args.args[0]
        self.assertEqual(args[0], 'cmd.exe')
        batch = Path(args[2])
        self.assertTrue(batch.is_file(), 'detached update helper was not written')
        script = batch.read_text(encoding='utf-8')
        self.assertIn('/VERYSILENT', script)
        self.assertIn('/NORESTART', script)
        self.assertIn('/SUPPRESSMSGBOXES', script)

    def test_release_without_installer_asset_fails_safely(self):
        body = release('v99.0.0', [{'name': 'SHA256SUMS.txt', 'browser_download_url': 'https://example.invalid/s.txt'}])
        with patch.object(desktop_app.urllib.request, 'urlopen', return_value=body), \
             patch.object(desktop_app.subprocess, 'run') as run:
            self.assertEqual(desktop_app.run_auto_update(), 1)
        run.assert_not_called()

    def test_network_failure_returns_error_without_leaking(self):
        with patch.object(desktop_app.urllib.request, 'urlopen',
                          side_effect=desktop_app.urllib.error.URLError('offline')):
            self.assertEqual(desktop_app.run_auto_update(), 1)

    def test_latest_release_version_returns_tag_without_prefix(self):
        body = release('v9.9.9', [{'name': 'CI-Operations-Setup.exe', 'browser_download_url': 'https://x.invalid/a.exe'}])
        with patch.object(desktop_app.urllib.request, 'urlopen', return_value=body):
            self.assertEqual(desktop_app.latest_release_version(), '9.9.9')

    def test_latest_release_version_returns_none_on_failure(self):
        with patch.object(desktop_app.urllib.request, 'urlopen',
                          side_effect=desktop_app.urllib.error.URLError('offline')):
            self.assertIsNone(desktop_app.latest_release_version())


if __name__ == '__main__':
    unittest.main()
