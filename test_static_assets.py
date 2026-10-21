"""The 3D engine is served as a same-origin static asset, never from the network."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import ci_dashboard


class StaticAssetTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), ci_dashboard.H)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = 'http://127.0.0.1:%d' % self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def fetch(self, path):
        with urllib.request.urlopen(self.origin + path, timeout=10) as response:
            return response.status, response.headers.get('Content-Type'), response.read()

    def test_the_dashboard_page_is_served(self):
        status, content_type, body = self.fetch('/index.html')
        self.assertEqual(status, 200)
        self.assertIn('text/html', content_type)
        self.assertIn(b'volume-canvas', body)

    def test_the_3d_engine_is_served_as_javascript(self):
        status, content_type, body = self.fetch('/fleet3d.js')
        self.assertEqual(status, 200)
        self.assertIn('javascript', content_type)
        self.assertIn(b'createViewer', body)

    def test_the_3d_engine_is_served_with_the_same_security_headers(self):
        with urllib.request.urlopen(self.origin + '/fleet3d.js', timeout=10) as response:
            self.assertEqual(response.headers.get('X-Content-Type-Options'), 'nosniff')
            self.assertIn("default-src 'self'", response.headers.get('Content-Security-Policy'))

    def test_an_unknown_asset_is_not_served(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.fetch('/secrets.js')
        self.assertEqual(caught.exception.code, 404)

    def test_the_3d_engine_exposes_the_expected_entry_points(self):
        _, _, body = self.fetch('/fleet3d.js')
        source = body.decode('utf-8')
        for name in ('buildLayout', 'createViewer', 'rayBox', 'orbit', 'zoom', 'resetCamera'):
            self.assertIn(name, source)


class DashboardRoutingTests(unittest.TestCase):
    def test_the_browser_only_server_also_serves_the_3d_engine(self):
        with open(ci_dashboard.__file__, encoding='utf-8') as source:
            self.assertIn("path == '/fleet3d.js'", source.read())


if __name__ == '__main__':
    unittest.main()
