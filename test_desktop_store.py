import json
import tempfile
import unittest
from pathlib import Path

import desktop_store as store


class StoreTests(unittest.TestCase):
    def test_token_roundtrip_is_encrypted_at_rest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.dat'
            token = 'TEST-ONLY-NOT-A-REAL-GITHUB-TOKEN'
            store.save_settings({'token': token, 'repos': ['owner/repo']}, path)
            self.assertNotIn(token.encode(), path.read_bytes())
            self.assertEqual(store.load_settings(path)['token'], token)

    def test_tampered_settings_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.dat'
            path.write_bytes(b'not-encrypted-settings')
            with self.assertRaises(store.SettingsError):
                store.load_settings(path)

    def test_missing_settings_requires_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(store.load_settings(Path(directory) / 'missing'))

    def test_notification_toggle_survives_the_roundtrip(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.dat'
            store.save_settings({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r'],
                                 'notifications': False}, path=path)
            loaded = store.load_settings(path=path)
            self.assertIs(loaded['notifications'], False)

    def test_missing_notification_toggle_defaults_to_enabled(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.dat'
            store.save_settings({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, path=path)
            loaded = store.load_settings(path=path)
            self.assertNotIn('notifications', loaded)

    def test_repo_validation_rejects_urls_and_paths(self):
        self.assertEqual(store.parse_repos(' owner/a, owner/b '), ['owner/a', 'owner/b'])
        for value in ('https://github.com/a/b', 'a/../../b', 'a/b?x=1', ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                store.parse_repos(value)


if __name__ == '__main__':
    unittest.main()
