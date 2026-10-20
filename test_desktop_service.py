import json
import unittest
import urllib.error
import urllib.request

import desktop_service


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
