import http.client
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import desktop_history
import desktop_service
import ci_dashboard as dashboard


class ServiceTests(unittest.TestCase):
    def test_missing_token_cannot_start_dashboard(self):
        with self.assertRaises(ValueError):
            desktop_service.DesktopService({'token': '', 'repos': ['o/r']}, poll=False)

    def test_consumed_poller_error_is_sanitized(self):
        from unittest.mock import patch
        service = desktop_service.DesktopService({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, poll=False)
        service.start()
        def failed_poll():
            desktop_service.dashboard.STATE['error'] = 'TEST-ONLY-NOT-REAL internal error'
            service.stop.set()
        try:
            with patch.object(desktop_service.dashboard, 'poll_once', side_effect=failed_poll):
                service._poll()
            self.assertNotIn('TEST-ONLY-NOT-REAL', desktop_service.dashboard.STATE['error'])
        finally:
            service.close()

    def test_non_ascii_cookie_is_rejected_cleanly(self):
        import http.client
        import socket
        service = desktop_service.DesktopService({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, poll=False)
        service.start()
        try:
            with socket.create_connection(('127.0.0.1', service.server.server_port), timeout=5) as connection:
                connection.sendall(('GET /api/state HTTP/1.1\r\nHost: ' + service.host +
                                    '\r\nCookie: ' + service.cookie + '=ทุจริต\r\nConnection: close\r\n\r\n').encode())
                response = http.client.HTTPResponse(connection)
                response.begin()
                self.assertEqual(response.status, 401)
                response.close()
        finally:
            service.close()

    def test_mutating_http_methods_are_rejected(self):
        import http.client
        service = desktop_service.DesktopService({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, poll=False)
        service.start()
        try:
            for method in ('POST', 'PUT', 'DELETE', 'PATCH'):
                with self.subTest(method=method):
                    connection = http.client.HTTPConnection('127.0.0.1', service.server.server_port, timeout=5)
                    connection.request(method, '/api/state', body='x')
                    response = connection.getresponse()
                    response.read()
                    self.assertEqual(response.status, 405)
                    connection.close()
        finally:
            service.close()

    def test_settings_watcher_reloads_credentials_saved_elsewhere(self):
        from unittest.mock import patch
        service = desktop_service.DesktopService({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, poll=False)
        try:
            updated = {'token': 'TEST-ONLY-NOT-REAL', 'repos': ['other/repo'], 'poll': 30}
            with patch.object(desktop_service, 'load_settings', return_value=updated), \
                 patch.object(service, '_settings_stamp', return_value=2):
                service.settings_stamp = 1
                service.watch_settings()
            self.assertEqual(desktop_service.dashboard.REPOS, ['other/repo'])
            self.assertEqual(desktop_service.dashboard.TOKEN, 'TEST-ONLY-NOT-REAL')
        finally:
            service.close()

    def test_settings_watcher_ignores_unchanged_files(self):
        from unittest.mock import patch
        service = desktop_service.DesktopService({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, poll=False)
        try:
            with patch.object(desktop_service, 'load_settings') as loader:
                service.settings_stamp = 1
                with patch.object(service, '_settings_stamp', return_value=1):
                    service.watch_settings()
            loader.assert_not_called()
        finally:
            service.close()

    def test_removing_the_settings_file_clears_the_token(self):
        from unittest.mock import patch
        service = desktop_service.DesktopService({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, poll=False)
        try:
            with patch.object(service, '_settings_stamp', return_value=None):
                service.settings_stamp = 12345
                service.watch_settings()
            self.assertEqual(desktop_service.dashboard.TOKEN, '')
            self.assertEqual(desktop_service.dashboard.REPOS, [])
            self.assertIn('removed', desktop_service.dashboard.STATE['error'])
        finally:
            service.close()

    def test_history_endpoint_requires_the_session_cookie(self):
        service = desktop_service.DesktopService({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, poll=False)
        service.start()
        try:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(service.origin + '/api/history')
            self.assertEqual(caught.exception.code, 401)
            caught.exception.close()
        finally:
            service.close()

    def test_history_endpoint_returns_a_summary_and_the_stored_jobs(self):
        service = desktop_service.DesktopService({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, poll=False)
        # Use an isolated store so the machine's real history cannot change the result.
        isolated = tempfile.TemporaryDirectory()
        self.addCleanup(isolated.cleanup)
        service.history = desktop_history.HistoryStore(Path(isolated.name) / 'history.db')
        self.addCleanup(service.history.close)
        service.start()
        try:
            service.history.record([{
                'repo': 'o/r', 'run_id': 1, 'job_id': 5, 'name': 'build', 'workflow': 'CI',
                'status': 'completed', 'conclusion': 'success', 'started': '2026-10-20T10:00:00Z',
                'completed': '2026-10-20T10:01:00Z', 'steps': []}])
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
            with opener.open(service.launch_url) as response:
                response.read()
            with opener.open(service.origin + '/api/history') as response:
                data = json.load(response)
            self.assertEqual(data['summary']['total'], 1)
            self.assertEqual(data['summary']['success_rate'], 100)
            self.assertEqual(len(data['jobs']), 1)
            self.assertEqual(data['jobs'][0]['workflow'], 'CI')
        finally:
            service.close()

    def test_history_csv_endpoint_returns_csv_text(self):
        service = desktop_service.DesktopService({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, poll=False)
        service.start()
        try:
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
            with opener.open(service.launch_url) as response:
                response.read()
            with opener.open(service.origin + '/api/history.csv') as response:
                body = response.read().decode('utf-8')
            self.assertTrue(body.startswith('repo,workflow,job'))
        finally:
            service.close()

    def test_history_window_header_selects_the_recorded_period(self):
        self.assertEqual(desktop_service._window_seconds('24h'), 24 * 3600)
        self.assertEqual(desktop_service._window_seconds('7d'), 7 * 24 * 3600)
        self.assertEqual(desktop_service._window_seconds('all'), 0)
        self.assertEqual(desktop_service._window_seconds('nonsense'), 0)

    def test_history_query_window_is_read_from_the_url(self):
        self.assertEqual(desktop_service._query_window('/api/history.csv?window=30d'), '30d')
        self.assertEqual(desktop_service._query_window('/api/history'), '')

    def test_history_endpoints_reject_mutating_methods(self):
        service = desktop_service.DesktopService({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, poll=False)
        service.start()
        try:
            connection = http.client.HTTPConnection('127.0.0.1', service.server.server_port, timeout=5)
            connection.request('POST', '/api/history', body='x')
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 405)
            connection.close()
        finally:
            service.close()


    def test_history_is_pruned_during_a_watch_cycle(self):
        service = desktop_service.DesktopService({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, poll=False)
        try:
            calls = []
            with patch.object(service.history, 'prune', side_effect=lambda *a, **k: calls.append(a)):
                service.prune_history()
            self.assertEqual(len(calls), 1, 'the history was not pruned')
        finally:
            service.close()

    def test_pruning_is_safe_when_history_is_disabled(self):
        service = desktop_service.DesktopService({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, poll=False)
        service.history = None
        try:
            self.assertEqual(service.prune_history(), 0)
        finally:
            service.close()

    def test_history_endpoint_caps_the_number_of_returned_jobs(self):
        service = desktop_service.DesktopService({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, poll=False)
        isolated = tempfile.TemporaryDirectory()
        self.addCleanup(isolated.cleanup)
        service.history = desktop_history.HistoryStore(Path(isolated.name) / 'history.db')
        self.addCleanup(service.history.close)
        service.start()
        try:
            for index in range(60):
                service.history.record([{
                    'repo': 'o/r', 'run_id': index, 'job_id': index, 'name': f'job{index}',
                    'workflow': 'CI', 'status': 'completed', 'conclusion': 'success',
                    'started': '2026-10-20T10:00:00Z', 'completed': '2026-10-20T10:01:00Z',
                    'steps': []}])
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
            with opener.open(service.launch_url) as response:
                response.read()
            with opener.open(service.origin + '/api/history') as response:
                data = json.load(response)
            self.assertLessEqual(len(data['jobs']), 50, 'the history payload was not capped')
            self.assertEqual(data['summary']['total'], 60, 'the summary must count every job')
        finally:
            service.close()

    def test_the_service_raises_a_toast_for_a_newly_failed_job(self):
        service = desktop_service.DesktopService({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, poll=False)
        isolated = tempfile.TemporaryDirectory()
        self.addCleanup(isolated.cleanup)
        service.history = desktop_history.HistoryStore(Path(isolated.name) / 'history.db')
        self.addCleanup(service.history.close)
        calls = []
        try:
            with patch('desktop_service.notify_new_failures',
                       side_effect=lambda store, jobs, enabled=True: calls.append(jobs) or True):
                dashboard.STATE['jobs'] = [{
                    'repo': 'o/r', 'run_id': 1, 'job_id': 10, 'name': 'build', 'workflow': 'CI',
                    'status': 'completed', 'conclusion': 'failure', 'steps': []}]
                service.raise_failure_notifications()
            self.assertEqual(len(calls), 1)
        finally:
            dashboard.STATE['jobs'] = []
            service.close()

    def test_notifications_are_off_when_the_setting_says_so(self):
        service = desktop_service.DesktopService(
            {'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r'], 'notifications': False}, poll=False)
        self.assertFalse(service.notifications_enabled)
        service.close()

    def test_notifications_are_on_by_default(self):
        service = desktop_service.DesktopService({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, poll=False)
        self.assertTrue(service.notifications_enabled)
        service.close()

    def test_applying_settings_updates_the_notification_toggle(self):
        service = desktop_service.DesktopService({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, poll=False)
        try:
            service.apply_settings({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r'], 'notifications': False})
            self.assertFalse(service.notifications_enabled)
        finally:
            service.close()

    def test_session_gate_and_cleanup(self):
        service = desktop_service.DesktopService({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['o/r']}, poll=False)
        service.start()
        try:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(service.origin + '/api/state')
            self.assertEqual(caught.exception.code, 401)
            caught.exception.close()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
            with opener.open(service.launch_url) as response:
                self.assertIn(b'CI Operations', response.read())
            with opener.open(service.origin + '/api/state') as response:
                data = json.load(response)
                self.assertIn('jobs', data)
                self.assertNotIn('TEST-ONLY-NOT-REAL', json.dumps(data))
            request = urllib.request.Request(service.origin + '/api/state', headers={'Origin': 'https://evil.example'})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                opener.open(request)
            self.assertEqual(caught.exception.code, 403)
            caught.exception.close()
        finally:
            service.close()
        self.assertFalse(service.thread.is_alive())


if __name__ == '__main__':
    unittest.main()
