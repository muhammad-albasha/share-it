# DateiLink (Self‑Hosted)

Eigenes, kleines File‑Sharing: Datei hochladen → URL bekommen → per E‑Mail teilen. Optionales Ablaufdatum mit **automatischem Cleanup**.

## Features
- API-only Backend (FastAPI) with file upload, download, and automatic cleanup
- Desktop Frontend (Tkinter) for easy uploads and link sharing
- Expiration: selectable 0–30 days (0 = one-time download)
- Persistent settings (API URL, host, port)
- Meine Uploads: local, persistent list of non-expired uploads with Copy/Open/Remove actions
- Local history file: `frontend_history.json` (stored next to the app)

## Sicherheit & Zugriffskontrolle

This project is now split into:
- API-only backend (FastAPI) with no web UI
- Desktop frontend (Tkinter) that talks to the API and can be packaged as an .exe

## 1) Setup

On Windows (PowerShell):

```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2) Run the API backend

```
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open API docs: http://127.0.0.1:8000/docs

Notes:
- Backend runs API-only. HTML templates and static UI are not served anymore.
- Storage is in the `storage/` folder (auto-created). Database is `files.db`.
- Config is stored in `config.json`.

## 3) Run the desktop frontend

```
python frontend_desktop.py
```

Use the GUI to select a file and upload to the API. You will get a copyable download link.
The "Meine Uploads" section shows your not-yet-expired uploads; you can copy/open links anytime or remove entries from the local list.

## 4) Package the desktop frontend as .exe

Install PyInstaller if needed, then build:

```
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name DateiLink frontend_desktop.py
```

The .exe will be created under `dist/DateiLink.exe`.

Tip: If your API URL is fixed, you can hard-code it in `frontend_desktop.py` default input.

## 4a) Windows helpers: Start/Stop scripts

On Windows you can use these helper scripts:

- `./start-backend.ps1` to start the API (creates `uvicorn.pid` and `uvicorn.meta.json`)
- `./stop-backend.ps1` to stop it again

Examples (PowerShell):

```
./start-backend.ps1 -BindAddress 0.0.0.0 -BindPort 8000 -LogLevel info -Detach
# ... later
./stop-backend.ps1
```

# DateiLink (Self‑Hosted)

Kleines, selbst gehostetes File‑Sharing: Datei hochladen → Download‑Link teilen. Optionales Ablaufdatum mit automatischem Cleanup.

**Powered by Hirsch-Lorenz** - [hirsch-lorenz.de](https://hirsch-lorenz.de)

## Architektur
- Backend: FastAPI (nur API, keine Web‑UI)
- Desktop‑Frontend: Tkinter (als .exe buildbar), kommuniziert mit der API

## Voraussetzungen
- Windows mit PowerShell
- Python 3.10+ (empfohlen in virtuellem Environment)

## Installation (Windows PowerShell)
```
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Backend starten
Variante A – direkt mit Uvicorn (Konsole sichtbar):
```
uvicorn app:app --host 0.0.0.0 --port 8000
```

Variante B – per Script (Hintergrund, optional ohne Konsole):
```
./start-backend.ps1 -Detach
```
Optionen:
- `-NoConsole` startet ohne sichtbares Fenster (bevorzugt pythonw.exe)
- `-BindAddress 0.0.0.0` IP‑Bindung ändern
- `-BindPort 8000` Port ändern
- `-LogLevel info` Log‑Level
- `-LogFile backend.log` Logs in Datei schreiben (stdout/err getrennt)

Stoppen:
```
./stop-backend.ps1
```
Falls keine PID‑Datei vorhanden ist, kann über Port entdeckt/gestoppt werden:
```
./stop-backend.ps1 -Port 8000           # Ersten passenden Prozess stoppen
./stop-backend.ps1 -Port 8000 -All      # Alle passenden Prozesse stoppen
./stop-backend.ps1 -Port 8000 -DryRun   # Nur anzeigen, was gestoppt würde
```

Hinweise:
- Das Start‑Script legt `uvicorn.pid` und `uvicorn.meta.json` im Projektordner an.
- API‑Docs: http://127.0.0.1:8000/docs
- Ablage: Dateien unter `storage/`, Datenbank `files.db`, Konfiguration `config.json`.

## Desktop‑App (.exe) bauen
Mit PyInstaller:
```
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name DateiLink frontend_desktop.py
```
Die .exe liegt danach unter `dist/DateiLink.exe`.

Einstellungen (API‑URL, Ports, etc.) lassen sich in der App über den Button „Einstellungen“ setzen und werden persistent gespeichert.

## API Kurzreferenz
- `POST /api/upload`  (multipart: file, expires_in_days)
- `GET /d/{token}`    Datei herunterladen
- `GET /api/access-info`  Basis‑Infos zum aufrufenden Client
- `DELETE /api/purge-expired`  Abgelaufene Einträge löschen
- `GET /api/cleanup-status`    Cleanup‑Status anzeigen

## Konfiguration (Backend, Umgebungsvariablen)
- `BASE_URL`  Öffentliche Basis‑URL für generierte Links (optional)
- `DEFAULT_EXPIRE_DAYS`  Standard‑Ablaufzeit in Tagen (int)
- `MAX_EXPIRE_DAYS`  Maximale Ablaufzeit in Tagen (int)
- `CLEANUP_INTERVAL_HOURS`  Intervall für automatisches Cleanup (Stunden)
- `INTERNAL_NETWORKS`  Kommagetrennte CIDRs, die als „intern“ gelten
- `ALLOW_EXTERNAL_UPLOAD`  `true`, um Uploads von extern zu erlauben (nicht empfohlen)
- `UPLOAD_TOKEN` Geheimer Token; wenn gesetzt können externe Clients mit Header `X-ShareIt-Token: <TOKEN>` (oder Query `?token=`) hochladen obwohl IP extern ist
- `STORAGE_BACKEND` `local` (Standard) oder `s3`
- `S3_ENDPOINT`  (für MinIO, optional; Beispiel: `https://minio.example.local`)
- `S3_REGION`  (Standard `us-east-1`)
- `S3_BUCKET`  Bucket-Name (muss existieren oder wird versucht zu erzeugen)
- `S3_ACCESS_KEY`  Access Key
- `S3_SECRET_KEY`  Secret Key
- `S3_PRESIGN_EXPIRE_SECONDS` Gültigkeit einer generierten Presigned URL (Default 900)

### S3/MinIO Nutzung
Beispiel (PowerShell):
```
$env:STORAGE_BACKEND = "s3"
$env:S3_ENDPOINT = "https://minio.local"       # optional bei AWS S3 leer lassen
$env:S3_REGION = "eu-central-1"
$env:S3_BUCKET = "shareit-files"
$env:S3_ACCESS_KEY = "minioadmin"
$env:S3_SECRET_KEY = "minioadmin"
uvicorn app:app --host 0.0.0.0 --port 8000
```
Uploads werden dann im Bucket unter `shareit/<file_id>.<ext>` gespeichert. Downloads leiten per `307 Redirect` auf eine Presigned URL, externe Nutzer benötigen keinen direkten Zugriff auf dein internes Netzwerk.

### Externer Upload mit Token (empfohlen statt ALLOW_EXTERNAL_UPLOAD=true)
PowerShell Beispiel:
```
$env:UPLOAD_TOKEN = "SuperGeheimerToken123"  # Backend
uvicorn app:app --host 0.0.0.0 --port 8000
```
Client (curl):
```
curl -H "X-ShareIt-Token: SuperGeheimerToken123" -F "file=@test.txt" -F "expires_in_days=3" https://deine-url/api/upload
```

## Troubleshooting
- Port belegt? Anderen Port nutzen: `./start-backend.ps1 -BindPort 8001`
- Läuft der Dienst? Prüfen: `netstat -ano | findstr :8000`
- Stop findet keine PID? Discovery nutzen: `./stop-backend.ps1 -Port 8000`
- Keine Konsole gewünscht? `-NoConsole` verwenden; mit `-LogFile` Logs mitschreiben (stdout → .log, stderr → .log.err).


Stop-Process -Name DateiLink -ErrorAction SilentlyContinue; Remove-Item -Recurse -Force .\build, .\dist -ErrorAction SilentlyContinue; C:/Users/MAlbasha/Desktop/share-it/.venv/Scripts/python.exe -m PyInstaller --clean --noconfirm DateiLink.spec