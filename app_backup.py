import os
import sys
import sqlite3
import secrets
import mimetypes
import asyncio
import logging
import ipaddress
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any


from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


# =====================
# Konfiguration
# =====================
BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
DB_PATH = BASE_DIR / "files.db"
CONFIG_PATH = BASE_DIR / "config.json"

# BASE_URL: Public URL deiner App (ohne Slash am Ende). Für lokale Tests leer lassen.
BASE_URL = os.getenv("BASE_URL", "") # z.B. "https://files.dein-domain.tld"
DEFAULT_EXPIRE_DAYS = int(os.getenv("DEFAULT_EXPIRE_DAYS", "7"))
MAX_EXPIRE_DAYS = int(os.getenv("MAX_EXPIRE_DAYS", "30"))
CLEANUP_INTERVAL_HOURS = int(os.getenv("CLEANUP_INTERVAL_HOURS", "1"))  # Cleanup alle X Stunden

# IP-Zugriffskontrolle Konfiguration
INTERNAL_NETWORKS = os.getenv("INTERNAL_NETWORKS", "192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,127.0.0.1/32").split(",")
ALLOW_EXTERNAL_UPLOAD = os.getenv("ALLOW_EXTERNAL_UPLOAD", "false").lower() == "true"

STORAGE_DIR.mkdir(exist_ok=True)

# Logging konfigurieren
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =====================
# Konfigurationsverwaltung
# =====================

def load_config() -> Dict[str, Any]:
    """Lädt Konfiguration aus Datei oder gibt Defaults zurück"""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error loading config file: {e}")
    
    return get_default_config()


def get_default_config() -> Dict[str, Any]:
    """Gibt Standard-Konfiguration zurück"""
    return {
        "base_url": BASE_URL,
        "default_expire_days": DEFAULT_EXPIRE_DAYS,
        "max_expire_days": MAX_EXPIRE_DAYS,
        "cleanup_interval_hours": CLEANUP_INTERVAL_HOURS,
        "internal_networks": [net.strip() for net in INTERNAL_NETWORKS],
        "allow_external_upload": ALLOW_EXTERNAL_UPLOAD
    }


def save_config(config: Dict[str, Any]) -> bool:
    """Speichert Konfiguration in Datei"""
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info("Configuration saved successfully")
        return True
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        return False


def update_runtime_config(config: Dict[str, Any]):
    """Aktualisiert Runtime-Konfiguration (für sofortige Änderungen)"""
    global INTERNAL_NETWORKS, ALLOW_EXTERNAL_UPLOAD
    global BASE_URL, DEFAULT_EXPIRE_DAYS, MAX_EXPIRE_DAYS
    
    if "internal_networks" in config:
        INTERNAL_NETWORKS = config["internal_networks"]
    
    if "allow_external_upload" in config:
        ALLOW_EXTERNAL_UPLOAD = config["allow_external_upload"]
    
    if "base_url" in config:
        BASE_URL = config["base_url"]
    
    if "default_expire_days" in config:
        DEFAULT_EXPIRE_DAYS = config["default_expire_days"]
    
    if "max_expire_days" in config:
        MAX_EXPIRE_DAYS = config["max_expire_days"]


# Konfiguration beim Start laden
current_config = load_config()
update_runtime_config(current_config)


app = FastAPI(title="WeTransfer-Light")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Hintergrund-Task für automatisches Cleanup
cleanup_task = None

@app.on_event("startup")
async def startup_event():
    """Startet das automatische Cleanup beim App-Start"""
    global cleanup_task
    logger.info("Starting automatic cleanup service...")
    # Erstes Cleanup direkt beim Start
    cleanup_expired_files()
    # Dann periodisches Cleanup starten
    cleanup_task = asyncio.create_task(periodic_cleanup())

@app.on_event("shutdown")
async def shutdown_event():
    """Stoppt das automatische Cleanup beim App-Shutdown"""
    global cleanup_task
    if cleanup_task:
        logger.info("Stopping automatic cleanup service...")
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass

# =====================
# SQLite Setup
# =====================


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


with get_db() as conn:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS files (
        id TEXT PRIMARY KEY,
        token TEXT UNIQUE NOT NULL,
        orig_name TEXT NOT NULL,
        mime TEXT,
        size INTEGER NOT NULL,
        path TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT,
        one_time_download INTEGER DEFAULT 0
        );
    """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_token ON files(token);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_expires ON files(expires_at);")
    
    # Migration: Füge one_time_download Spalte hinzu, falls sie nicht existiert
    try:
        conn.execute("ALTER TABLE files ADD COLUMN one_time_download INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        # Spalte existiert bereits
        pass
    conn.commit()


# =====================
# Helpers
# =====================


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_expiry(days: int | None) -> str | None:
    if days is None or days <= 0:
        return None
    days = min(days, MAX_EXPIRE_DAYS)
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def public_download_url(token: str, request: Request) -> str:
# Bevorzugt BASE_URL, ansonsten Host aus Request
    if BASE_URL:
        return f"{BASE_URL}/d/{token}"
    base = str(request.base_url).rstrip("/")
    return f"{base}/d/{token}"


def get_client_ip(request: Request) -> str:
    """Ermittelt die echte Client-IP aus Request Headers (auch bei Reverse Proxy)"""
    # Prüfe verschiedene Headers für echte IP (bei Proxy/Load Balancer)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Nimm die erste IP aus der Liste (Original-Client)
        return forwarded_for.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    
    # Fallback auf direkte Client-IP
    return request.client.host if request.client else "127.0.0.1"


def is_internal_ip(ip_str: str) -> bool:
    """Prüft ob eine IP-Adresse zu den internen Netzwerken gehört"""
    try:
        client_ip = ipaddress.ip_address(ip_str)
        
        for network_str in INTERNAL_NETWORKS:
            try:
                network = ipaddress.ip_network(network_str.strip(), strict=False)
                if client_ip in network:
                    return True
            except ValueError:
                logger.warning(f"Invalid network configuration: {network_str}")
                continue
        
        return False
    except ValueError:
        logger.warning(f"Invalid IP address: {ip_str}")
        return False  # Bei ungültiger IP externe Behandlung


def check_upload_permission(request: Request) -> bool:
    """Prüft ob Upload für diese IP erlaubt ist"""
    if ALLOW_EXTERNAL_UPLOAD:
        return True  # Upload für alle erlaubt
    
    client_ip = get_client_ip(request)
    is_internal = is_internal_ip(client_ip)
    
    logger.info(f"Upload request from IP: {client_ip}, internal: {is_internal}")
    
    return is_internal


def get_access_info(request: Request) -> dict:
    """Gibt Zugriffsinformationen für Frontend zurück"""
    client_ip = get_client_ip(request)
    is_internal = is_internal_ip(client_ip)
    
    return {
        "client_ip": client_ip,
        "is_internal": is_internal,
        "can_upload": is_internal or ALLOW_EXTERNAL_UPLOAD,
        "can_download": True  # Download ist immer erlaubt
    }


async def delete_one_time_file(token: str, file_path: str, orig_name: str):
    """Löscht eine One-Time-Download Datei nach dem Download (Background Task)"""
    # Kurz warten, um sicherzustellen, dass der Download abgeschlossen ist
    await asyncio.sleep(2)
    
    try:
        logger.info(f"🔥 Starting delayed deletion of one-time download: {orig_name}")
        
        # 1. Datei vom Dateisystem löschen
        file_path_obj = Path(file_path)
        if file_path_obj.exists():
            file_path_obj.unlink()
            logger.info(f"✅ Successfully deleted file from storage: {orig_name}")
        else:
            logger.warning(f"⚠️ File not found on disk: {file_path_obj}")
        
        # 2. Eintrag aus Datenbank löschen
        with get_db() as conn:
            conn.execute("DELETE FROM files WHERE token = ?", (token,))
            conn.commit()
        logger.info(f"✅ Successfully deleted database entry: {orig_name}")
        
    except Exception as delete_error:
        logger.error(f"❌ Error during delayed deletion of {orig_name}: {delete_error}")
        # Fallback: Markiere als abgelaufen für späteren Cleanup
        try:
            with get_db() as conn:
                now_iso = datetime.now(timezone.utc).isoformat()
                conn.execute("UPDATE files SET expires_at = ? WHERE token = ?", (now_iso, token))
                conn.commit()
            logger.info(f"⏰ Fallback: File marked as expired for cleanup: {orig_name}")
        except Exception as fallback_error:
            logger.error(f"❌ Even fallback failed for {orig_name}: {fallback_error}")


def cleanup_expired_files():
    """Löscht abgelaufene Dateien aus Datenbank und Dateisystem"""
    now = datetime.now(timezone.utc)
    removed_count = 0
    
    try:
        with get_db() as conn:
            # Alle Dateien finden (mit und ohne Ablaufzeit)
            rows = conn.execute(
                "SELECT token, path, expires_at, orig_name FROM files"
            ).fetchall()
            
            logger.info(f"Found {len(rows)} total files in database")
            
            for row in rows:
                try:
                    should_delete = False
                    reason = ""
                    
                    if row["expires_at"] is not None:
                        # Datei hat Ablaufzeit - prüfe ob abgelaufen
                        expires_dt = datetime.fromisoformat(row["expires_at"])
                        logger.info(f"Checking file {row['orig_name']}: expires {expires_dt}, now {now}")
                        
                        if now > expires_dt:
                            should_delete = True
                            reason = f"expired at {expires_dt}"
                    else:
                        # Datei hat keine Ablaufzeit - prüfe Alter anhand der Datei-Modifikationszeit
                        file_path = Path(row["path"])
                        if file_path.exists():
                            file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
                            # Verwende aktuelle DEFAULT_EXPIRE_DAYS Konfiguration
                            age_limit = now - timedelta(days=DEFAULT_EXPIRE_DAYS)
                            logger.info(f"File {row['orig_name']} without expiry: created {file_mtime}, age limit {age_limit} (current config: {DEFAULT_EXPIRE_DAYS} days)")
                            if file_mtime < age_limit:
                                should_delete = True
                                reason = f"no expiry date and older than {DEFAULT_EXPIRE_DAYS} days (created {file_mtime})"
                        else:
                            # Datei existiert nicht im Dateisystem - lösche DB-Eintrag
                            should_delete = True
                            reason = "file missing from filesystem"
                    
                    # ZUSÄTZLICHE PRÜFUNG: Wenn DEFAULT_EXPIRE_DAYS = 0, lösche alle Dateien sofort
                    if DEFAULT_EXPIRE_DAYS == 0 and row["expires_at"] is not None:
                        logger.info(f"🚨 IMMEDIATE DELETION MODE: DEFAULT_EXPIRE_DAYS = 0, deleting {row['orig_name']} immediately")
                        should_delete = True
                        reason = f"immediate deletion (config set to 0 days)"
                    
                    if should_delete:
                        logger.info(f"🗑️ Deleting file {row['orig_name']}: {reason}")
                        
                        # Datei vom Dateisystem löschen
                        file_path = Path(row["path"])
                        logger.info(f"📁 File path to delete: {file_path}")
                        logger.info(f"📂 File exists check: {file_path.exists()}")
                        
                        if file_path.exists():
                            try:
                                file_path.unlink()
                                logger.info(f"✅ Successfully deleted file from storage: {row['orig_name']}")
                            except PermissionError as pe:
                                logger.error(f"❌ Permission denied deleting file {file_path}: {pe}")
                                raise  # Re-raise to skip DB deletion if file deletion fails
                            except Exception as fe:
                                logger.error(f"❌ Error deleting file {file_path}: {fe}")
                                raise  # Re-raise to skip DB deletion if file deletion fails
                        else:
                            logger.warning(f"⚠️ File not found on disk (already deleted?): {file_path}")
                        
                        # Eintrag aus Datenbank löschen (nur wenn Datei erfolgreich gelöscht wurde)
                        logger.info(f"🗄️ Deleting database entry for token: {row['token']}")
                        conn.execute("DELETE FROM files WHERE token = ?", (row["token"],))
                        removed_count += 1
                        logger.info(f"✅ Removed database entry for: {row['orig_name']}")
                    else:
                        logger.info(f"⏳ File {row['orig_name']} is not ready for deletion yet")
                        
                except (ValueError, OSError, PermissionError) as e:
                    # Bei korrupten Daten oder Dateisystem-Fehlern: Fehler protokollieren
                    logger.error(f"❌ Error processing file {row['token']} ({row['orig_name']}): {e}")
                    logger.error(f"🚨 File will NOT be deleted from database due to error")
                    # NICHT aus DB entfernen, wenn File-Deletion fehlschlägt
                    continue
                except Exception as e:
                    # Unerwartete Fehler
                    logger.error(f"🚨 Unexpected error processing file {row['token']}: {e}")
                    continue
            
            # Nur committen, wenn alles erfolgreich war
            conn.commit()
            logger.info(f"💾 Database transaction committed successfully")
            
    except Exception as e:
        logger.error(f"🚨 Critical error during cleanup: {e}")
        raise
    
    logger.info(f"🧹 Cleanup completed: {removed_count} files removed")
    return removed_count


async def periodic_cleanup():
    """Führt periodisch das Cleanup durch"""
    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL_HOURS * 3600)  # Warten in Sekunden
            cleanup_expired_files()
        except Exception as e:
            logger.error(f"Error in periodic cleanup: {e}")
            await asyncio.sleep(60)  # Bei Fehler nur 1 Minute warten

# =====================
# Routes
# =====================


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    access_info = get_access_info(request)
    context = {
        "request": request, 
        "max_expire": MAX_EXPIRE_DAYS, 
        "default_expire": DEFAULT_EXPIRE_DAYS,
        "access_info": access_info
    }
    return templates.TemplateResponse("index.html", context)


@app.post("/api/upload")
async def upload(request: Request, file: UploadFile = File(...), expires_in_days: int = Form(DEFAULT_EXPIRE_DAYS)):
    # Zugriffskontrolle: Upload nur für interne IPs (außer ALLOW_EXTERNAL_UPLOAD=true)
    if not check_upload_permission(request):
        client_ip = get_client_ip(request)
        logger.warning(f"Upload denied for external IP: {client_ip}")
        raise HTTPException(
            status_code=403, 
            detail="Upload nur für interne Benutzer erlaubt. Download ist weiterhin möglich."
        )
    
    if not file:
        raise HTTPException(status_code=400, detail="Keine Datei erhalten.")

    # Begrenze expires_in_days auf [0..MAX]
    try:
        expires_in_days = int(expires_in_days)
    except Exception:
        expires_in_days = DEFAULT_EXPIRE_DAYS


    if expires_in_days < 0:
        expires_in_days = 0
    if expires_in_days > MAX_EXPIRE_DAYS:
        expires_in_days = MAX_EXPIRE_DAYS

    # Generiere IDs & Pfade
    file_id = secrets.token_hex(16)
    token = secrets.token_urlsafe(32)

 # Bestimme sichere Endung per mimetype – optional
    orig_name = file.filename or "upload.bin"
    mime = file.content_type or mimetypes.guess_type(orig_name)[0] or "application/octet-stream"


# Wir speichern unter der internen ID, nicht unter dem Originalnamen
    safe_suffix = Path(orig_name).suffix # kann leer sein
    disk_path = STORAGE_DIR / f"{file_id}{safe_suffix}"


# Stream auf Platte schreiben
    size = 0
    with disk_path.open("wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            f.write(chunk)

    created = utcnow_iso()
    expires_at = compute_expiry(expires_in_days)
    
    # Markiere One-Time-Downloads (wenn expires_in_days = 0)
    one_time_download = 1 if expires_in_days == 0 else 0
    
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO files(id, token, orig_name, mime, size, path, created_at, expires_at, one_time_download)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (file_id, token, orig_name, mime, size, str(disk_path), created, expires_at, one_time_download),
            )
    conn.commit()


    return JSONResponse(
        {
        "ok": True,
        "download_url": public_download_url(token, request),
        "token": token,
        "expires_at": expires_at,
        "filename": orig_name,
        "size": size,
        }
    )

@app.get("/d/{token}")
async def download(token: str, background_tasks: BackgroundTasks):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM files WHERE token = ?", (token,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Link nicht gefunden.")


    # Ablauf prüfen
    expires_at = row["expires_at"]
    if expires_at:
        try:
            expires_dt = datetime.fromisoformat(expires_at)
            if datetime.now(timezone.utc) > expires_dt:
                # Optional: Datei löschen, um Speicher freizugeben
                try:
                    Path(row["path"]).unlink(missing_ok=True)
                except Exception:
                    pass
                with get_db() as conn:
                    conn.execute("DELETE FROM files WHERE token = ?", (token,))
                    conn.commit()
                raise HTTPException(status_code=410, detail="Link abgelaufen.")
        except ValueError:
            pass
    path = Path(row["path"])
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Datei nicht mehr vorhanden.")
    
    # Prüfe, ob es sich um eine One-Time-Download Datei handelt
    try:
        should_delete_after_download = bool(row["one_time_download"])
    except (KeyError, IndexError):
        # Fallback für alte Datenbank-Einträge ohne one_time_download Spalte
        should_delete_after_download = False
    
    if should_delete_after_download:
        logger.info(f"🔥 One-time download detected for {row['orig_name']} (one_time_download flag set)")
    
    # Datei streamen – als Attachment mit Originalnamen
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{row['orig_name']}"}
    
    try:
        # Bei One-Time-Downloads: Background Task für verzögerte Löschung planen
        if should_delete_after_download:
            logger.info(f"🗑️ One-time download: Will delete {row['orig_name']} after download completes")
            background_tasks.add_task(
                delete_one_time_file, 
                token, 
                row["path"], 
                row["orig_name"]
            )
        
        # FileResponse zurückgeben - die Löschung passiert im Hintergrund nach dem Download
        return FileResponse(
            path,
            media_type=row["mime"] or "application/octet-stream",
            filename=row["orig_name"],
            headers=headers,
        )
        
        # SOFORTIGE LÖSCHUNG bei One-Time-Downloads (nach Response)
        if should_delete_after_download:
            try:
                logger.info(f"� Immediately deleting one-time download: {row['orig_name']}")
                
                # 1. Datei vom Dateisystem löschen
                file_path = Path(row["path"])
                if file_path.exists():
                    file_path.unlink()
                    logger.info(f"✅ Successfully deleted file from storage: {row['orig_name']}")
                else:
                    logger.warning(f"⚠️ File not found on disk: {file_path}")
                
                # 2. Eintrag aus Datenbank löschen
                with get_db() as conn:
                    conn.execute("DELETE FROM files WHERE token = ?", (token,))
                    conn.commit()
                logger.info(f"✅ Successfully deleted database entry: {row['orig_name']}")
                
            except Exception as delete_error:
                logger.error(f"❌ Error during immediate deletion of {row['orig_name']}: {delete_error}")
                # Fallback: Markiere als abgelaufen für späteren Cleanup
                try:
                    with get_db() as conn:
                        now_iso = datetime.now(timezone.utc).isoformat()
                        conn.execute("UPDATE files SET expires_at = ? WHERE token = ?", (now_iso, token))
                        conn.commit()
                    logger.info(f"⏰ Fallback: File marked as expired for cleanup: {row['orig_name']}")
                except Exception as fallback_error:
                    logger.error(f"❌ Even fallback failed for {row['orig_name']}: {fallback_error}")
        
        return response
        
    except Exception as e:
        logger.error(f"❌ Error during file download: {e}")
        raise HTTPException(status_code=500, detail="Fehler beim Download")

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    """Admin-Konfigurationsseite"""
    # Nur interne IPs haben Zugriff auf Admin-Bereich
    if not is_internal_ip(get_client_ip(request)):
        raise HTTPException(status_code=403, detail="Admin-Zugriff nur für interne IPs")
    
    access_info = get_access_info(request)
    config = load_config()
    
    context = {
        "request": request,
        "access_info": access_info,
        "config": config
    }
    return templates.TemplateResponse("admin.html", context)


@app.get("/admin/api/config")
async def get_config(request: Request):
    """Aktuelle Konfiguration abrufen"""
    if not is_internal_ip(get_client_ip(request)):
        raise HTTPException(status_code=403, detail="Admin-Zugriff nur für interne IPs")
    
    return load_config()


@app.post("/admin/api/config/network")
async def update_network_config(request: Request):
    """Netzwerk-Konfiguration aktualisieren"""
    if not is_internal_ip(get_client_ip(request)):
        raise HTTPException(status_code=403, detail="Admin-Zugriff nur für interne IPs")
    
    try:
        config_update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Ungültige JSON-Daten")
    
    current_config = load_config()
    
    # Validiere interne Netzwerke
    if "internal_networks" in config_update:
        networks = config_update["internal_networks"]
        for network_str in networks:
            try:
                ipaddress.ip_network(network_str.strip(), strict=False)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Ungültiges Netzwerk-Format: {network_str}")
        
        current_config["internal_networks"] = networks
    
    if "allow_external_upload" in config_update:
        current_config["allow_external_upload"] = config_update["allow_external_upload"]
    
    # Speichern und Runtime aktualisieren
    if save_config(current_config):
        update_runtime_config(current_config)
        logger.info(f"Network config updated by {get_client_ip(request)}")
        return {"ok": True, "message": "Netzwerk-Konfiguration gespeichert", "restart_required": False}
    else:
        raise HTTPException(status_code=500, detail="Fehler beim Speichern der Konfiguration")


@app.post("/admin/api/config/app")
async def update_app_config(request: Request):
    """App-Konfiguration aktualisieren"""
    if not is_internal_ip(get_client_ip(request)):
        raise HTTPException(status_code=403, detail="Admin-Zugriff nur für interne IPs")
    
    try:
        config_update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Ungültige JSON-Daten")
    
    current_config = load_config()
    
    # Validiere und aktualisiere App-Einstellungen
    if "base_url" in config_update:
        current_config["base_url"] = config_update["base_url"].strip()
    
    if "default_expire_days" in config_update:
        days = config_update["default_expire_days"]
        if not isinstance(days, int) or days < 1 or days > 365:
            raise HTTPException(status_code=400, detail="Standard-Ablaufzeit muss zwischen 1 und 365 Tagen liegen")
        current_config["default_expire_days"] = days
    
    if "max_expire_days" in config_update:
        days = config_update["max_expire_days"]
        if not isinstance(days, int) or days < 1 or days > 365:
            raise HTTPException(status_code=400, detail="Maximum-Ablaufzeit muss zwischen 1 und 365 Tagen liegen")
        current_config["max_expire_days"] = days
    
    if "cleanup_interval_hours" in config_update:
        hours = config_update["cleanup_interval_hours"]
        if not isinstance(hours, (int, float)) or hours < 0.1 or hours > 168:
            raise HTTPException(status_code=400, detail="Cleanup-Intervall muss zwischen 0.1 und 168 Stunden liegen")
        current_config["cleanup_interval_hours"] = hours
    
    # Prüfe logische Konsistenz
    if current_config["default_expire_days"] > current_config["max_expire_days"]:
        raise HTTPException(status_code=400, detail="Standard-Ablaufzeit kann nicht größer als Maximum sein")
    
    # Speichern und Runtime aktualisieren
    if save_config(current_config):
        update_runtime_config(current_config)
        logger.info(f"App config updated by {get_client_ip(request)}")
        return {"ok": True, "message": "App-Konfiguration gespeichert", "restart_required": True}
    else:
        raise HTTPException(status_code=500, detail="Fehler beim Speichern der Konfiguration")


@app.get("/admin/api/config/export")
async def export_config(request: Request):
    """Konfiguration exportieren"""
    if not is_internal_ip(get_client_ip(request)):
        raise HTTPException(status_code=403, detail="Admin-Zugriff nur für interne IPs")
    
    config = load_config()
    config["exported_at"] = datetime.now(timezone.utc).isoformat()
    config["exported_by"] = get_client_ip(request)
    
    return config


@app.get("/admin/api/system-info")
async def get_system_info(request: Request):
    """System-Informationen abrufen"""
    if not is_internal_ip(get_client_ip(request)):
        raise HTTPException(status_code=403, detail="Admin-Zugriff nur für interne IPs")
    
    # Dateistatistiken
    with get_db() as conn:
        total_files = conn.execute("SELECT COUNT(*) as count FROM files").fetchone()["count"]
        
        total_size = conn.execute("SELECT SUM(size) as size FROM files").fetchone()["size"] or 0
        
        expired_count = 0
        rows = conn.execute("SELECT expires_at FROM files WHERE expires_at IS NOT NULL").fetchall()
        now = datetime.now(timezone.utc)
        for row in rows:
            try:
                if datetime.fromisoformat(row["expires_at"]) < now:
                    expired_count += 1
            except ValueError:
                expired_count += 1
    
    return {
        "system": {
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "platform": os.name,
            "storage_path": str(STORAGE_DIR.absolute()),
            "config_path": str(CONFIG_PATH.absolute()),
            "database_path": str(DB_PATH.absolute())
        },
        "files": {
            "total_count": total_files,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "expired_count": expired_count
        },
        "config": load_config(),
        "runtime": {
            "current_internal_networks": INTERNAL_NETWORKS,
            "allow_external_upload": ALLOW_EXTERNAL_UPLOAD,
            "cleanup_running": cleanup_task is not None and not cleanup_task.done() if 'cleanup_task' in globals() else False
        },
        "client": {
            "ip": get_client_ip(request),
            "is_internal": is_internal_ip(get_client_ip(request)),
            "user_agent": request.headers.get("user-agent", "Unknown")
        }
    }


@app.get("/api/access-info")
async def access_info(request: Request):
    """Gibt Zugriffsinformationen für die aktuelle IP zurück"""
    return get_access_info(request)

@app.get("/admin/api/debug-files")
async def debug_files(request: Request):
    """Debug-Endpoint um alle Dateien in der Datenbank zu sehen"""
    access_info = get_access_info(request)
    if not access_info["is_internal"]:
        raise HTTPException(status_code=403, detail="Nur für interne IPs verfügbar")
    
    try:
        now = datetime.now(timezone.utc)
        files_info = []
        
        with get_db() as conn:
            rows = conn.execute(
                "SELECT token, orig_name, expires_at, path, size FROM files"
            ).fetchall()
            
            for row in rows:
                file_info = {
                    "token": row["token"][:10] + "...",
                    "name": row["orig_name"],
                    "path": row["path"],
                    "size": row["size"],
                    "expires_at": row["expires_at"],
                    "file_exists": Path(row["path"]).exists() if row["path"] else False
                }
                
                if row["expires_at"]:
                    try:
                        expires_dt = datetime.fromisoformat(row["expires_at"])
                        file_info["is_expired"] = now > expires_dt
                        file_info["expires_in_hours"] = round((expires_dt - now).total_seconds() / 3600, 2)
                    except ValueError:
                        file_info["is_expired"] = True
                        file_info["expires_in_hours"] = "invalid_date"
                else:
                    file_info["is_expired"] = False
                    file_info["expires_in_hours"] = "never"
                
                files_info.append(file_info)
        
        return {
            "ok": True,
            "current_time": now.isoformat(),
            "total_files": len(files_info),
            "files": files_info
        }
        
    except Exception as e:
        logger.error(f"Error in debug_files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/api/create-test-expired-file")
async def create_test_expired_file(request: Request):
    """Erstellt eine Test-Datei die bereits abgelaufen ist (nur für Debugging)"""
    access_info = get_access_info(request)
    if not access_info["is_internal"]:
        raise HTTPException(status_code=403, detail="Nur für interne IPs verfügbar")
    
    try:
        # Erstelle eine Test-Datei
        test_content = b"Test file for cleanup testing"
        test_filename = "test_expired_file.txt"
        
        # Generiere Token und Pfad
        token = secrets.token_urlsafe(32)
        file_path = STORAGE_DIR / f"{token}.txt"
        
        # Speichere die Datei
        with open(file_path, "wb") as f:
            f.write(test_content)
        
        # Erstelle DB-Eintrag mit Ablaufzeit in der Vergangenheit
        expires_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        
        with get_db() as conn:
            conn.execute(
                "INSERT INTO files (token, orig_name, path, size, expires_at) VALUES (?, ?, ?, ?, ?)",
                (token, test_filename, str(file_path), len(test_content), expires_at)
            )
            conn.commit()
        
        logger.info(f"Created test expired file: {test_filename} with token {token}")
        
        return {
            "ok": True,
            "message": "Test-Datei erstellt",
            "token": token,
            "filename": test_filename,
            "expires_at": expires_at,
            "path": str(file_path)
        }
        
    except Exception as e:
        logger.error(f"Error creating test expired file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/purge-expired")
async def purge_expired():
    """Manuelles Aufräumen - löscht alle abgelaufenen und verwaisten Dateien"""
    logger.info("Manual cleanup requested via API")
    
    initial_count = 0
    try:
        with get_db() as conn:
            initial_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        
        # Cleanup ausführen
        cleanup_expired_files()
        
        # Anzahl nach Cleanup prüfen
        final_count = 0
        with get_db() as conn:
            final_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        
        removed = initial_count - final_count
        
        return {
            "success": True,
            "message": f"Cleanup abgeschlossen. {removed} Dateien entfernt.",
            "removed_count": removed,
            "remaining_count": final_count
        }
        
    except Exception as e:
        logger.error(f"Error during manual cleanup: {e}")
        return {
            "success": False,
            "message": f"Fehler beim Aufräumen: {str(e)}"
        }


@app.delete("/api/purge-all")
async def purge_all():
    """Löscht ALLE Dateien (für Admin-Zwecke) - VORSICHT!"""
    logger.info("Manual PURGE ALL requested via API")
    
    initial_count = 0
    try:
        with get_db() as conn:
            initial_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        
        # Alle Dateien aus DB und Storage löschen
        removed_count = 0
        
        with get_db() as conn:
            rows = conn.execute(
                "SELECT token, path, orig_name FROM files"
            ).fetchall()
            
            logger.info(f"🗑️ PURGE ALL: Found {len(rows)} files to delete")
            
            for row in rows:
                try:
                    logger.info(f"🗑️ Deleting file {row['orig_name']}")
                    
                    # Datei vom Dateisystem löschen
                    file_path = Path(row["path"])
                    logger.info(f"📁 File path to delete: {file_path}")
                    
                    if file_path.exists():
                        file_path.unlink()
                        logger.info(f"✅ Successfully deleted file from storage: {row['orig_name']}")
                    else:
                        logger.warning(f"⚠️ File not found on disk: {file_path}")
                    
                    # Eintrag aus Datenbank löschen
                    conn.execute("DELETE FROM files WHERE token = ?", (row["token"],))
                    removed_count += 1
                    logger.info(f"✅ Removed database entry for: {row['orig_name']}")
                    
                except Exception as e:
                    logger.error(f"❌ Error deleting file {row['orig_name']}: {e}")
                    continue
            
            conn.commit()
            logger.info(f"💾 Database transaction committed successfully")
        
        final_count = 0
        with get_db() as conn:
            final_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        
        return {
            "success": True,
            "message": f"ALLE Dateien gelöscht! {removed_count} Dateien entfernt.",
            "removed_count": removed_count,
            "remaining_count": final_count
        }
        
    except Exception as e:
        logger.error(f"Error during PURGE ALL: {e}")
        return {
            "success": False,
            "message": f"Fehler beim Löschen aller Dateien: {str(e)}"
        }


@app.post("/api/update-expiry-based-on-config")
async def update_expiry_based_on_config():
    """Aktualisiert alle Ablaufzeiten basierend auf der aktuellen Konfiguration"""
    logger.info(f"🔄 Updating expiry dates based on current config (DEFAULT_EXPIRE_DAYS: {DEFAULT_EXPIRE_DAYS})")
    
    try:
        updated_count = 0
        now = datetime.now(timezone.utc)
        
        with get_db() as conn:
            rows = conn.execute(
                "SELECT token, orig_name, created_at, expires_at FROM files"
            ).fetchall()
            
            logger.info(f"Found {len(rows)} files to potentially update")
            
            for row in rows:
                try:
                    # Berechne neue Ablaufzeit basierend auf created_at + DEFAULT_EXPIRE_DAYS
                    if row["created_at"]:
                        created_dt = datetime.fromisoformat(row["created_at"])
                        new_expires_at = created_dt + timedelta(days=DEFAULT_EXPIRE_DAYS)
                        
                        logger.info(f"File {row['orig_name']}: created {created_dt}, new expiry {new_expires_at} (config: {DEFAULT_EXPIRE_DAYS} days)")
                        
                        # Aktualisiere Ablaufzeit in DB
                        conn.execute(
                            "UPDATE files SET expires_at = ? WHERE token = ?",
                            (new_expires_at.isoformat(), row["token"])
                        )
                        updated_count += 1
                        
                except Exception as e:
                    logger.error(f"Error updating file {row['orig_name']}: {e}")
                    continue
            
            conn.commit()
            logger.info(f"💾 Updated {updated_count} files with new expiry dates")
        
        return {
            "success": True,
            "message": f"Ablaufzeiten aktualisiert! {updated_count} Dateien basierend auf aktueller Konfiguration ({DEFAULT_EXPIRE_DAYS} Tage) angepasst.",
            "updated_count": updated_count,
            "current_expire_days": DEFAULT_EXPIRE_DAYS
        }
        
    except Exception as e:
        logger.error(f"Error updating expiry dates: {e}")
        return {
            "success": False,
            "message": f"Fehler beim Aktualisieren der Ablaufzeiten: {str(e)}"
        }


@app.get("/api/cleanup-status")
async def cleanup_status():
    """Status des automatischen Cleanup-Systems"""
    global cleanup_task
    is_running = cleanup_task is not None and not cleanup_task.done()
    
    # Statistiken über abgelaufene Dateien
    now = datetime.now(timezone.utc)
    with get_db() as conn:
        total_files = conn.execute("SELECT COUNT(*) as count FROM files").fetchone()["count"]
        expired_files = 0
        
        rows = conn.execute("SELECT expires_at FROM files WHERE expires_at IS NOT NULL").fetchall()
        for row in rows:
            try:
                if datetime.fromisoformat(row["expires_at"]) < now:
                    expired_files += 1
            except ValueError:
                expired_files += 1  # Korrupte Daten als abgelaufen betrachten
    
    return {
        "cleanup_running": is_running,
        "cleanup_interval_hours": CLEANUP_INTERVAL_HOURS,
        "total_files": total_files,
        "expired_files_pending": expired_files
    }