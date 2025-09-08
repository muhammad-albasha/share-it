import threading
import time
import requests
import sys
from PIL import Image, ImageDraw
import pystray
import subprocess
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(ROOT, 'server.pid')
STOP_SCRIPT = os.path.join(ROOT, 'stop_server.ps1')
START_SCRIPT = os.path.join(ROOT, 'start_server.ps1')
URL = 'http://127.0.0.1:8000/'
CHECK_INTERVAL = 3.0


def create_image(color):
    # Try to use a pre-generated ICO for crisp native Windows look.
    # The function will attempt to load assets/shareit-<color>.ico (color: green/red)
    # If missing, it will generate modern multi-resolution ICOs automatically.
    assets_dir = os.path.join(ROOT, 'assets')
    os.makedirs(assets_dir, exist_ok=True)

    # Map color names to filenames
    name = 'green' if color.lower().startswith('g') else 'red'
    ico_path = os.path.join(assets_dir, f'shareit-{name}.ico')

    def draw_modern_icon(base_size=256, bg_color=(0, 150, 90, 255)):
        # Draw a clear cloud + upload arrow icon suitable for small tray sizes.
        # Draw at base_size and save ICOs for crisp native rendering.
        img = Image.new('RGBA', (base_size, base_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        cx, cy = base_size // 2, base_size // 2
        # soft circular backdrop (simple gradient approximation)
        for r in range(base_size//2, 0, -6):
            t = r / (base_size/2)
            alpha = int(220 * (1 - (1 - t)**1.5))
            fill = (bg_color[0], bg_color[1], bg_color[2], max(0, alpha))
            draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill=fill)

        # helper to scale 64-based coords
        def s(x, y):
            return (int(x * base_size / 64), int(y * base_size / 64))

        # Cloud constructed from overlapping circles and a bottom rectangle
        circles = [ (22,30,12), (34,24,14), (46,30,12) ]
        for (x,y,radius) in circles:
            rr = int(radius * base_size / 64)
            draw.ellipse((s(x - radius, y - radius)[0], s(x - radius, y - radius)[1], s(x + radius, y + radius)[0], s(x + radius, y + radius)[1]), fill=(255,255,255,255))

        # bottom filler to flatten cloud base
        draw.rectangle((s(18, 30)[0], s(30,30)[1], s(50, 46)[0], s(46,46)[1]), fill=(255,255,255,255))

        # Arrow (upload): triangle tip above cloud, stem overlaps cloud slightly
        tip = s(34, 14)
        left = s(26, 28)
        right = s(42, 28)
        draw.polygon([tip, left, right], fill=bg_color)
        # stem
        stem_left = s(30, 28)
        stem_right = s(38, 46)
        draw.rectangle((stem_left[0], stem_left[1], stem_right[0], stem_right[1]), fill=bg_color)

        # small light line on arrow for contrast
        draw.line([ ( (tip[0]+left[0])//2, (tip[1]+left[1])//2 ), ( (tip[0]+right[0])//2, (tip[1]+right[1])//2 ) ], fill=(255,255,255,180), width=max(1, base_size//128))

        return img

    if not os.path.exists(ico_path):
        # pick color values
        if name == 'green':
            bg = (72, 187, 120, 255)
        else:
            bg = (220, 80, 90, 255)

        large = draw_modern_icon(base_size=256, bg_color=bg)
        # save multiple sizes into one ICO
        try:
            sizes = [(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)]
            large.save(ico_path, format='ICO', sizes=sizes)
        except Exception:
            # fallback: save PNG instead and use that
            png_path = ico_path.replace('.ico', '.png')
            large.resize((64,64), Image.LANCZOS).save(png_path, format='PNG')
            ico_path = png_path

    # load the ICO/PNG and return as PIL Image
    try:
        img = Image.open(ico_path)
        img = img.convert('RGBA')
        # ensure a reasonable size for tray (32x32)
        return img.resize((32,32), Image.LANCZOS)
    except Exception:
        # last fallback: return the old procedural icon
        return Image.new('RGBA', (32,32), (200,0,0,255))


class TrayApp:
    def __init__(self):
        self.icon = pystray.Icon('share-it')
        self.status = False
        self._lock = threading.Lock()
        self.icon.icon = create_image('red')
        self.icon.title = 'Share-It'
        self.icon.menu = pystray.Menu(
            pystray.MenuItem('Open in Browser', self.open_browser),
            pystray.MenuItem('Start Server', self.start_server),
            pystray.MenuItem('Stop Server', self.stop_server),
            pystray.MenuItem('Quit', self.quit)
        )
        self._stop = threading.Event()

    def start(self):
        t = threading.Thread(target=self._monitor_loop, daemon=True)
        t.start()
        self.icon.run()

    def _monitor_loop(self):
        while not self._stop.is_set():
            try:
                r = requests.get(URL, timeout=1.5)
                ok = r.status_code == 200
            except Exception:
                ok = False

            with self._lock:
                if ok != self.status:
                    self.status = ok
                    self.icon.icon = create_image('green' if ok else 'red')
                    self.icon.update_menu()
            time.sleep(CHECK_INTERVAL)

    def open_browser(self):
        import webbrowser
        webbrowser.open(URL)

    def start_server(self):
        # Start server via Start script
        try:
            subprocess.Popen(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', START_SCRIPT], cwd=ROOT)
        except Exception as e:
            print('Failed to start server:', e)

    def stop_server(self):
        try:
            subprocess.Popen(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', STOP_SCRIPT], cwd=ROOT)
        except Exception as e:
            print('Failed to stop server:', e)

    def quit(self):
        self._stop.set()
        self.icon.stop()


if __name__ == '__main__':
    app = TrayApp()
    app.start()
