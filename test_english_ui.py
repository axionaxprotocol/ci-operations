"""Prevent application-authored Thai labels returning in the packaged UI."""
import re
import unittest
from pathlib import Path


class EnglishInterfaceTests(unittest.TestCase):
    def test_runtime_sources_are_english_only(self):
        root = Path(__file__).resolve().parent
        for name in ('desktop_setup.py', 'desktop_app.py', 'desktop_service.py', 'index.html'):
            with self.subTest(file=name):
                self.assertIsNone(re.search(r'[\u0e00-\u0e7f]', (root / name).read_text(encoding='utf-8')),
                                  'Application-owned UI text must be English')


if __name__ == '__main__':
    unittest.main()
