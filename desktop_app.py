"""Windows desktop entry point. Token gate + DPAPI + private WebView2 window."""
import argparse
import ctypes
import faulthandler
import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from desktop_service import DesktopService
from desktop_setup import launch_command, show_setup
from desktop_store import DATA_DIR, LOG_PATH, SettingsError, load_settings, save_settings

LOGGER = logging.getLogger('ci_operations')

GITHUB_REPO = "axionaxprotocol/ci-operations"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
CURRENT_VERSION = "1.3.0"

# Two independent locks: the dashboard window and the settings window may run
# side by side, but never twice of the same kind.
DASHBOARD_LOCK = 'Local\\CIOperations-dashboard-'
SETUP_LOCK = 'Local\\CIOperations-setup-'


def lock_names():
    """Return the kernel32 handle plus the per-user dashboard and setup lock names."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    identity = hashlib.sha256(str(Path.home()).encode()).hexdigest()[:16]
    return kernel, DASHBOARD_LOCK + identity, SETUP_LOCK + identity


def acquire_mutex(kernel, name):
    """Create a named lock. Returns None when another instance already holds it."""
    ctypes.set_last_error(0)
    handle = kernel.CreateMutexW(None, True, name)
    if not handle:
        raise OSError('Could not create application lock')
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel.CloseHandle(handle)
        return None
    return handle


def release_mutex(kernel, handle):
    if handle:
        kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def instance_running(kernel, name):
    """True when another process currently holds the named lock."""
    handle = acquire_mutex(kernel, name)
    if handle is None:
        return True
    release_mutex(kernel, handle)
    return False


def notify(title, message):
    """Show a native message box without leaking details into the log."""
    from tkinter import Tk, messagebox
    root = Tk()
    root.withdraw()
    messagebox.showinfo(title, message)
    root.destroy()


def parse_version(value):
    """Return a comparable tuple for a dotted version string."""
    parts = []
    for chunk in str(value).split('.'):
        digits = ''.join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def version_is_newer(candidate, current):
    """True when candidate is a strictly newer version than current.

    Comparing the raw strings is wrong: '1.0.10' sorts before '1.0.9'.
    """
    return parse_version(candidate) > parse_version(current)


def latest_release_version():
    """Return the newest published release version, or None if it cannot be read."""
    import json
    try:
        with urllib.request.urlopen(GITHUB_API, timeout=8) as resp:
            data = json.load(resp)
        tag = data.get('tag_name') or ''
        version = tag.lstrip('v').strip()
        return version or None
    except Exception as e:
        LOGGER.info('Release lookup failed: %s', e)
        return None


def parse_checksums(text):
    """Parse a SHA256SUMS file into {filename: lowercase hex digest}."""
    sums = {}
    for line in text.splitlines():
        parts = line.replace('*', ' ').split()
        if len(parts) >= 2 and len(parts[0]) == 64:
            sums[parts[1]] = parts[0].lower()
    return sums


def sha256_file(path, chunk=1 << 20):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(chunk), b''):
            digest.update(block)
    return digest.hexdigest()


def _schedule_detached_install(installer_path):
    """Install after this process exits.

    The installer replaces CI-Operations.exe. Running it inline makes Inno Setup
    try to close the very process that is waiting on it, which aborts the
    install with exit code 5. A short-lived detached helper avoids that.

    The helper also waits before relaunching. The old process is terminated by
    the installer, but its WebView2 COM server can still be registered a moment
    later, and the new window then fails to initialise with RPC_E_CALL_REJECTED
    (0x8001010d). A short pause lets that COM object go away.
    """
    frozen = bool(getattr(sys, 'frozen', False))
    relaunch = [sys.executable] if frozen else [sys.executable, str(Path(__file__).with_name('desktop_app.py'))]
    batch = Path(tempfile.gettempdir()) / 'ci-operations-update.cmd'
    lines = [
        '@echo off',
        'ping -n 4 127.0.0.1 >nul',
        f'"{installer_path}" /VERYSILENT /NORESTART /SUPPRESSMSGBOXES',
        'ping -n 8 127.0.0.1 >nul',
        f'start "" {subprocess.list2cmdline(relaunch)}',
    ]
    batch.write_text('\r\n'.join(lines) + '\r\n', encoding='utf-8')
    flags = 0
    if hasattr(subprocess, 'DETACHED_PROCESS'):
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    subprocess.Popen(['cmd.exe', '/c', str(batch)], creationflags=flags, close_fds=True)
    LOGGER.info('Installer scheduled; exiting so files can be replaced')


def run_auto_update() -> int:
    import json
    try:
        with urllib.request.urlopen(GITHUB_API, timeout=10) as resp:
            data = json.load(resp)
        tag = data['tag_name']
        assets = data.get('assets', [])
        setup_asset = next((a for a in assets if a['name'].endswith('-Setup.exe')), None)
        if not setup_asset:
            LOGGER.info('No installer asset found in latest release')
            return 1
        latest_version = tag.lstrip('v')
        if not version_is_newer(latest_version, CURRENT_VERSION):
            LOGGER.info('Already on latest version %s', CURRENT_VERSION)
            return 0
        LOGGER.info('Update available: %s -> %s', CURRENT_VERSION, latest_version)
        installer_url = setup_asset['browser_download_url']
        with tempfile.NamedTemporaryFile(suffix='-Setup.exe', delete=False) as tmp:
            installer_path = tmp.name
        LOGGER.info('Downloading installer from %s', installer_url)
        urllib.request.urlretrieve(installer_url, installer_path)
        sums_asset = next((a for a in assets if a['name'] == 'SHA256SUMS.txt'), None)
        if not sums_asset:
            LOGGER.error('Release has no SHA256SUMS.txt; refusing to install unverified bytes')
            return 1
        with urllib.request.urlopen(sums_asset['browser_download_url'], timeout=15) as resp:
            expected = parse_checksums(resp.read().decode('utf-8', 'replace'))
        wanted = expected.get(setup_asset['name'])
        if not wanted:
            LOGGER.error('SHA256SUMS.txt has no entry for %s', setup_asset['name'])
            return 1
        actual = sha256_file(installer_path)
        if actual != wanted:
            LOGGER.error('Installer checksum mismatch; aborting update')
            try:
                Path(installer_path).unlink()
            except OSError:
                pass
            return 1
        LOGGER.info('Installer checksum verified')
        _schedule_detached_install(installer_path)
        return 2
    except Exception as e:
        LOGGER.error('Auto-update failed: %s', e)
        return 1


def configure_logging():
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(LOG_PATH, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
        logging.basicConfig(level=logging.INFO, handlers=[handler])
        faulthandler.enable(handler.stream)
        return
    except OSError:
        pass
    logging.basicConfig(level=logging.INFO)


def resource(name):
    return Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / name


def self_test(report):
    with tempfile.TemporaryDirectory(prefix='ci-operations-test-') as directory:
        path = Path(directory) / 'test-settings.dat'
        value = 'TEST-ONLY-NOT-A-GITHUB-TOKEN'
        save_settings({'token': value, 'repos': ['test/fixture']}, path)
        encrypted = value.encode() not in path.read_bytes()
        roundtrip = load_settings(path)['token'] == value
    Path(report).write_text(json.dumps({'dpapi_encrypted': encrypted, 'dpapi_roundtrip': roundtrip,
                                        'dashboard_bundled': resource('index.html').is_file(),
                                        'dashboard_english': not any(0x0E00 <= ord(c) <= 0x0E7F for c in resource('index.html').read_text(encoding='utf-8')),
                                        'viewer_bundled': resource('fleet3d.js').is_file(),
                                        'frozen': bool(getattr(sys, 'frozen', False))}), encoding='utf-8')


def run_dashboard(settings, smoke_report=None):
    import webview
    from webview.menu import Menu, MenuAction

    service = DesktopService({**settings, 'app_version': CURRENT_VERSION}, poll=not bool(smoke_report))
    service.start()

    def update_probe():
        version = latest_release_version()
        if version:
            import desktop_service
            desktop_service.dashboard.STATE['latest_version'] = version
            if version_is_newer(version, CURRENT_VERSION):
                LOGGER.info('Newer release available: %s', version)

    if not smoke_report:
        threading.Thread(target=update_probe, daemon=True).start()
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
    webview.settings['ALLOW_DOWNLOADS'] = False
    window = webview.create_window('CI Operations', service.launch_url, width=1440, height=980,
                                   min_size=(980, 680), background_color='#f4f6f8',
                                   text_select=True, zoomable=True)

    current = dict(settings)

    def configure():
        # Run the native setup form in its own process: Tk needs a main thread,
        # and the dashboard window keeps running while settings are edited.
        try:
            subprocess.Popen(launch_command() + ['--configure'], close_fds=True)
        except OSError:
            LOGGER.warning('settings window could not be started')
            notify('CI Operations', 'The settings window could not be opened. Use the GitHub Settings shortcut in the Start menu instead.')

    def check_updates():
        import threading
        def worker():
            from tkinter import messagebox
            code = run_auto_update()
            if code == 0:
                messagebox.showinfo('CI Operations', f'CI Operations {CURRENT_VERSION} is up to date.')
            elif code == 2:
                messagebox.showinfo('CI Operations', 'Update downloaded. CI Operations will close, install the update, and reopen automatically.')
            elif code == 1:
                messagebox.showinfo('CI Operations', 'Update check failed. See the diagnostic log for details.')
        threading.Thread(target=worker, daemon=True).start()

    menu = [Menu(f'Application (v{CURRENT_VERSION})',
                 [MenuAction('Check for updates', check_updates),
                  MenuAction('GitHub settings', configure),
                  MenuAction('Exit', window.destroy)])]

    def smoke():
        outcome: dict = {'window': False}
        try:
            for _ in range(80):
                try:
                    outcome = window.evaluate_js("({window:document.title.includes('CI Operations'),theme: getComputedStyle(document.documentElement).colorScheme,body:!!document.getElementById('summary'),tokenFields:document.querySelectorAll('input[type=password]').length})")
                    if outcome and outcome.get('window') and outcome.get('body'):
                        break
                except Exception:
                    pass
                time.sleep(.15)
            # The 3D view must be present and, where WebGL2 exists, actually drawn.
            volume = {'present': False}
            try:
                found = window.evaluate_js("(() => {const c=document.getElementById('volume-canvas');if(!c)return {present:false};const gl=c.getContext('webgl2');return {present:true,webgl:!!gl,width:c.width,height:c.height,labels:document.getElementById('volume-labels').children.length};})()")
                if isinstance(found, dict):
                    volume = found
            except Exception:
                pass
            report = dict(outcome) if isinstance(outcome, dict) else {}
            report['volume'] = volume
            Path(smoke_report).write_text(json.dumps(report), encoding='utf-8')
        finally:
            window.destroy()

    LOGGER.info('dashboard window opening')
    try:
        webview.start(smoke if smoke_report else None, gui='edgechromium', debug=False,
                      private_mode=True, menu=menu, icon=str(resource('app.ico')))
    finally:
        service.close()
        LOGGER.info('dashboard closed')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--configure', action='store_true')
    parser.add_argument('--startup', action='store_true')
    parser.add_argument('--self-test-report')
    parser.add_argument('--ui-smoke-report')
    parser.add_argument('--setup-smoke-report')
    parser.add_argument('--check-update', action='store_true', help='Check and apply update if available')
    configure_logging()
    args = parser.parse_args()
    if args.check_update:
        code = run_auto_update()
        # code 2 means the detached helper will install and relaunch; exit now.
        sys.exit(0 if code == 2 else code)
    if args.self_test_report:
        self_test(args.self_test_report)
        return
    if args.setup_smoke_report:
        show_setup(smoke_report=args.setup_smoke_report)
        return
    if args.ui_smoke_report:
        run_dashboard({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['test/fixture']}, args.ui_smoke_report)
        return

    kernel, dashboard_name, setup_name = lock_names()
    notice = ''
    try:
        settings = load_settings()
    except SettingsError:
        settings = None
        notice = 'Could not read saved credentials. Please configure your token again.'
        LOGGER.warning('saved settings could not be decrypted')

    if args.configure:
        # Settings-only session: it must be reachable while the dashboard runs.
        setup_handle = acquire_mutex(kernel, setup_name)
        if setup_handle is None:
            if not args.startup:
                notify('CI Operations', 'The settings window is already open.')
            return
        try:
            updated = show_setup(settings, notice)
        finally:
            release_mutex(kernel, setup_handle)
        if not updated:
            return
        settings = updated
        if instance_running(kernel, dashboard_name):
            # A dashboard is already open; it reloads the new credentials itself.
            notify('CI Operations', 'Settings saved. The running dashboard now uses the new token and repositories.')
            return

    dashboard_handle = acquire_mutex(kernel, dashboard_name)
    if dashboard_handle is None:
        if not args.startup:
            notify('CI Operations', 'CI Operations is already running. Select its window on the taskbar.')
        return
    try:
        if not settings:
            setup_handle = acquire_mutex(kernel, setup_name)
            if setup_handle is None:
                if not args.startup:
                    notify('CI Operations', 'The settings window is already open.')
                return
            try:
                settings = show_setup(settings, notice)
            finally:
                release_mutex(kernel, setup_handle)
            if not settings:
                return
        run_dashboard(settings)
    finally:
        release_mutex(kernel, dashboard_handle)
    LOGGER.info('application exiting')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Never log a traceback: exception text may echo request headers or credentials.
        error = sys.exc_info()[1]
        try:
            LOGGER.error('startup failed (%s)', type(error).__name__)
        except Exception:
            pass
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror('CI Operations', 'Could not start CI Operations. Ensure Microsoft Edge WebView2 Runtime is installed.\nIf the issue persists, open GitHub Settings or reinstall the app.\nDiagnostic log: ' + str(LOG_PATH))
            root.destroy()
        except Exception:
            pass
        sys.exit(1)
