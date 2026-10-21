#!/usr/bin/env python3
"""Realtime GitHub Actions runner dashboard (stdlib only).
Env: GITHUB_TOKEN (fine-grained PAT: Actions read + Administration read on repos)
     REPOS (comma-separated owner/repo names; default owner/repo placeholder)
     PORT (default 8787), POLL (default 20), HOST (default 127.0.0.1)
     STATE_FILE: serve a static state JSON instead of polling (for snapshots)."""
import json, logging, os, signal, threading, time, urllib.request, urllib.error
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPOS = [r.strip() for r in os.environ.get("REPOS", "owner/repo").split(",") if r.strip()]
LOGGER = logging.getLogger("ci_dashboard")
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8787")); POLL = max(5, int(os.environ.get("POLL", "20")))
STATE = {"updated": None, "error": "starting", "runners": [], "jobs": [], "rate": None}
_etag = {}
_cache = {}
_links = {}


def gh(path):
    headers = {
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    if path in _etag:
        headers['If-None-Match'] = _etag[path]
    request = urllib.request.Request('https://api.github.com' + path, headers=headers)
    if TOKEN:
        request.add_unredirected_header('Authorization', 'Bearer ' + TOKEN)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            STATE['rate'] = response.headers.get('X-RateLimit-Remaining')
            data = json.load(response)
            _cache[path] = data
            if len(_cache) > 512:
                oldest = next(iter(_cache))
                _cache.pop(oldest, None)
                _etag.pop(oldest, None)
                _links.pop(oldest, None)
            _links[path] = response.headers.get('Link', '')
            if response.headers.get('ETag'):
                _etag[path] = response.headers['ETag']
            return data
    except urllib.error.HTTPError as error:
        if error.code == 304 and path in _cache:
            error.close()
            return _cache[path]
        raise


def gh_items(path, key):
    items, visited = [], set()
    while path and path not in visited:
        visited.add(path)
        items.extend(gh(path).get(key, []))
        link = _links.get(path, '')
        path = None
        for part in link.split(','):
            if 'rel="next"' in part:
                url = part.split(';', 1)[0].strip().strip('<>')
                if url.startswith('https://api.github.com/'):
                    path = url[len('https://api.github.com'):]
    return items

def poll_once():
    try:
        _collect()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        STATE['error'] = str(error)
        if isinstance(error, urllib.error.HTTPError):
            error.close()


def _steps(job):
    """Normalise the steps of a job, keeping only fields the dashboard uses."""
    steps = []
    for step in job.get("steps") or []:
        steps.append({"name": step.get("name"), "conclusion": step.get("conclusion"),
                      "number": step.get("number"), "started": step.get("started_at"),
                      "completed": step.get("completed_at")})
    return steps


def _collect():
    runners, jobs, errs = [], [], []
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3 * 3600))
    for repo in REPOS:
        try:
            for rn in gh_items(f"/repos/{repo}/actions/runners?per_page=100", "runners"):
                runners.append({"repo": repo, "name": rn["name"], "status": rn["status"], "busy": rn["busy"],
                                "labels": [l["name"] for l in rn.get("labels", [])]})
        except urllib.error.HTTPError as e:
            LOGGER.warning("runner inventory unavailable for %s (HTTP %s)", repo, e.code)
            errs.append(f"{repo} runners: HTTP {e.code} (needs Administration: read)")
            e.close()
        runs = {}
        try:
            # One request per repo instead of one per status: the created window
            # already bounds the result, and a separate status filter per query
            # multiplied the API calls by four.
            for run in gh_items(f"/repos/{repo}/actions/runs?per_page=100&created=%3E{since}", "workflow_runs"):
                runs[run["id"]] = run
        except urllib.error.HTTPError:
            raise
        for run in runs.values():
            try:
                js = gh_items(f"/repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100", "jobs")
            except urllib.error.HTTPError:
                raise
            pr = run.get("pull_requests") or []
            for j in js:
                jobs.append({"repo": repo, "run_id": run["id"], "job_id": j.get("id"),
                             "workflow": run["name"], "branch": run["head_branch"],
                             "pr": pr[0]["number"] if pr else None, "sha": run["head_sha"][:7], "name": j["name"],
                             "status": j["status"], "conclusion": j["conclusion"], "runner": j.get("runner_name"),
                             "created": j.get("created_at"), "started": j.get("started_at"),
                             "completed": j.get("completed_at"), "url": j.get("html_url"),
                             "steps": _steps(j)})
    STATE.update(updated=datetime.now(timezone.utc).isoformat(), error="; ".join(errs) or None,
                 runners=runners, jobs=jobs)

def loop():
    while True:
        try: poll_once()
        except Exception as e: STATE["error"] = repr(e)
        time.sleep(POLL)

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/api/state':
            body, ct = json.dumps(STATE).encode(), 'application/json; charset=utf-8'
        elif path in ('/', '/index.html'):
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html'), 'rb') as source:
                body = source.read()
            ct = 'text/html; charset=utf-8'
        elif path == '/fleet3d.js':
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fleet3d.js'), 'rb') as source:
                body = source.read()
            ct = 'text/javascript; charset=utf-8'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header("Content-Type", ct); self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(body)

if __name__ == "__main__":
    sf = os.environ.get("STATE_FILE")
    if sf:
        with open(sf, encoding="utf-8") as source:
            STATE.update(json.load(source))
        STATE["snapshot"] = True
    else:
        if not TOKEN:
            LOGGER.warning("GITHUB_TOKEN is not set; private repositories will return 404")
        threading.Thread(target=loop, daemon=True).start()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if HOST not in ("127.0.0.1", "::1", "localhost"):
        LOGGER.warning("BINDING TO %s EXPOSES CI DATA BEYOND THIS MACHINE. Use a firewall and authenticated reverse proxy.", HOST)
    LOGGER.info("CI dashboard listening on http://%s:%s", HOST, PORT)
    server = ThreadingHTTPServer((HOST, PORT), H)
    def stop(signum, frame):
        LOGGER.info("shutting down")
        threading.Thread(target=server.shutdown, daemon=True).start()
    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stop)
    try:
        server.serve_forever()
    finally:
        server.server_close()
