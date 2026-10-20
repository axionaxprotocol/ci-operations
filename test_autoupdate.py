"""Auto-update contract tests: no network, no real installer execution."""
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import desktop_app

ASSET = [{'name': 'CI-Operations-Setup.exe', 'browser_download_url': 'https://example.invalid/setup.exe'}]
SUMS_ASSET = [{'name': 'SHA256SUMS.txt', 'browser_download_url': 'https://example.invalid/SHA256SUMS.txt'}]


def release(tag, assets):
    return io.BytesIO(json.dumps({'tag_name': tag, 'assets': assets}).encode())


def download_fake(content=b'installer-bytes'):
    def _retrieve(url, target):
        Path(target).write_bytes(content)
    return _retrieve


class AutoUpdateTests(unittest.TestCase):
    def test_updater_module_has_urllib_available(self):
        # Regression: the updater referenced urllib without importing it.
        self.assertTrue(hasattr(desktop_app, 'urllib'))
        self.assertTrue(hasattr(desktop_app.urllib, 'request'))
        self.assertTrue(hasattr(desktop_app.urllib, 'error'))

    def test_already_latest_returns_zero_without_download(self):
        body = release('v' + desktop_app.CURRENT_VERSION, ASSET)
        with patch.object(desktop_app.urllib.request, 'urlopen', return_value=body), \
             patch.object(desktop_app.urllib.request, 'urlretrieve') as download, \
             patch.object(desktop_app.subprocess, 'Popen') as popen:
            self.assertEqual(desktop_app.run_auto_update(), 0)
        download.assert_not_called()
        popen.assert_not_called()

    def test_release_without_installer_asset_fails_safely(self):
        body = release('v99.0.0', SUMS_ASSET)
        with patch.object(desktop_app.urllib.request, 'urlopen', return_value=body), \
             patch.object(desktop_app.subprocess, 'Popen') as popen:
            self.assertEqual(desktop_app.run_auto_update(), 1)
        popen.assert_not_called()

    def test_newer_release_schedules_detached_install(self):
        content = b'installer-bytes'
        digest = hashlib.sha256(content).hexdigest()
        sums = io.BytesIO(f'{digest}  CI-Operations-Setup.exe\n'.encode())
        with patch.object(desktop_app.urllib.request, 'urlopen', side_effect=[release('v99.0.0', ASSET + SUMS_ASSET), sums]), \
             patch.object(desktop_app.urllib.request, 'urlretrieve', side_effect=download_fake(content)), \
             patch.object(desktop_app.subprocess, 'Popen') as popen, \
             patch.object(desktop_app.subprocess, 'run') as run:
            self.assertEqual(desktop_app.run_auto_update(), 2)
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

    def test_checksum_mismatch_aborts_before_installing(self):
        sums = io.BytesIO(b'0' * 64 + b'  CI-Operations-Setup.exe\n')
        with patch.object(desktop_app.urllib.request, 'urlopen', side_effect=[release('v99.0.0', ASSET + SUMS_ASSET), sums]), \
             patch.object(desktop_app.urllib.request, 'urlretrieve', side_effect=download_fake(b'tampered')), \
             patch.object(desktop_app.subprocess, 'Popen') as popen:
            self.assertEqual(desktop_app.run_auto_update(), 1)
        popen.assert_not_called()

    def test_missing_checksums_aborts_before_installing(self):
        with patch.object(desktop_app.urllib.request, 'urlopen', side_effect=[release('v99.0.0', ASSET)]), \
             patch.object(desktop_app.urllib.request, 'urlretrieve', side_effect=download_fake()), \
             patch.object(desktop_app.subprocess, 'Popen') as popen:
            self.assertEqual(desktop_app.run_auto_update(), 1)
        popen.assert_not_called()

    def test_network_failure_returns_error_without_leaking(self):
        with patch.object(desktop_app.urllib.request, 'urlopen',
                          side_effect=desktop_app.urllib.error.URLError('offline')):
            self.assertEqual(desktop_app.run_auto_update(), 1)

    def test_latest_release_version_returns_tag_without_prefix(self):
        body = release('v9.9.9', ASSET)
        with patch.object(desktop_app.urllib.request, 'urlopen', return_value=body):
            self.assertEqual(desktop_app.latest_release_version(), '9.9.9')

    def test_latest_release_version_returns_none_on_failure(self):
        with patch.object(desktop_app.urllib.request, 'urlopen',
                          side_effect=desktop_app.urllib.error.URLError('offline')):
            self.assertIsNone(desktop_app.latest_release_version())


class ChecksumHelperTests(unittest.TestCase):
    def test_parse_sums_finds_matching_entry(self):
        other = 'a' * 64
        wanted = 'b' * 64
        text = f'{other}  other.zip\r\n{wanted} *CI-Operations-Setup.exe\r\n'
        self.assertEqual(desktop_app.parse_checksums(text).get('CI-Operations-Setup.exe'), wanted)

    def test_sha256_file_matches_hashlib(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'f.bin'
            p.write_bytes(b'abc')
            self.assertEqual(desktop_app.sha256_file(p), hashlib.sha256(b'abc').hexdigest())


if __name__ == '__main__':
    unittest.main()
