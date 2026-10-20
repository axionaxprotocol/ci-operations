"""Windows toast notifications, tested without displaying anything."""
import subprocess
import unittest
from unittest.mock import patch

import desktop_notify


class Recorder:
    """Captures the arguments and environment of the notifier call."""

    def __init__(self, returncode=0, stderr=''):
        self.calls = []
        self.returncode = returncode
        self.stderr = stderr

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args, returncode=self.returncode,
                                           stdout='', stderr=self.stderr)

    @property
    def args(self):
        return self.calls[-1][0]

    @property
    def env(self):
        return self.calls[-1][1].get('env') or {}


class ToastTests(unittest.TestCase):
    def test_a_toast_is_raised_for_a_failed_job(self):
        recorder = Recorder()
        with patch.object(desktop_notify.subprocess, 'run', recorder):
            ok = desktop_notify.notify_failure(
                {'repo': 'o/r', 'workflow': 'CI', 'name': 'build', 'url': 'https://github.com/o/r/actions/runs/1'})
        self.assertTrue(ok)
        self.assertEqual(len(recorder.calls), 1)

    def test_the_toast_text_mentions_the_workflow_and_repository(self):
        recorder = Recorder()
        with patch.object(desktop_notify.subprocess, 'run', recorder):
            desktop_notify.notify_failure({'repo': 'o/r', 'workflow': 'CI', 'name': 'build', 'url': ''})
        self.assertIn('CI', recorder.env.get(desktop_notify.TITLE_VARIABLE, ''))
        self.assertIn('o/r', recorder.env.get(desktop_notify.BODY_VARIABLE, ''))

    def test_the_text_travels_in_the_environment_not_on_the_command_line(self):
        recorder = Recorder()
        with patch.object(desktop_notify.subprocess, 'run', recorder):
            desktop_notify.notify_failure({'repo': 'o/r', 'workflow': 'CI', 'name': 'build'})
        joined = ' '.join(str(part) for part in recorder.args)
        self.assertNotIn('CI failed', joined,
                         'the text must not be passed as a command-line argument')
        self.assertIn(desktop_notify.TITLE_VARIABLE, recorder.env)
        self.assertIn(desktop_notify.BODY_VARIABLE, recorder.env)

    def test_a_failure_without_details_still_raises_a_toast(self):
        recorder = Recorder()
        with patch.object(desktop_notify.subprocess, 'run', recorder):
            self.assertTrue(desktop_notify.notify_failure({}))

    def test_a_crashed_notifier_does_not_raise(self):
        with patch.object(desktop_notify.subprocess, 'run', side_effect=OSError('no powershell')):
            self.assertFalse(desktop_notify.notify_failure({'repo': 'o/r'}))

    def test_a_timeout_does_not_raise(self):
        with patch.object(desktop_notify.subprocess, 'run',
                          side_effect=subprocess.TimeoutExpired('powershell', 20)):
            self.assertFalse(desktop_notify.notify_failure({'repo': 'o/r'}))

    def test_a_failing_notifier_is_reported_as_unsuccessful(self):
        recorder = Recorder(returncode=1, stderr='boom')
        with patch.object(desktop_notify.subprocess, 'run', recorder):
            self.assertFalse(desktop_notify.notify_failure({'repo': 'o/r'}))

    def test_notifications_can_be_switched_off(self):
        recorder = Recorder()
        with patch.object(desktop_notify.subprocess, 'run', recorder):
            self.assertFalse(desktop_notify.notify_failure({'repo': 'o/r'}, enabled=False))
        self.assertEqual(recorder.calls, [])

    def test_the_job_url_is_included_when_present(self):
        recorder = Recorder()
        with patch.object(desktop_notify.subprocess, 'run', recorder):
            desktop_notify.notify_failure({'repo': 'o/r', 'workflow': 'CI', 'name': 'build',
                                           'url': 'https://github.com/o/r/actions/runs/42'})
        body = recorder.env.get(desktop_notify.BODY_VARIABLE, '')
        self.assertIn('https://github.com/o/r/actions/runs/42', body)

    def test_the_powershell_command_is_not_interactive(self):
        recorder = Recorder()
        with patch.object(desktop_notify.subprocess, 'run', recorder):
            desktop_notify.notify_failure({'repo': 'o/r'})
        self.assertIn('-NonInteractive', recorder.args)
        self.assertIn('-NoProfile', recorder.args)

    def test_the_toast_script_escapes_the_text_it_embeds(self):
        self.assertIn('SecurityElement]::Escape', desktop_notify.TOAST_SCRIPT)
        self.assertNotIn('$args[0]', desktop_notify.TOAST_SCRIPT)


if __name__ == '__main__':
    unittest.main()
