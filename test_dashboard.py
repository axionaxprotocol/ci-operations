import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import ci_dashboard as app


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), app.H)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_unknown_route_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.url + '/api/state-extra')
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()

    def test_state_is_json_with_security_headers(self):
        with urllib.request.urlopen(self.url + '/api/state?refresh=1') as response:
            self.assertIn('jobs', json.load(response))
            self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')


class ApiTests(unittest.TestCase):
    def test_authorization_is_not_forwarded_on_redirect(self):
        import io
        from email.message import Message
        response = io.BytesIO(b'{}')
        response.headers = Message()
        with patch.object(app, 'TOKEN', 'TEST-ONLY-NOT-REAL'), patch.object(app.urllib.request, 'urlopen', return_value=response) as call:
            app.gh('/test-redirect')
            request = call.call_args.args[0]
        redirected = app.urllib.request.HTTPRedirectHandler().redirect_request(
            request, None, 302, 'Found', {}, 'https://different.example/path')
        self.assertIsNone(redirected.get_header('Authorization'))

    def test_cache_is_bounded(self):
        import io
        from email.message import Message
        original = dict(app._cache)
        try:
            app._cache.clear()
            app._cache.update({f'/old/{i}': {} for i in range(512)})
            response = io.BytesIO(b'{}')
            response.headers = Message()
            with patch.object(app.urllib.request, 'urlopen', return_value=response):
                app.gh('/new')
            self.assertLessEqual(len(app._cache), 512)
            self.assertIn('/new', app._cache)
        finally:
            app._cache.clear()
            app._cache.update(original)

    def test_pagination_and_conditional_cache(self):
        import io
        from email.message import Message
        def response(data, **headers):
            body = io.BytesIO(json.dumps(data).encode())
            body.headers = Message()
            for key, value in headers.items():
                body.headers[key.replace('_', '-')] = value
            return body
        first = response({'jobs': [{'id': 1}]}, ETag='"one"', Link=' <https://api.github.com/test?page=2>; rel="next"')
        second = response({'jobs': [{'id': 2}]})
        cached = urllib.error.HTTPError('https://api.github.com/test', 304, 'Not Modified', {}, None)
        with patch.object(app.urllib.request, 'urlopen', side_effect=[first, second, cached]) as request:
            self.assertEqual(app.gh_items('/test', 'jobs'), [{'id': 1}, {'id': 2}])
            self.assertEqual(app.gh('/test'), {'jobs': [{'id': 1}]})
            self.assertEqual(request.call_args.args[0].get_header('If-none-match'), '"one"')


class PollTests(unittest.TestCase):
    def test_collection_uses_paginated_endpoints(self):
        original = dict(app.STATE)
        try:
            with patch.object(app, 'REPOS', ['owner/repo']), patch.object(app, 'gh_items', return_value=[]) as items:
                app.poll_once()
            self.assertTrue(items.called)
            self.assertIsNone(app.STATE['error'])
            self.assertEqual(app.HOST, '127.0.0.1')
        finally:
            app.STATE.clear()
            app.STATE.update(original)

    def test_http_failure_preserves_jobs(self):
        original = dict(app.STATE)
        error = urllib.error.HTTPError('https://api.github.com/test', 403, 'Forbidden', {}, None)
        app.STATE.update(updated='previous', jobs=[{'name': 'last-good'}])
        try:
            with patch.object(app, 'gh', side_effect=error):
                app.poll_once()
            self.assertEqual(app.STATE['jobs'], [{'name': 'last-good'}])
            self.assertEqual(app.STATE['updated'], 'previous')
        finally:
            error.close()
            app.STATE.clear()
            app.STATE.update(original)

    def test_network_failure_preserves_last_good_state(self):
        original = dict(app.STATE)
        app.STATE.update(updated='previous', runners=[{'name': 'last-good'}], jobs=[])
        try:
            with patch.object(app, 'gh', side_effect=urllib.error.URLError('offline')):
                app.poll_once()
            self.assertEqual(app.STATE['runners'], [{'name': 'last-good'}])
            self.assertEqual(app.STATE['updated'], 'previous')
            self.assertIn('offline', app.STATE['error'])
        finally:
            app.STATE.clear()
            app.STATE.update(original)


if __name__ == '__main__':
    unittest.main()
