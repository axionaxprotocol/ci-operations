"""Windows-user-bound settings encryption. Never serialize a plaintext token."""
import ctypes
import json
import os
import re
from ctypes import wintypes
from pathlib import Path

APP_NAME = 'CI Operations'
DATA_DIR = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'CIOperations'
SETTINGS_PATH = DATA_DIR / 'settings.dat'


class SettingsError(Exception):
    pass


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data, decrypt=False):
    if os.name != 'nt':
        raise SettingsError('Secure credential storage requires Windows.')
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        fn = crypt.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        fn = crypt.CryptProtectData
        fn.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = fn(ctypes.byref(source), APP_NAME, None, None, None, 1, ctypes.byref(target))
    if not ok:
        raise SettingsError('Windows could not unlock saved settings. Configure the token again.')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


def save_settings(settings, path=SETTINGS_PATH):
    path = Path(path)
    encrypted = _crypt(json.dumps(settings, ensure_ascii=False).encode('utf-8'))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes(encrypted)
    os.replace(temporary, path)


def load_settings(path=SETTINGS_PATH):
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(_crypt(path.read_bytes(), decrypt=True).decode('utf-8'))
        if not isinstance(data, dict) or not isinstance(data.get('token'), str) or not data['token']:
            raise ValueError('invalid settings')
        data['repos'] = parse_repos(','.join(data.get('repos', [])))
        return data
    except (OSError, ValueError, TypeError, SettingsError) as error:
        raise SettingsError('Cannot read saved credentials. Please configure the token again.') from error


def parse_repos(value):
    repos = list(dict.fromkeys(repo.strip() for repo in value.split(',') if repo.strip()))
    if not repos or any(not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo)
                        or any(part in ('.', '..') for part in repo.split('/')) for repo in repos):
        raise ValueError('Use owner/repo, separated by commas; do not enter full URLs.')
    return repos
