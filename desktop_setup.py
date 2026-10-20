"""Native setup form: credentials never pass through dashboard JavaScript."""
import json
import queue
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import winreg
from pathlib import Path

from desktop_store import SETTINGS_PATH, SettingsError, parse_repos, save_settings

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME = 'CIOperations'
DEFAULT_REPOS = ''


class ValidationError(Exception):
    pass


def validate_access(token, repos):
    if not token or len(token) > 1024 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValidationError('Enter a valid GitHub token (no URLs or whitespace).')
    for repo in repos:
        request = urllib.request.Request(
            f'https://api.github.com/repos/{repo}/actions/runs?per_page=1',
            headers={'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'CI-Operations-Desktop'})
        request.add_unredirected_header('Authorization', 'Bearer ' + token)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.load(response)
                if not isinstance(data, dict) or 'workflow_runs' not in data:
                    raise ValidationError('GitHub returned an invalid response. Please try again.')
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            if code == 401:
                raise ValidationError('The token is invalid or expired. Please create a new token.') from None
            if code == 404:
                raise ValidationError(f'Cannot access {repo}. Check the repository name and Actions: Read permission.') from None
            raise ValidationError(f'GitHub returned HTTP {code}. Check permissions or try again later.') from None
        except (OSError, ValueError) as error:
            raise ValidationError('Cannot connect to GitHub. Check your internet connection and try again.') from None


def launch_command():
    if getattr(sys, 'frozen', False):
        return [sys.executable]
    return [sys.executable, str(Path(__file__).with_name('desktop_app.py'))]


def set_startup(enabled):
    command = subprocess.list2cmdline(launch_command() + ['--startup'])
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_NAME)
            return True
    except FileNotFoundError:
        return False


class TokenPasteSupport:
    """Read the clipboard only on an explicit user paste action; never log it."""
    def __init__(self, entry, status):
        import tkinter as tk
        self.entry = entry
        self.status = status
        self.menu = tk.Menu(entry, tearoff=False, font=('Segoe UI', 14))
        self.menu.add_command(label='Paste', command=self.paste)
        entry.bind('<<Paste>>', self.paste)
        entry.bind('<Control-KeyPress>', self.on_key)
        entry.bind('<Button-3>', self.show_menu)

    def paste(self, event=None):
        import tkinter as tk
        try:
            value = self.entry.clipboard_get().strip()
        except tk.TclError:
            self.status.set('No text is available in the clipboard. Copy your token and try again.')
            return 'break'
        if not value or len(value) > 1024 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            self.status.set('The clipboard must contain one token, without spaces or line breaks.')
            return 'break'
        # A token field is a single value: avoid concatenating a new token with an old one.
        self.entry.delete(0, 'end')
        self.entry.insert(0, value)
        self.entry.icursor('end')
        self.entry.focus_set()
        self.status.set('Token pasted. Choose Save and open dashboard to continue.')
        return 'break'

    def on_key(self, event):
        # Windows virtual-key V is stable even when the active layout is Thai.
        if event.state & 0x4 and event.keycode == 0x56:
            return self.paste()
        return None

    def show_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
        return 'break'


def show_setup(existing=None, notice='', smoke_report=None):
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title('CI Operations — GitHub Setup')
    root.geometry('760x730')
    root.minsize(720, 700)
    root.configure(bg='#f4f6f8')
    root.option_add('*Font', ('Segoe UI', 14))
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=('Segoe UI', 14), background='#f4f6f8', foreground='#17252e')
    style.configure('TEntry', padding=8, fieldbackground='#ffffff')
    style.configure('TButton', padding=(16, 9))
    style.configure('Title.TLabel', font=('Segoe UI', 24, 'bold'))
    frame = ttk.Frame(root, padding=32)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='CI Operations', style='Title.TLabel').pack(anchor='w')
    ttk.Label(frame, text='Connect GitHub once, then launch your dashboard from the app icon.', wraplength=670).pack(anchor='w', pady=(8, 22))
    token = tk.StringVar(value=(existing or {}).get('token', ''))
    repos = tk.StringVar(value=','.join((existing or {}).get('repos', [])) or DEFAULT_REPOS)
    auto = tk.BooleanVar(value=startup_enabled())
    notify = tk.BooleanVar(value=(existing or {}).get('notifications', True) is not False)
    ttk.Label(frame, text='GitHub Personal Access Token').pack(anchor='w')
    token_row = ttk.Frame(frame)
    token_row.pack(fill='x', pady=(6, 6))
    entry = ttk.Entry(token_row, textvariable=token, show='●')
    entry.pack(side='left', fill='x', expand=True)
    reveal = tk.BooleanVar(value=False)
    ttk.Checkbutton(frame, text='Show token', variable=reveal,
                    command=lambda: entry.configure(show='' if reveal.get() else '●')).pack(anchor='w')
    ttk.Label(frame, text='Repositories (owner/repo, separated by commas)').pack(anchor='w', pady=(18, 0))
    ttk.Entry(frame, textvariable=repos).pack(fill='x', pady=(6, 14))
    ttk.Label(frame, text='Required: Actions: Read and Metadata: Read.\nOptional: Administration: Read to view idle and offline runners.', wraplength=670).pack(anchor='w')
    ttk.Checkbutton(frame, text='Launch automatically when I sign in to Windows', variable=auto).pack(anchor='w', pady=(14, 8))
    ttk.Checkbutton(frame, text='Notify me when a job fails', variable=notify).pack(anchor='w', pady=(0, 8))
    ttk.Label(frame, text='Your token is encrypted with Windows DPAPI for this Windows account.\nIt is never stored in browser localStorage or plaintext files.', wraplength=670).pack(anchor='w', pady=(0, 10))
    status = tk.StringVar(value=notice)
    paste_support = TokenPasteSupport(entry, status)
    paste_button = ttk.Button(token_row, text='Paste', command=paste_support.paste)
    paste_button.pack(side='right', padx=(8, 0))
    ttk.Label(frame, textvariable=status, wraplength=670, foreground='#956000').pack(anchor='w', fill='x')
    result = []
    messages = queue.Queue()
    busy = False
    buttons = ttk.Frame(frame)
    buttons.pack(side='bottom', fill='x', pady=(18, 0))

    def check_messages():
        nonlocal busy
        try:
            ok, data, requested_auto = messages.get_nowait()
        except queue.Empty:
            root.after(100, check_messages)
            return
        busy = False
        save.configure(state='normal')
        clear.configure(state='normal')
        if not ok:
            status.set(data)
        else:
            try:
                save_settings(data)
                set_startup(requested_auto)
                result.append(data)
                token.set('')
                root.destroy()
                return
            except (OSError, SettingsError):
                status.set('Could not save settings. Check your Windows permissions and try again.')
        root.after(100, check_messages)

    def submit():
        nonlocal busy
        if busy:
            return
        try:
            selected = parse_repos(repos.get())
        except ValueError:
            status.set('Enter owner/repo names separated by commas, not full URLs.')
            return
        value = token.get().strip()
        requested_auto = auto.get()
        save.configure(state='disabled')
        clear.configure(state='disabled')
        status.set('Checking your token and GitHub repository access...')
        busy = True

        def validate():
            try:
                validate_access(value, selected)
                messages.put((True, {'token': value, 'repos': selected, 'poll': 30,
                                     'notifications': notify.get()}, requested_auto))
            except ValidationError as error:
                messages.put((False, str(error), requested_auto))
            except Exception:
                messages.put((False, 'Validation failed. Please try again.', requested_auto))
        threading.Thread(target=validate, daemon=True).start()

    def forget():
        if messagebox.askyesno('Forget credentials', 'Remove the saved token and disable automatic launch?'):
            try:
                SETTINGS_PATH.unlink(missing_ok=True)
                set_startup(False)
                token.set('')
                auto.set(False)
                status.set('Saved token removed. Enter a new token before opening the dashboard.')
            except OSError:
                status.set('Could not remove settings. Check your Windows permissions.')

    clear = ttk.Button(buttons, text='Forget credentials', command=forget)
    clear.pack(side='left')
    save = ttk.Button(buttons, text='Save and open dashboard', command=submit)
    save.pack(side='right')
    ttk.Button(buttons, text='Cancel', command=root.destroy).pack(side='right', padx=8)
    root.after(100, check_messages)
    entry.focus_set()
    if smoke_report:
        def report():
            # Synthetic clipboard provider only; never read or overwrite the OS clipboard.
            original_clipboard_get = entry.clipboard_get
            try:
                entry.clipboard_get = lambda: '  TEST-ONLY-NOT-REAL\r\n'
                paste_button.invoke()
                paste_verified = token.get() == 'TEST-ONLY-NOT-REAL'
                token.set('')
                paste_support.on_key(type('KeyEvent', (), {'state': 0x4, 'keycode': 0x56})())
                ctrl_v_verified = token.get() == 'TEST-ONLY-NOT-REAL'
            finally:
                token.set('')
                entry.clipboard_get = original_clipboard_get
                status.set(notice)
            widgets = [root]
            labels = []
            while widgets:
                widget = widgets.pop()
                widgets.extend(widget.winfo_children())
                if 'text' in widget.keys():
                    labels.append(str(widget.cget('text')))
            english_labels = all(not 0x0E00 <= ord(c) <= 0x0E7F for text in labels for c in text)
            # The action row must sit fully inside the window, not clipped by it.
            buttons_bottom = buttons.winfo_rooty() + buttons.winfo_height() - root.winfo_rooty()
            save_button_visible = buttons_bottom <= root.winfo_height() - 4
            Path(smoke_report).write_text(json.dumps({'native_setup': True, 'paste_verified': paste_verified, 'ctrl_v_verified': ctrl_v_verified, 'paste_button_visible': bool(paste_button.winfo_ismapped()), 'english_labels': english_labels, 'actions': [clear.cget('text'), save.cget('text')], 'masked': bool(entry.cget('show')), 'token_empty': not token.get(), 'title': root.title(), 'save_button_visible': save_button_visible, 'buttons_bottom': buttons_bottom, 'window_height': root.winfo_height()}), encoding='utf-8')
            root.destroy()
        root.after(1200, report)
    root.mainloop()
    return result[0] if result else None
