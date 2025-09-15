import os
import sys
import json
import threading
import time
import webbrowser
from pathlib import Path
from datetime import datetime, timezone
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import tkinter.font as tkfont

import requests
try:
    from PIL import Image, ImageTk  # type: ignore
    _HAS_PIL = True
except Exception:
    Image = None  # type: ignore
    ImageTk = None  # type: ignore
    _HAS_PIL = False


    class Tooltip:
        """Simple tooltip for a widget.
        Usage: Tooltip(widget, "your text")
        """
        def __init__(self, widget, text: str, delay: int = 500):
            self.widget = widget
            self.text = text
            self.delay = delay
            self._id = None
            self._tip = None
            widget.bind("<Enter>", self._on_enter, add="+")
            widget.bind("<Leave>", self._on_leave, add="+")
            widget.bind("<Motion>", self._on_motion, add="+")

        def _on_enter(self, _evt=None):
            self._schedule()

        def _on_motion(self, _evt=None):
            # restart timer on move for a smoother feel
            self._schedule()

        def _on_leave(self, _evt=None):
            self._cancel()
            self._hide()

        def _schedule(self):
            self._cancel()
            self._id = self.widget.after(self.delay, self._show)

        def _cancel(self):
            if self._id is not None:
                try:
                    self.widget.after_cancel(self._id)
                except Exception:
                    pass
                self._id = None

        def _show(self):
            if self._tip is not None:
                return
            try:
                x = self.widget.winfo_rootx() + 20
                y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
                self._tip = tk.Toplevel(self.widget)
                self._tip.wm_overrideredirect(True)
                self._tip.wm_geometry(f"+{x}+{y}")
                lbl = tk.Label(
                    self._tip,
                    text=self.text,
                    background="#111827",
                    foreground="#e5e7eb",
                    padx=6,
                    pady=3,
                    relief=tk.SOLID,
                    borderwidth=1,
                )
                lbl.pack()
            except Exception:
                # Fail silently if tooltip cannot be created
                self._tip = None

        def _hide(self):
            if self._tip is not None:
                try:
                    self._tip.destroy()
                except Exception:
                    pass
                self._tip = None


def human_bytes(num: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024.0:
            return f"{num:3.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


def upload_file(api_base: str, file_path: Path, expires: int, token: str | None = None) -> dict:
    """Upload Datei zum Backend.
    Wenn token gesetzt -> Header 'X-DateiLink-Token' mitsenden.
    """
    url = api_base.rstrip("/") + "/api/upload"
    headers = {}
    if token:
        headers["X-DateiLink-Token"] = token.strip()
    with open(file_path, "rb") as f:
        files = {"file": (file_path.name, f)}
        data = {"expires_in_days": str(expires)}
        resp = requests.post(url, files=files, data=data, headers=headers, timeout=300)
        resp.raise_for_status()
        return resp.json()


def _app_dir() -> Path:
    """Return directory for config/history: next to .exe when frozen, else script dir."""
    if getattr(sys, "frozen", False):  # PyInstaller onefile
        return Path(sys.executable).parent
    return Path(__file__).parent


def _res_dir() -> Path:
    """Return directory for bundled resources (PyInstaller _MEIPASS) or script dir.
    Use this for read-only assets like images/icons that are packaged into the exe.
    Keep _app_dir for writable files like config/history.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    return Path(__file__).parent


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DateiLink")
        self.geometry("820x560")

        # Modernes Icon setzen (bevorzugt aus gebündelten Ressourcen ./static)
        icon_path = _res_dir() / "static" / "dateilink.ico"
        if icon_path.exists():
            try:
                self.iconbitmap(str(icon_path))
            except Exception:
                # Fallback: try iconphoto via PIL if available
                if _HAS_PIL:
                    try:
                        _img = Image.open(icon_path)
                        self._app_icon = ImageTk.PhotoImage(_img)
                        self.iconphoto(True, self._app_icon)
                    except Exception:
                        pass

        # Styles first for consistent look
        self._setup_style()

        self.selected_file = None
        self.last_link = None
        base_dir = _app_dir()
        # Use new filenames; migrate legacy ones if they exist
        self.config_path = base_dir / "config.json"
        self.history_path = base_dir / "history.json"
        try:
            self._migrate_legacy_file(base_dir / "frontend_config.json", self.config_path)
            self._migrate_legacy_file(base_dir / "frontend_history.json", self.history_path)
        except Exception:
            # Migration errors are non-fatal; continue with defaults
            pass
        self.settings = self.load_settings()
        self.history = self.load_history()
        # Mapping: Treeview item id -> URL (URL wird nicht mehr als Spalte angezeigt)
        self.row_url = {}

        self._build_ui()
        self.refresh_uploads_list()

        # Background validation to auto-remove deleted links
        self._stop_event = threading.Event()
        self._start_background_validation()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        pad = {"padx": 10, "pady": 8}

        # Header bar
        header_bg = "#1f2937"  # dark slate
        header = tk.Frame(self, bg=header_bg)
        header.pack(fill=tk.X, side=tk.TOP)
        # Icon in header (prefer dateilink.ico; fallback to logo.png)
        try:
            ico_path = _res_dir() / "static" / "dateilink.ico"
            if _HAS_PIL and ico_path.exists():
                img = Image.open(ico_path)
                # Resize to a good header size
                img = img.resize((20, 20), Image.LANCZOS)
                self._header_icon = ImageTk.PhotoImage(img)
                tk.Label(header, image=self._header_icon, bg=header_bg).pack(side=tk.LEFT, padx=(12, 8), pady=8)
            else:
                logo_path = _res_dir() / "static" / "logo.png"
                if logo_path.exists():
                    self._logo_img = tk.PhotoImage(file=str(logo_path))
                    tk.Label(header, image=self._logo_img, bg=header_bg).pack(side=tk.LEFT, padx=(12, 8), pady=8)
        except Exception:
            pass
        tk.Label(header, text="DateiLink", fg="#ffffff", bg=header_bg, font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT, pady=8)
        # Settings button as symbol with tooltip
        self.settings_btn = ttk.Button(header, text="⚙", style="Header.TButton", width=3, command=self.open_settings)
        self.settings_btn.pack(side=tk.RIGHT, padx=12, pady=8)

        # Content card
        outer = ttk.Frame(self, style="Outer.TFrame")
        outer.pack(fill=tk.BOTH, expand=True)
        frm = ttk.Frame(outer, style="Card.TFrame")
        frm.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        ttk.Label(frm, text="Datei:").grid(row=1, column=0, sticky="w", **pad)
        self.file_var = tk.StringVar()
        self.file_entry = ttk.Entry(frm, textvariable=self.file_var)
        self.file_entry.grid(row=1, column=1, columnspan=2, sticky="ew", **pad)
        self.pick_btn = ttk.Button(frm, text="📁", width=3, command=self.choose_file)
        self.pick_btn.grid(row=1, column=3, sticky="e", **pad)

        ttk.Label(frm, text="Ablauf (Tage, 0 = One-Time-Download)").grid(row=2, column=0, sticky="w", **pad)
        self.expires = tk.IntVar(value=2)
        self.exp_scale = ttk.Scale(
            frm, from_=0, to=30, orient=tk.HORIZONTAL, variable=self.expires, command=self._on_exp_change
        )
        self.exp_scale.grid(row=2, column=1, columnspan=2, sticky="ew", **pad)
        self.exp_value_lbl = ttk.Label(frm, text="2")
        self.exp_value_lbl.grid(row=2, column=3, sticky="e", **pad)

        self.upload_btn = ttk.Button(frm, text="⏫", width=3, style="Accent.TButton", command=self.on_upload, state=tk.DISABLED)
        self.upload_btn.grid(row=3, column=0, sticky="w", **pad)

        # Meine Uploads Abschnitt
        sep1 = ttk.Separator(frm)
        sep1.grid(row=4, column=0, columnspan=4, sticky="ew", **pad)

        ttk.Label(frm, text="Meine Uploads (nicht abgelaufen)", font=("Segoe UI", 10, "bold")).grid(row=5, column=0, columnspan=2, sticky="w", **pad)
        # URL nicht anzeigen: nur Datei, Ablauf, und Download-Zähler
        self.uploads_tree = ttk.Treeview(
            frm,
            columns=("name", "expires", "downloads"),
            show="headings",
            height=10,
            style="Modern.Treeview",
        )
        self.uploads_tree.heading("name", text="Datei")
        self.uploads_tree.heading("expires", text="Läuft ab")
        self.uploads_tree.heading("downloads", text="Heruntergeladen")
        # Make the file column a bit narrower and let 'expires' flex to fill
        self.uploads_tree.column("name", width=360, stretch=False)
        self.uploads_tree.column("expires", width=220, stretch=True)
        self.uploads_tree.column("downloads", width=120, anchor="center", stretch=False)
        self.uploads_tree.grid(row=6, column=0, columnspan=4, sticky="nsew", **pad)
        self.uploads_tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        btn_bar = ttk.Frame(frm)
        btn_bar.grid(row=7, column=0, columnspan=4, sticky="w", **pad)
        self.copy_sel_btn = ttk.Button(btn_bar, text="📋", width=3, command=self.copy_selected, state=tk.DISABLED)
        self.copy_sel_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.open_sel_btn = ttk.Button(btn_bar, text="🌐", width=3, command=self.open_selected, state=tk.DISABLED)
        self.open_sel_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.remove_sel_btn = ttk.Button(btn_bar, text="🗑", width=3, command=self.remove_selected, state=tk.DISABLED)
        self.remove_sel_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.refresh_btn = ttk.Button(btn_bar, text="🔄", width=3, style="Secondary.TButton", command=self.refresh_uploads_click)
        self.refresh_btn.pack(side=tk.LEFT, padx=(0, 6))

        # Log unten
        self.log = tk.Text(frm, height=8, bg="#0f172a", fg="#e5e7eb", insertbackground="#ffffff", relief=tk.FLAT, borderwidth=0)
        self.log.grid(row=8, column=0, columnspan=4, sticky="nsew", **pad)
        self.log.configure(state=tk.DISABLED)

        # Powered by link at the bottom
        powered_by_frame = ttk.Frame(frm)
        powered_by_frame.grid(row=9, column=0, columnspan=4, sticky="ew", padx=8, pady=(0, 6))
        hirsch_lorenz_link = ttk.Label(powered_by_frame, text="Hirsch-Lorenz", font=("Segoe UI", 9), foreground="blue", cursor="hand2")
        hirsch_lorenz_link.pack(side=tk.RIGHT)
        hirsch_lorenz_link.bind("<Button-1>", lambda e: webbrowser.open("https://hirsch-lorenz.de"))
        powered_by_text = ttk.Label(powered_by_frame, text="Powered by ", font=("Segoe UI", 9))
        powered_by_text.pack(side=tk.RIGHT)

        frm.columnconfigure(1, weight=1)
        frm.columnconfigure(2, weight=1)
        frm.rowconfigure(6, weight=1)
        frm.rowconfigure(8, weight=1)

        # Zebra striping for treeview rows
        try:
            self.uploads_tree.tag_configure("odd", background="#fafafa")
            self.uploads_tree.tag_configure("even", background="#ffffff")
        except Exception:
            pass

        # Tooltips for icon buttons
        try:
            Tooltip(self.settings_btn, "Einstellungen")
            Tooltip(self.pick_btn, "Datei auswählen")
            Tooltip(self.upload_btn, "Hochladen")
            Tooltip(self.copy_sel_btn, "Link kopieren")
            Tooltip(self.open_sel_btn, "Im Browser öffnen")
            Tooltip(self.remove_sel_btn, "Aus Liste entfernen")
            Tooltip(self.refresh_btn, "Aktualisieren")
        except Exception:
            pass

    def _setup_style(self):
        # Global fonts using named Tk fonts (safer than option_add with strings)
        try:
            default_font = tkfont.nametofont("TkDefaultFont")
            default_font.configure(family="Segoe UI", size=10)
            text_font = tkfont.nametofont("TkTextFont")
            text_font.configure(family="Segoe UI", size=10)
            fixed_font = tkfont.nametofont("TkFixedFont")
            fixed_font.configure(family="Consolas", size=10)
        except Exception:
            pass

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        bg = "#f7f9fc"
        card_bg = "#ffffff"
        border = "#e5e7eb"
        text = "#1f2937"
        muted = "#6b7280"
        accent = "#e87722"

        # Base
        self.configure(bg=bg)
        style.configure("TFrame", background=bg)
        style.configure("Outer.TFrame", background=bg)
        style.configure("Card.TFrame", background=card_bg, relief="solid", bordercolor=border, borderwidth=1)
        style.configure("TLabel", background=card_bg, foreground=text)
        style.configure("Header.TButton", padding=6)

        # Buttons
        style.configure("TButton", padding=(10, 6), font=("Segoe UI", 10))
        style.configure("Accent.TButton", background=accent, foreground="#ffffff", borderwidth=0, focusthickness=0)
        style.map("Accent.TButton", background=[("active", "#ff8d33"), ("disabled", "#d1d5db")])
        style.configure("Secondary.TButton", background="#e5e7eb", foreground=text, borderwidth=0)
        style.map("Secondary.TButton", background=[("active", "#d1d5db")])

        # Inputs
        style.configure("TEntry", padding=6)
        style.configure("TScale", troughcolor="#e5e7eb")

        # Treeview
        style.configure(
            "Modern.Treeview",
            background=card_bg,
            fieldbackground=card_bg,
            foreground=text,
            rowheight=26,
            bordercolor=border,
            borderwidth=1,
        )
        style.configure("Modern.Treeview.Heading", background=card_bg, foreground=muted, padding=6)
        style.map("Treeview", background=[("selected", "#cfe8ff")])

    def _migrate_legacy_file(self, old_path: Path, new_path: Path):
        """Rename legacy JSON files to new names once, preserving data.
        If the old file exists and the new one doesn't, attempt rename; fallback to copy.
        """
        try:
            if old_path.exists() and not new_path.exists():
                try:
                    old_path.rename(new_path)
                except Exception:
                    # Fallback: copy contents
                    try:
                        with open(old_path, "r", encoding="utf-8") as fsrc:
                            data = fsrc.read()
                        with open(new_path, "w", encoding="utf-8") as fdst:
                            fdst.write(data)
                        try:
                            old_path.unlink()
                        except Exception:
                            pass
                    except Exception:
                        # If copying fails, leave files as-is
                        pass
                self.logln(f"Datei migriert: {old_path.name} -> {new_path.name}")
        except Exception:
            # Ignore migration issues silently in production
            pass

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
                data = upload_file(api, self.selected_file, expires, self.settings.get("upload_token"))
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
                        # Neue Zählerspalte; für Alt-Daten weiter kompatibel
                        "download_count": 0,
                        "downloaded": False,
                    })
                    self.refresh_uploads_list()
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

    # Export/Import der Upload-Liste -------------------------------------------------
    def export_history(self):
        try:
            ts = datetime.now().strftime("%Y-%m-%d")
            default_name = f"dateilink_uploads_{ts}.json"
            path = filedialog.asksaveasfilename(
                title="Uploads exportieren",
                defaultextension=".json",
                initialfile=default_name,
                filetypes=[("JSON", "*.json"), ("Alle Dateien", "*.*")],
            )
            if not path:
                return
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=2, ensure_ascii=False)
            self.logln(f"Uploads exportiert: {path}")
        except Exception as e:
            messagebox.showerror("Fehler", f"Export fehlgeschlagen: {e}")

    def import_history(self):
        try:
            path = filedialog.askopenfilename(
                title="Uploads importieren",
                filetypes=[("JSON", "*.json"), ("Alle Dateien", "*.*")],
            )
            if not path:
                return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("JSON muss eine Liste von Objekten sein")
            cleaned = self._normalize_history_items(data)
            if cleaned is None:
                raise ValueError("Ungültiges Format der Upload-Liste")

            replace = messagebox.askyesno(
                "Import",
                "Sollen die aktuellen Einträge ERSETZT werden?\nNein = Zusammenführen (Duplikate werden entfernt)",
            )
            if replace:
                self.history = cleaned
            else:
                self.history = self._merge_history(self.history, cleaned)
            self.save_history()
            self.refresh_uploads_list()
            self.logln(f"Uploads importiert: {path} ({len(cleaned)} Einträge)")
        except Exception as e:
            messagebox.showerror("Fehler", f"Import fehlgeschlagen: {e}")

    def _normalize_history_items(self, items: list) -> list | None:
        norm = []
        for it in items:
            if not isinstance(it, dict):
                return None
            n = {
                "filename": str(it.get("filename") or it.get("name") or ""),
                "download_url": str(it.get("download_url") or it.get("url") or ""),
                "token": (it.get("token") or None),
                "expires_at": (it.get("expires_at") or None),
                "size": it.get("size"),
                "created_at": it.get("created_at") or datetime.now(timezone.utc).isoformat(),
                "downloaded": bool(it.get("downloaded", False)),
            }
            # Minimal: Es muss mindestens eine URL oder ein Token vorhanden sein
            if not n["download_url"] and not n["token"]:
                # überspringen statt failen: toleranter Import
                continue
            norm.append(n)
        return norm

    def _merge_history(self, existing: list, incoming: list) -> list:
        # Duplikate anhand token bevorzugt, sonst download_url
        out = []
        seen = set()
        def key_for(it):
            return (it.get("token") or "") + "|" + (it.get("download_url") or "")

        # incoming zuerst (neuer gewinnt), dann existing
        for src in (incoming, existing):
            for it in src:
                k = key_for(it)
                if k in seen:
                    continue
                seen.add(k)
                out.append(it)

        # optional: nach created_at absteigend sortieren, fallback: unsortiert
        def parse_dt(s):
            try:
                if isinstance(s, str):
                    t = s.strip()
                    if t.endswith("Z"):
                        t = t[:-1] + "+00:00"
                    return datetime.fromisoformat(t)
            except Exception:
                pass
            return datetime.min.replace(tzinfo=timezone.utc)

        out.sort(key=lambda it: parse_dt(it.get("created_at")), reverse=True)
        return out

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
        self.row_url.clear()
        for row in self.uploads_tree.get_children():
            self.uploads_tree.delete(row)
        for it in self.history:
            name = it.get("filename") or "(unbekannt)"
            exp = it.get("expires_at") or "nie/one-time"
            # Anzeige: Zähler statt Ja/Nein; fallback für Alt-Historie
            count = it.get("download_count")
            if isinstance(count, bool):
                count = 1 if count else 0
            if count is None:
                count = 1 if it.get("downloaded") else 0
            try:
                count = int(count)
            except Exception:
                count = 0
            url = it.get("download_url") or ""
            iid = self.uploads_tree.insert("", tk.END, values=(name, exp, str(count)))
            # URL pro Zeile merken (nicht sichtbar)
            self.row_url[str(iid)] = url
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
        iid = sel[0]
        vals = self.uploads_tree.item(iid, "values")
        # values: (name, expires, downloads) – URL separat gemappt
        name = vals[0] if len(vals) > 0 else ""
        expires = vals[1] if len(vals) > 1 else ""
        # downloads at vals[2] (not used here)
        url = self.row_url.get(str(iid), "")
        return (name, expires, url)

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
                            continue
                        # Update download counter and legacy 'downloaded' flag
                        new_count = data.get("download_count")
                        try:
                            new_count = int(new_count) if new_count is not None else None
                        except Exception:
                            new_count = None
                        if new_count is not None:
                            if it.get("download_count") != new_count:
                                it["download_count"] = new_count
                                # Maintain legacy boolean for compatibility
                                if new_count > 0:
                                    it["downloaded"] = True
                                self.save_history()
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
        # host/port entfernt – nur noch komplette API URL nötig
        defaults = {"api_url": "http://127.0.0.1:8000", "upload_token": ""}
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
        url = (new_settings.get("api_url") or "http://127.0.0.1:8000").strip()
        upload_token = new_settings.get("upload_token", "").strip()
        self.settings = {"api_url": url, "upload_token": upload_token}
        self.save_settings()
        masked = (upload_token[:4] + "***") if upload_token else "(kein Token)"
        self.logln(f"Einstellungen gespeichert. API: {url} | Token: {masked}")


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
        ttk.Entry(frm, textvariable=self.api_var, width=50).grid(row=0, column=1, sticky="ew", **pad)

        ttk.Label(frm, text="Upload Token").grid(row=1, column=0, sticky="w", **pad)
        self.token_var = tk.StringVar(value=current.get("upload_token", ""))
        token_entry = ttk.Entry(frm, textvariable=self.token_var, width=50, show="*")
        token_entry.grid(row=1, column=1, sticky="ew", **pad)
        # Removed the 'anzeigen' checkbox; token remains masked by default

        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, columnspan=3, sticky="e", **pad)
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btns, text="Speichern", command=self._save).pack(side=tk.RIGHT)

        frm.columnconfigure(1, weight=1)

    def _save(self):
        data = {
            "api_url": self.api_var.get().strip(),
            "upload_token": self.token_var.get().strip(),
        }
        try:
            self.on_save(data)
            self.destroy()
        except Exception as e:
            messagebox.showerror("Fehler", f"Konnte Einstellungen nicht speichern: {e}")


if __name__ == "__main__":
    App().mainloop()
