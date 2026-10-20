"""Audit that diagnostic output never records credentials or request headers."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SENSITIVE_LOGGING = re.compile(
    r'LOGGER\.\w+\([^\n]*(?:\bformat\(|\.format\(|repr\(|exc_info|\bheaders\b|Bearer)',
    re.IGNORECASE)


class DiagnosticLoggingTests(unittest.TestCase):
    def test_runtime_modules_do_not_log_credentials_or_exception_locals(self):
        for name in ('ci_dashboard.py', 'desktop_app.py', 'desktop_service.py', 'desktop_setup.py', 'desktop_store.py'):
            text = (ROOT / name).read_text(encoding='utf-8')
            with self.subTest(file=name):
                self.assertIsNone(SENSITIVE_LOGGING.search(text))
                self.assertNotIn('traceback.print_exc', text)

    def test_web_logging_uses_standard_warning_level(self):
        text = (ROOT / 'ci_dashboard.py').read_text(encoding='utf-8')
        self.assertIn('logging.basicConfig', text)
        self.assertNotIn('print("WARNING', text)


if __name__ == '__main__':
    unittest.main()
