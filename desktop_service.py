"""Private loopback HTTP adapter for the desktop WebView, not a LAN server."""
import secrets
import threading
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer

import ci_dashboard as dashboard
from desktop_store import parse_repos


class DesktopService:
    def __init__(self, settings, poll=True):
        if not isinstance(settings.get('token'), str) or not settings['token'].strip():
            raise ValueError('Configure a GitHub token before opening the dashboard.')
        repos = parse_repos(','.join(settings.get('repos', [])))
        self.stop = threading.Event()
        self.secret = secrets.token_urlsafe(32)
        self.bootstrap_lock = threading.Lock()
        self.bootstrapped = False
        self.poll_enabled = poll
        owner = self

        class GuardedHandler(dashboard.H):
            def do_POST(self):
                self.send_error(405)

            do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_POST

            def do_GET(self):
                if self.command != 'GET':
                    self.send_error(405)
                    return
                if self.headers.get('Host') != owner.host:
                    self.send_error(403)
                    return
                origin = self.headers.get('Origin')
                if origin and origin != owner.origin:
                    self.send_error(403)
                    return
                if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                    self.send_error(403)
                    return
                with owner.bootstrap_lock:
                    bootstrap = self.path == '/launch/' + owner.secret and not owner.bootstrapped
                    if bootstrap:
                        owner.bootstrapped = True
                if bootstrap:
                    self.send_response(302)
                    self.send_header('Set-Cookie', f'{owner.cookie}={owner.secret}; Path=/; HttpOnly; SameSite=Strict')
                    self.send_header('Location', '/')
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Referrer-Policy', 'no-referrer')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                cookie = SimpleCookie()
                try:
                    cookie.load(self.headers.get('Cookie', ''))
                    supplied = cookie[owner.cookie].value if owner.cookie in cookie else ''
                except Exception:
                    supplied = ''
                try:
                    valid = secrets.compare_digest(supplied, owner.secret)
                except (TypeError, ValueError):
                    valid = False
                if not valid:
                    self.send_error(401)
                    return
                super().do_GET()

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), GuardedHandler)
        self.server.daemon_threads = True
        self.host = f'127.0.0.1:{self.server.server_port}'
        self.origin = 'http://' + self.host
        self.cookie = f'ci_session_{self.server.server_port}'
        self.launch_url = self.origin + '/launch/' + self.secret
        dashboard.TOKEN = settings['token'].strip()
        dashboard.REPOS = repos
        dashboard.POLL = max(20, int(settings.get('poll', 30)))
        dashboard.STATE.clear()
        dashboard.STATE.update(updated=None, error='Loading data from GitHub...', runners=[], jobs=[], rate=None)
        dashboard._cache.clear()
        dashboard._etag.clear()
        dashboard._links.clear()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.poll_thread = threading.Thread(target=self._poll, daemon=True)

    def _poll(self):
        while not self.stop.is_set():
            try:
                dashboard.poll_once()
                if dashboard.STATE.get('error'):
                    dashboard.STATE['error'] = 'GitHub data is incomplete or unavailable. Check your connection and token permissions (Actions/Administration: Read).'
            except Exception:
                # Never include exception repr, request headers or credentials in the UI.
                dashboard.STATE['error'] = 'GitHub connection failed. Please try again or check your token.'
            self.stop.wait(dashboard.POLL)

    def start(self):
        self.thread.start()
        if self.poll_enabled:
            self.poll_thread.start()

    def close(self):
        self.stop.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        if self.poll_thread.is_alive():
            self.poll_thread.join(timeout=1)
