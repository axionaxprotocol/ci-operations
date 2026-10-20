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
import time
from pathlib import Path

from desktop_service import DesktopService
from desktop_setup import launch_command, show_setup
from desktop_store import DATA_DIR, LOG_PATH, SettingsError, load_settings, save_settings

LOGGER = logging.getLogger('ci_operations')


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
                                        'frozen': bool(getattr(sys, 'frozen', False))}), encoding='utf-8')


def run_dashboard(settings, smoke_report=None):
    import webview
    from webview.menu import Menu, MenuAction

    service = DesktopService(settings, poll=not bool(smoke_report))
    service.start()
    reconfigure = []
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
    webview.settings['ALLOW_DOWNLOADS'] = False
    window = webview.create_window('CI Operations', service.launch_url, width=1440, height=980,
                                   min_size=(980, 680), background_color='#f4f6f8',
                                   text_select=True, zoomable=True)

    def configure():
        reconfigure.append(True)
        window.destroy()

    menu = [Menu('Application', [MenuAction('GitHub settings', configure),
                                 MenuAction('Exit', window.destroy)])]

    def smoke():
        outcome = {'window': False}
        try:
            for _ in range(80):
                try:
                    outcome = window.evaluate_js("({window:document.title.includes('CI Operations'),theme: getComputedStyle(document.documentElement).colorScheme,body:!!document.getElementById('summary'),tokenFields:document.querySelectorAll('input[type=password]').length})")
                    if outcome and outcome.get('window') and outcome.get('body'):
                        break
                except Exception:
                    pass
                time.sleep(.15)
            Path(smoke_report).write_text(json.dumps(outcome), encoding='utf-8')
        finally:
            window.destroy()

    LOGGER.info('dashboard window opening')
    try:
        webview.start(smoke if smoke_report else None, gui='edgechromium', debug=False,
                      private_mode=True, menu=menu, icon=str(resource('app.ico')))
    finally:
        service.close()
        LOGGER.info('dashboard closed')
    return bool(reconfigure)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--configure', action='store_true')
    parser.add_argument('--startup', action='store_true')
    parser.add_argument('--self-test-report')
    parser.add_argument('--ui-smoke-report')
    parser.add_argument('--setup-smoke-report')
    configure_logging()
    args = parser.parse_args()
    if args.self_test_report:
        self_test(args.self_test_report)
        return
    if args.setup_smoke_report:
        show_setup(smoke_report=args.setup_smoke_report)
        return
    if args.ui_smoke_report:
        run_dashboard({'token': 'TEST-ONLY-NOT-REAL', 'repos': ['test/fixture']}, args.ui_smoke_report)
        return

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    identity = hashlib.sha256(str(Path.home()).encode()).hexdigest()[:16]
    mutex = kernel.CreateMutexW(None, True, 'Local\\CIOperations-' + identity)
    if not mutex:
        raise OSError('Could not create application lock')
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(mutex)
        if not args.startup:
            from tkinter import Tk, messagebox
            root = Tk()
            root.withdraw()
            messagebox.showinfo('CI Operations', 'CI Operations is already running. Select its window on the taskbar.')
            root.destroy()
        return
    reconfigure = False
    try:
        notice = ''
        try:
            settings = load_settings()
        except SettingsError:
            settings = None
            notice = 'Could not read saved credentials. Please configure your token again.'
            LOGGER.warning('saved settings could not be decrypted')
        if args.configure or not settings:
            settings = show_setup(settings, notice)
        if settings:
            reconfigure = run_dashboard(settings)
    finally:
        kernel.ReleaseMutex(mutex)
        kernel.CloseHandle(mutex)
    LOGGER.info('application exiting')
    if reconfigure:
        subprocess.Popen(launch_command() + ['--configure'], close_fds=True)


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
