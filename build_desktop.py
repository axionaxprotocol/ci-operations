"""Build a self-contained Windows x64 app and per-user Inno Setup installer.
Run with the packaging venv: .venv-desktop/Scripts/python.exe build_desktop.py
"""
import os
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def make_icon():
    images = []
    for size in (16, 32, 48, 64, 128):
        pixels = bytearray()
        for y in reversed(range(size)):
            for x in range(size):
                px, py = x / size, y / size
                square = any(a <= px < a + .22 and b <= py < b + .22
                             for a in (.22, .56) for b in (.22, .56))
                r, g, b = (8, 123, 89) if square else (244, 246, 248)
                pixels.extend((b, g, r, 255))
        mask = bytes(((size + 31) // 32) * 4 * size)
        bitmap = struct.pack('<IiiHHIIiiII', 40, size, size * 2, 1, 32, 0,
                             len(pixels) + len(mask), 0, 0, 0, 0) + pixels + mask
        images.append((size, bitmap))
    offset = 6 + 16 * len(images)
    entries = bytearray()
    for size, bitmap in images:
        entries.extend(struct.pack('<BBBBHHII', size, size, 0, 0, 1, 32, len(bitmap), offset))
        offset += len(bitmap)
    (ROOT / 'app.ico').write_bytes(struct.pack('<HHH', 0, 1, len(images)) + entries + b''.join(data for _, data in images))


def main():
    if os.name != 'nt':
        raise SystemExit('Build this installer on Windows x64.')
    make_icon()
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
                    '--windowed', '--name', 'CI-Operations', '--icon', str(ROOT / 'app.ico'),
                    '--add-data', f'{ROOT / "index.html"};.', '--add-data', f'{ROOT / "fleet3d.js"};.',
                    '--add-data', f'{ROOT / "app.ico"};.',
                    '--collect-all', 'webview', '--hidden-import', 'webview.platforms.edgechromium',
                    '--hidden-import', 'webview.platforms.winforms', str(ROOT / 'desktop_app.py')],
                   cwd=ROOT, check=True)
    candidates = [Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Inno Setup 6/ISCC.exe',
                  Path('C:/Program Files (x86)/Inno Setup 6/ISCC.exe'),
                  Path('C:/Program Files/Inno Setup 6/ISCC.exe')]
    compiler = next((p for p in candidates if p.is_file()), None)
    if not compiler:
        raise SystemExit('Install Inno Setup 6, then compile installer.iss. App build is in dist/CI-Operations.')
    subprocess.run([str(compiler), str(ROOT / 'installer.iss')], cwd=ROOT, check=True)
    print('Installer:', ROOT / 'dist/CI-Operations-Setup.exe')


if __name__ == '__main__':
    main()
