"""Small desktop launcher for the admin page.

Starts the local FastAPI app in a background thread (uvicorn) and opens
a native window using pywebview pointing to http://127.0.0.1:8000/admin.

This file can be packaged with PyInstaller to a single EXE.
"""
import threading
import time
import webbrowser
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)


def start_server_in_bg(host='127.0.0.1', port=8000):
    try:
        import uvicorn
    except Exception as exc:
        print('uvicorn is required to run the embedded server:', exc)
        return None

    def _run():
        # Import as module path so PyInstaller can still include app.py
        uvicorn.run('app:app', host=host, port=port, log_level='info')

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def wait_for_server(url='http://127.0.0.1:8000', timeout=10.0):
    import requests
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(url, timeout=1.0)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def open_admin_window(url='http://127.0.0.1:8000/admin'):
    try:
        import webview
    except Exception:
        # fallback to opening in default browser
        webbrowser.open(url)
        return

    # Create a simple window (uses platform native backend)
    webview.create_window('Share-It — Admin', url, width=1000, height=800)
    webview.start()


def main():
    host = '127.0.0.1'
    port = 8000
    base = f'http://{host}:{port}'

    print('Starting local server...')
    t = start_server_in_bg(host=host, port=port)
    ok = wait_for_server(base, timeout=8.0)
    if not ok:
        print('Server did not start in time; opening admin in browser instead.')
        webbrowser.open(base + '/admin')
        return

    print('Opening admin window...')
    open_admin_window(base + '/admin')


if __name__ == '__main__':
    main()
