import os
import json
import threading
import time
import webbrowser
from pathlib import Path
from datetime import datetime, timezone
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import requests


def human_bytes(num: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024.0:
            return f"{num:3.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


def upload_file(api_base: str, file_path: Path, expires: int) -> dict:
    url = api_base.rstrip("/") + "/api/upload"
    with open(file_path, "rb") as f:
        files = {"file": (file_path.name, f)}
        data = {"expires_in_days": str(expires)}
        resp = requests.post(url, files=files, data=data, timeout=300)
        resp.raise_for_status()
        return resp.json()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Share-It")
        self.geometry("820x560")
        try:
            self.iconbitmap(default='')
        except Exception:
            pass

        self.selected_file = None
        self.last_link = None
        self.config_path = Path(__file__).with_name("frontend_config.json")
        self.history_path = Path(__file__).with_name("frontend_history.json")
        self.settings = self.load_settings()
        self.history = self.load_history()

        self._build_ui()
        self.refresh_uploads_list()

        # Background validation to auto-remove deleted links
        self._stop_event = threading.Event()
        self._start_background_validation()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}
        frm = ttk.Frame(self)
        frm.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(frm, text="Share-It", font=("Segoe UI", 13, "bold"))
        title.grid(row=0, column=0, columnspan=3, sticky="w", **pad)
        self.settings_btn = ttk.Button(frm, text="Einstellungen", command=self.open_settings)
        self.settings_btn.grid(row=0, column=3, sticky="e", **pad)

        ttk.Label(frm, text="Datei:").grid(row=1, column=0, sticky="w", **pad)
        self.file_var = tk.StringVar()
        self.file_entry = ttk.Entry(frm, textvariable=self.file_var)
        self.file_entry.grid(row=1, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Button(frm, text="Auswählen", command=self.choose_file).grid(row=1, column=3, sticky="e", **pad)

        ttk.Label(frm, text="Ablauf (Tage, 0 = One-Time-Download)").grid(row=2, column=0, sticky="w", **pad)
        self.expires = tk.IntVar(value=7)
        # Integer-Schieberegler mit Schrittweite 1 und Anzeige
        self.exp_scale = tk.Scale(
            frm,
            from_=0,
            to=30,
            orient=tk.HORIZONTAL,
            resolution=1,
            showvalue=False,
            variable=self.expires,
            command=self._on_exp_change,
        )
        self.exp_scale.grid(row=2, column=1, columnspan=2, sticky="ew", **pad)
        self.exp_value_lbl = ttk.Label(frm, text="7")
        self.exp_value_lbl.grid(row=2, column=3, sticky="e", **pad)

        self.upload_btn = ttk.Button(frm, text="Hochladen", command=self.on_upload, state=tk.DISABLED)
        self.upload_btn.grid(row=3, column=0, sticky="w", **pad)
        self.open_btn = ttk.Button(frm, text="Link öffnen", command=self.open_link, state=tk.DISABLED)
        self.open_btn.grid(row=3, column=1, sticky="w", **pad)
        self.copy_btn = ttk.Button(frm, text="Kopieren", command=self.copy_link, state=tk.DISABLED)
        self.copy_btn.grid(row=3, column=2, sticky="w", **pad)

        # Meine Uploads Abschnitt
        sep1 = ttk.Separator(frm)
        sep1.grid(row=4, column=0, columnspan=4, sticky="ew", **pad)

        ttk.Label(frm, text="Meine Uploads (nicht abgelaufen)", font=("Segoe UI", 10, "bold")).grid(row=5, column=0, columnspan=2, sticky="w", **pad)
        self.uploads_tree = ttk.Treeview(frm, columns=("name","expires","url"), show="headings", height=8)
        self.uploads_tree.heading("name", text="Datei")
        self.uploads_tree.heading("expires", text="Läuft ab")
        self.uploads_tree.heading("url", text="URL")
        self.uploads_tree.column("name", width=260)
        self.uploads_tree.column("expires", width=160)
        self.uploads_tree.column("url", width=300)
        self.uploads_tree.grid(row=6, column=0, columnspan=4, sticky="nsew", **pad)
        self.uploads_tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        btn_bar = ttk.Frame(frm)
        btn_bar.grid(row=7, column=0, columnspan=4, sticky="w", **pad)
        self.copy_sel_btn = ttk.Button(btn_bar, text="Link kopieren", command=self.copy_selected, state=tk.DISABLED)
        self.copy_sel_btn.pack(side=tk.LEFT, padx=(0,6))
        self.open_sel_btn = ttk.Button(btn_bar, text="Im Browser öffnen", command=self.open_selected, state=tk.DISABLED)
        self.open_sel_btn.pack(side=tk.LEFT, padx=(0,6))
        self.remove_sel_btn = ttk.Button(btn_bar, text="Aus Liste entfernen", command=self.remove_selected, state=tk.DISABLED)
        self.remove_sel_btn.pack(side=tk.LEFT, padx=(0,6))
        ttk.Button(btn_bar, text="Aktualisieren", command=self.refresh_uploads_click).pack(side=tk.LEFT)

        # Log unten
        self.log = tk.Text(frm, height=8)
        self.log.grid(row=8, column=0, columnspan=4, sticky="nsew", **pad)
        self.log.configure(state=tk.DISABLED)

        frm.columnconfigure(1, weight=1)
        frm.columnconfigure(2, weight=1)
        frm.rowconfigure(6, weight=1)
        frm.rowconfigure(8, weight=1)

    def logln(self, msg: str):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def choose_file(self):
        fp = filedialog.askopenfilename()
        if fp and os.path.isfile(fp):
            self.selected_file = Path(fp)
            self.file_var.set(fp)
            size = self.selected_file.stat().st_size
            self.logln(f"Ausgewählt: {self.selected_file.name} ({human_bytes(size)})")
            self.upload_btn.config(state=tk.NORMAL)
        else:
            self.selected_file = None
            self.upload_btn.config(state=tk.DISABLED)

    def on_upload(self):
        if not self.selected_file:
            messagebox.showwarning("Hinweis", "Bitte eine Datei auswählen.")
            return
        api = self.settings.get("api_url", "http://127.0.0.1:8000").strip()
        # Begrenzen auf 0..30 Tage
        try:
            expires = int(self.expires.get())
        except Exception:
            expires = 7
        expires = max(0, min(30, expires))
        self.upload_btn.config(state=tk.DISABLED)
        self.logln("Lade hoch…")

        def worker():
            try:
                data = upload_file(api, self.selected_file, expires)
                if data.get("ok"):
                    self.last_link = data.get("download_url")
                    self.logln(f"Fertig. Download-Link: {self.last_link}")
                    exp = data.get("expires_at")
                    if exp:
                        self.logln(f"Läuft ab am: {exp}")
                    else:
                        self.logln("Kein Ablaufdatum oder One-Time-Download.")
                    # In lokale Historie aufnehmen
                    self.add_history_item({
                        "filename": data.get("filename") or self.selected_file.name,
                        "download_url": self.last_link,
                        "token": data.get("token"),
                        "expires_at": data.get("expires_at"),
                        "size": data.get("size"),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
                    self.refresh_uploads_list()
                    self.open_btn.config(state=tk.NORMAL)
                    self.copy_btn.config(state=tk.NORMAL)
                else:
                    self.logln("Fehler beim Upload: Unbekannte Antwort")
            except requests.HTTPError as e:
                try:
                    err = e.response.json()
                    self.logln(f"Fehler: {err.get('detail', str(e))}")
                except Exception:
                    self.logln(f"HTTP Fehler: {e}")
            except Exception as e:
                self.logln(f"Fehler: {e}")
            finally:
                self.upload_btn.config(state=tk.NORMAL)

        threading.Thread(target=worker, daemon=True).start()

    def open_link(self):
        if self.last_link:
            webbrowser.open(self.last_link)
            # Nach kurzer Zeit prüfen, ob Link ungültig wurde (z.B. One-Time)
            def worker():
                time.sleep(3)
                try:
                    self._network_prune_once()
                finally:
                    self.after(0, self.refresh_uploads_list)
            threading.Thread(target=worker, daemon=True).start()

    def copy_link(self):
        if self.last_link:
            self.clipboard_clear()
            self.clipboard_append(self.last_link)
            self.logln("Link kopiert.")

    def _on_exp_change(self, value):
        try:
            iv = int(float(value))
        except Exception:
            iv = 7
        self.exp_value_lbl.config(text=str(iv))

    # Upload-Historie (lokal, pro Benutzer)
    def load_history(self) -> list:
        try:
            if self.history_path.exists():
                with open(self.history_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
        return []

    def save_history(self):
        try:
            with open(self.history_path, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logln(f"Konnte Historie nicht speichern: {e}")

    def add_history_item(self, item: dict):
        # Verhindere Duplikate anhand Token/URL
        token = item.get("token")
        url = item.get("download_url")
        if token:
            self.history = [it for it in self.history if it.get("token") != token]
        elif url:
            self.history = [it for it in self.history if it.get("download_url") != url]
        self.history.insert(0, item)
        self.save_history()

    def _is_expired(self, expires_at: str | None) -> bool:
        if not expires_at:
            return False
        try:
            # Support timestamps with trailing 'Z' and without timezone
            ts = expires_at.strip()
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            # Falls ungültig, als abgelaufen behandeln
            return True
        return datetime.now(timezone.utc) > dt

    def refresh_uploads_list(self):
        # Entferne abgelaufene aus Ansicht (optional: gleichzeitig aus Datei entfernen)
        pruned = []
        for it in self.history:
            if not self._is_expired(it.get("expires_at")):
                pruned.append(it)
        if len(pruned) != len(self.history):
            self.history = pruned
            self.save_history()

        # Liste neu füllen
        for row in self.uploads_tree.get_children():
            self.uploads_tree.delete(row)
        for it in self.history:
            name = it.get("filename") or "(unbekannt)"
            exp = it.get("expires_at") or "nie/one-time"

            url = it.get("download_url") or ""
            self.uploads_tree.insert("", tk.END, values=(name, exp, url))
        self._update_sel_buttons()

    def refresh_uploads_click(self):
        # Run a quick network validation in background, then refresh UI
        def worker():
            try:
                self._network_prune_once()
            finally:
                self.after(0, self.refresh_uploads_list)
        threading.Thread(target=worker, daemon=True).start()

    def _get_selected_values(self):
        sel = self.uploads_tree.selection()
        if not sel:
            return None
        vals = self.uploads_tree.item(sel[0], "values")
        # values: (name, expires, url)
        return vals

    def _update_sel_buttons(self):
        enabled = tk.NORMAL if self.uploads_tree.selection() else tk.DISABLED
        for b in (self.copy_sel_btn, self.open_sel_btn, self.remove_sel_btn):
            b.config(state=enabled)

    def _on_tree_select(self, _evt=None):
        self._update_sel_buttons()

    def copy_selected(self):
        vals = self._get_selected_values()
        if not vals:
            return
        url = vals[2]
        if url:
            self.clipboard_clear()
            self.clipboard_append(url)
            self.logln("Link kopiert (Auswahl).")

    def open_selected(self):
        vals = self._get_selected_values()
        if not vals:
            return
        url = vals[2]
        if url:
            webbrowser.open(url)
            # Nach kurzer Zeit prüfen, ob Link ungültig wurde (z.B. One-Time)
            def worker():
                time.sleep(3)
                try:
                    self._network_prune_once()
                finally:
                    self.after(0, self.refresh_uploads_list)
            threading.Thread(target=worker, daemon=True).start()

    def remove_selected(self):
        vals = self._get_selected_values()
        if not vals:
            return
        name, _exp, url = vals
        # Entferne aus history per URL
        self.history = [it for it in self.history if it.get("download_url") != url]
        self.save_history()
        self.refresh_uploads_list()
        self.logln(f"Aus Liste entfernt: {name}")

    # Hintergrundvalidierung: entferne Links, die 404/410 zurückgeben
    def _network_prune_once(self):
        to_remove_urls = set()
        for it in list(self.history):
            url = it.get("download_url")
            if not url:
                continue
            # Wenn bereits per Zeit abgelaufen, wird es woanders entfernt
            if self._is_expired(it.get("expires_at")):
                continue
            try:
                # 1) HEAD versuchen
                resp = requests.head(url, allow_redirects=True, timeout=5)
                if resp.status_code in (404, 410):
                    to_remove_urls.add(url)
                    continue
                # 2) Falls HEAD nichts sagt (z.B. 200), zusätzlich API-Status prüfen
                token = it.get("token")
                if token:
                    api_base = self.settings.get("api_url", "http://127.0.0.1:8000").rstrip("/")
                    status_url = f"{api_base}/api/link-status/{token}"
                    sresp = requests.get(status_url, timeout=5)
                    if sresp.ok:
                        data = sresp.json()
                        if not data.get("exists", True):
                            to_remove_urls.add(url)
            except requests.RequestException:
                # Netzwerkfehler ignorieren (später erneut versuchen)
                pass

        if to_remove_urls:
            self.history = [h for h in self.history if h.get("download_url") not in to_remove_urls]
            self.save_history()
            self.logln(f"{len(to_remove_urls)} ungültige Links aus der Liste entfernt")

    def _auto_validate_loop(self, interval_seconds: int = 600):
        # Initial kleine Verzögerung, dann periodisch prüfen
        time.sleep(3)
        while not self._stop_event.is_set():
            try:
                self._network_prune_once()
                # UI aktualisieren im Hauptthread
                self.after(0, self.refresh_uploads_list)
            except Exception:
                pass
            # Warte mit Abbruchprüfung
            for _ in range(interval_seconds):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def _start_background_validation(self):
        t = threading.Thread(target=self._auto_validate_loop, args=(600,), daemon=True)
        t.start()

    def _on_close(self):
        # Signalisiere Hintergrundthread zum Beenden, dann Fenster schließen
        try:
            self._stop_event.set()
        except Exception:
            pass
        self.destroy()

    # Settings management
    def load_settings(self) -> dict:
        defaults = {"api_url": "http://127.0.0.1:8000", "host": "127.0.0.1", "port": 8000}
        try:
            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return {**defaults, **data}
        except Exception:
            pass
        return defaults

    def save_settings(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logln(f"Konnte Einstellungen nicht speichern: {e}")

    def open_settings(self):
        SettingsWindow(self, self.settings.copy(), self._apply_settings)

    def _apply_settings(self, new_settings: dict):
        # minimal validation
        host = new_settings.get("host") or "127.0.0.1"
        try:
            port = int(new_settings.get("port", 8000))
        except Exception:
            port = 8000
        url = new_settings.get("api_url") or f"http://{host}:{port}"
        self.settings = {"api_url": url.strip(), "host": host.strip(), "port": port}
        self.save_settings()
        self.logln(f"Einstellungen gespeichert. API: {self.settings['api_url']}")


class SettingsWindow(tk.Toplevel):
    def __init__(self, parent: App, current: dict, on_save):
        super().__init__(parent)
        self.title("Einstellungen")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.on_save = on_save

        pad = {"padx": 10, "pady": 6}
        frm = ttk.Frame(self)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="Backend API URL").grid(row=0, column=0, sticky="w", **pad)
        self.api_var = tk.StringVar(value=current.get("api_url", "http://127.0.0.1:8000"))
        ttk.Entry(frm, textvariable=self.api_var, width=40).grid(row=0, column=1, sticky="ew", **pad)

        ttk.Label(frm, text="Host/IP").grid(row=1, column=0, sticky="w", **pad)
        self.host_var = tk.StringVar(value=current.get("host", "127.0.0.1"))
        ttk.Entry(frm, textvariable=self.host_var, width=25).grid(row=1, column=1, sticky="w", **pad)

        ttk.Label(frm, text="Port").grid(row=2, column=0, sticky="w", **pad)
        self.port_var = tk.StringVar(value=str(current.get("port", 8000)))
        ttk.Entry(frm, textvariable=self.port_var, width=10).grid(row=2, column=1, sticky="w", **pad)

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=2, sticky="e", **pad)
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btns, text="Speichern", command=self._save).pack(side=tk.RIGHT)

        frm.columnconfigure(1, weight=1)

    def _save(self):
        data = {
            "api_url": self.api_var.get().strip(),
            "host": self.host_var.get().strip(),
            "port": self.port_var.get().strip(),
        }
        try:
            self.on_save(data)
            self.destroy()
        except Exception as e:
            messagebox.showerror("Fehler", f"Konnte Einstellungen nicht speichern: {e}")


if __name__ == "__main__":
    App().mainloop()
