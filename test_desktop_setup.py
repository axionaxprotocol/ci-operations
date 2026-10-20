import io
import unittest
import urllib.error
from unittest.mock import patch

import desktop_setup as setup


class SetupTests(unittest.TestCase):
    def test_the_settings_form_offers_a_notification_choice(self):
        source = open(setup.__file__, encoding='utf-8').read()
        self.assertIn('Notify me when a job fails', source)
        self.assertIn('notifications', source)

    def test_the_saved_settings_include_the_notification_choice(self):
        source = open(setup.__file__, encoding='utf-8').read()
        self.assertIn("'notifications': notify.get()", source)

    def test_the_settings_window_is_tall_enough_for_its_action_row(self):
        """The action row must not be clipped by the bottom of the window."""
        source = open(setup.__file__, encoding='utf-8').read()
        self.assertIn("root.geometry('760x730')", source)
        self.assertIn('root.minsize(720, 700)', source)

    def test_the_smoke_report_detects_a_clipped_action_row(self):
        source = open(setup.__file__, encoding='utf-8').read()
        self.assertIn('buttons_bottom', source)
        self.assertIn('save_button_visible', source)

    def test_public_first_run_does_not_prefill_private_repositories(self):
        self.assertEqual(setup.DEFAULT_REPOS, '')

    def test_token_validation_uses_github_only(self):
        with patch.object(setup.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"workflow_runs":[]}')) as call:
            setup.validate_access('TEST-ONLY-NOT-REAL', ['owner/repo'])
            request = call.call_args.args[0]
            self.assertTrue(request.full_url.startswith('https://api.github.com/repos/owner/repo/actions/runs?'))
            self.assertEqual(request.get_header('Authorization'), 'Bearer TEST-ONLY-NOT-REAL')

    def test_unauthorized_error_does_not_echo_token(self):
        token = 'TEST-ONLY-NOT-REAL'
        error = urllib.error.HTTPError('https://api.github.com', 401, token, {}, None)
        with patch.object(setup.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaises(setup.ValidationError) as caught:
                setup.validate_access(token, ['owner/repo'])
        self.assertNotIn(token, str(caught.exception))

    def test_auth_is_not_forwarded_by_default_redirect_handler(self):
        with patch.object(setup.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"workflow_runs":[]}')) as call:
            setup.validate_access('TEST-ONLY-NOT-REAL', ['owner/repo'])
            original = call.call_args.args[0]
        redirected = setup.urllib.request.HTTPRedirectHandler().redirect_request(
            original, None, 302, 'Found', {}, 'https://different.example/path')
        self.assertIsNone(redirected.get_header('Authorization'))

    def test_invalid_token_is_rejected_before_network(self):
        with patch.object(setup.urllib.request, 'urlopen') as call:
            for token in ('', 'abc\r\nx: y'):
                with self.assertRaises(setup.ValidationError):
                    setup.validate_access(token, ['owner/repo'])
            call.assert_not_called()


class NativePasteTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from tkinter import ttk
        self.root = tk.Tk()
        self.root.withdraw()
        self.status = tk.StringVar(self.root)
        self.entry = ttk.Entry(self.root, show='*')

    def tearDown(self):
        self.root.destroy()

    def test_paste_replaces_field_and_trims_copied_line_endings(self):
        support = setup.TokenPasteSupport(self.entry, self.status)
        self.entry.insert(0, 'old-test-value')
        with patch.object(self.entry, 'clipboard_get', return_value='  TEST-ONLY-NOT-REAL\r\n'):
            self.assertEqual(support.paste(), 'break')
        self.assertEqual(self.entry.get(), 'TEST-ONLY-NOT-REAL')
        self.assertEqual(self.entry.cget('show'), '*')

    def test_physical_ctrl_v_does_not_depend_on_english_keysym(self):
        from types import SimpleNamespace
        support = setup.TokenPasteSupport(self.entry, self.status)
        with patch.object(self.entry, 'clipboard_get', return_value='TEST-ONLY-NOT-REAL'):
            result = support.on_key(SimpleNamespace(keycode=0x56, state=0x4, keysym='Thai_oang'))
        self.assertEqual(result, 'break')
        self.assertEqual(self.entry.get(), 'TEST-ONLY-NOT-REAL')

    def test_unavailable_clipboard_is_safe_and_preserves_field(self):
        import tkinter as tk
        support = setup.TokenPasteSupport(self.entry, self.status)
        self.entry.insert(0, 'existing-test-value')
        with patch.object(self.entry, 'clipboard_get', side_effect=tk.TclError('unavailable')):
            support.paste()
        self.assertEqual(self.entry.get(), 'existing-test-value')
        self.assertIn('clipboard', self.status.get().lower())

    def test_native_paste_event_uses_the_safe_clipboard_provider(self):
        setup.TokenPasteSupport(self.entry, self.status)
        self.entry.pack()
        self.root.deiconify()
        self.root.update()
        self.entry.focus_force()
        with patch.object(self.entry, 'clipboard_get', return_value='TEST-ONLY-NOT-REAL'):
            self.entry.event_generate('<<Paste>>')
            self.root.update()
        self.assertEqual(self.entry.get(), 'TEST-ONLY-NOT-REAL')

    def test_native_ctrl_v_event_pastes_without_reading_the_os_clipboard(self):
        setup.TokenPasteSupport(self.entry, self.status)
        self.entry.pack()
        self.root.deiconify()
        self.root.update()
        self.entry.focus_force()
        self.root.update()
        with patch.object(self.entry, 'clipboard_get', return_value='TEST-ONLY-NOT-REAL'):
            self.entry.event_generate('<KeyPress>', keycode=0x56, state=0x4)
            self.root.update()
        self.assertEqual(self.entry.get(), 'TEST-ONLY-NOT-REAL')

    def test_virtual_paste_and_context_menu_are_bound(self):
        setup.TokenPasteSupport(self.entry, self.status)
        self.assertTrue(self.entry.bind('<<Paste>>'))
        self.assertTrue(self.entry.bind('<Button-3>'))


if __name__ == '__main__':
    unittest.main()
