"""Private loopback HTTP adapter for the desktop WebView, not a LAN server."""
import json
import logging
import secrets
import threading
import time
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer

import ci_dashboard as dashboard
from desktop_history import load_store
from desktop_store import DATA_DIR, SETTINGS_PATH, SettingsError, load_settings, parse_repos

LOGGER = logging.getLogger('ci_operations')

HISTORY_PATH = DATA_DIR / 'history.db'
HISTORY_WINDOWS = {'24h': 24 * 3600, '7d': 7 * 24 * 3600, '30d': 30 * 24 * 3600, 'all': 0}


def _window_seconds(value):
    """Translate a history window name into seconds. Unknown values mean everything."""
    try:
        return HISTORY_WINDOWS.get(str(value or '').lower(), 0)
    except (AttributeError, TypeError):
        return 0


def _drain(handler):
    """Read and discard the request body so the socket closes cleanly."""
    try:
        length = int(handler.headers.get('Content-Length') or 0)
    except (TypeError, ValueError):
        length = 0
    if length > 0:
        try:
            handler.rfile.read(min(length, 1 << 20))
        except OSError:
            pass


def _query_window(path):
    """Read the history window from a query string."""
    try:
        from urllib.parse import parse_qs, urlsplit
        values = parse_qs(urlsplit(path).query).get('window', [])
        return values[0] if values else ''
    except (AttributeError, TypeError, ValueError):
        return ''


class DesktopService:
    def __init__(self, settings, poll=True):
        if not isinstance(settings.get('token'), str) or not settings['token'].strip():
            raise ValueError('Configure a GitHub token before opening the dashboard.')
        repos = parse_repos(','.join(settings.get('repos', [])))
        self.stop = threading.Event()
        self.secret = secrets.token_urlsafe(32)
        self.bootstrap_lock = threading.Lock()
        self.bootstrapped = False
        # Session secret used only to set the HttpOnly cookie; never exposed to the page.
        self.session_value = ''
        self.poll_enabled = poll
        self.history = load_store(HISTORY_PATH, enabled=settings.get('history', True) is not False)
        owner = self

        class GuardedHandler(dashboard.H):
            def do_POST(self):
                # Drain the request body before replying, otherwise closing the
                # socket with unread data makes Windows reset the connection.
                _drain(self)
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
                        owner.session_value = secrets.token_urlsafe(32)
                if bootstrap:
                    self.send_response(302)
                    self.send_header('Set-Cookie', f'{owner.cookie}={owner.session_value}; Path=/; HttpOnly; SameSite=Strict')
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
                    valid = bool(owner.session_value) and secrets.compare_digest(supplied, owner.session_value)
                except (TypeError, ValueError):
                    valid = False
                if not valid:
                    self.send_error(401)
                    return
                history = owner.history_payload(self.path, self.headers)
                if history is not None:
                    body, content_type = history
                    self.send_response(200)
                    self.send_header('Content-Type', content_type)
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.end_headers()
                    self.wfile.write(body)
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
        dashboard.STATE.update(updated=None, error='Loading data from GitHub...', runners=[], jobs=[], rate=None,
                               version=settings.get('app_version', ''))
        dashboard._cache.clear()
        dashboard._etag.clear()
        dashboard._links.clear()
        self.settings_stamp = self._settings_stamp()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.poll_thread = threading.Thread(target=self._poll, daemon=True)
        self.watch_thread = threading.Thread(target=self._watch, daemon=True)

    @staticmethod
    def _settings_stamp():
        try:
            return SETTINGS_PATH.stat().st_mtime_ns
        except OSError:
            return None

    def _poll(self):
        while not self.stop.is_set():
            try:
                dashboard.poll_once()
                if dashboard.STATE.get('error'):
                    dashboard.STATE['error'] = 'GitHub data is incomplete or unavailable. Check your connection and token permissions (Actions/Administration: Read).'
                self.record_history()
            except Exception:
                # Never include exception repr, request headers or credentials in the UI.
                dashboard.STATE['error'] = 'GitHub connection failed. Please try again or check your token.'
            self.stop.wait(dashboard.POLL)

    def record_history(self):
        """Persist finished jobs so reliability trends survive a restart."""
        if self.history is None:
            return 0
        try:
            return self.history.record(dashboard.STATE.get('jobs') or [])
        except Exception:
            LOGGER.warning('job history could not be written')
            return 0

    def history_payload(self, path, headers):
        """Return the body for a history route, or None when the route is unknown."""
        route = path.split('?', 1)[0]
        if route not in ('/api/history', '/api/history.csv'):
            return None
        if self.history is None:
            return json.dumps({'error': 'History is disabled.'}).encode(), 'application/json'
        window = _window_seconds(headers.get('X-History-Window') or _query_window(path))
        since = time.time() - window if window else None
        if route == '/api/history.csv':
            return self.history.export_csv(since=since).encode('utf-8'), 'text/csv; charset=utf-8'
        body = json.dumps({
            'summary': self.reliability(window),
            'jobs': self.history.export_json(since=since)['jobs'],
        }).encode('utf-8')
        return body, 'application/json'

    def apply_settings(self, settings):
        """Adopt a new token and repository list without restarting the window."""
        token = settings.get('token', '').strip()
        repos = parse_repos(','.join(settings.get('repos', [])))
        dashboard.TOKEN = token
        dashboard.REPOS = repos
        dashboard.POLL = max(20, int(settings.get('poll', 30)))
        dashboard._cache.clear()
        dashboard._etag.clear()
        dashboard._links.clear()
        dashboard.STATE['error'] = 'Settings updated. Loading data from GitHub...'
        dashboard.STATE['updated'] = None
        dashboard.STATE['runners'] = []
        dashboard.STATE['jobs'] = []

    def reliability(self, window='24h'):
        """Return the reliability summary for the requested window."""
        if self.history is None:
            return {'total': 0, 'failed': 0, 'successes': 0, 'success_rate': None,
                    'workflows': [], 'failing_steps': []}
        since = time.time() - _window_seconds(window) if _window_seconds(window) else None
        try:
            return self.history.summary(since=since)
        except Exception:
            LOGGER.warning('reliability summary could not be computed')
            return {'total': 0, 'failed': 0, 'successes': 0, 'success_rate': None,
                    'workflows': [], 'failing_steps': []}

    def watch_settings(self):
        """Reload credentials saved by a separate settings window."""
        stamp = self._settings_stamp()
        if stamp == self.settings_stamp:
            return
        self.settings_stamp = stamp
        if stamp is None:
            # The credentials file was removed: stop using the old token.
            self.forget_settings()
            return
        try:
            settings = load_settings()
        except SettingsError:
            LOGGER.warning('saved settings could not be read while watching for changes')
            return
        if not settings:
            self.forget_settings()
            return
        self.apply_settings(settings)
        LOGGER.info('applied updated credentials from the settings window')

    def forget_settings(self):
        """Drop the credentials and tell the user to configure the app again."""
        dashboard.TOKEN = ''
        dashboard.REPOS = []
        dashboard._cache.clear()
        dashboard._etag.clear()
        dashboard._links.clear()
        dashboard.STATE['runners'] = []
        dashboard.STATE['jobs'] = []
        dashboard.STATE['updated'] = None
        dashboard.STATE['error'] = 'The saved token was removed. Open GitHub settings to continue.'
        LOGGER.info('saved credentials were removed')

    def _watch(self):
        while not self.stop.is_set():
            try:
                self.watch_settings()
            except Exception:
                LOGGER.warning('settings watcher failed')
            self.stop.wait(3)

    def start(self):
        self.thread.start()
        if self.poll_enabled:
            self.poll_thread.start()
            self.watch_thread.start()

    def close(self):
        self.stop.set()
        # shutdown() blocks until serve_forever returns, so only call it when
        # the server thread is actually running.
        if self.thread.is_alive():
            self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3) if self.thread.is_alive() else None
        if self.poll_thread.is_alive():
            self.poll_thread.join(timeout=1)
        if self.watch_thread.is_alive():
            self.watch_thread.join(timeout=1)
