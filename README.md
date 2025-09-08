# Share‑It (Self‑Hosted)

Eigenes, kleines File‑Sharing: Datei hochladen → URL bekommen → per E‑Mail teilen. Optionales Ablaufdatum mit **automatischem Cleanup**.

## Features

- ✅ Datei-Upload mit Drag & Drop
- ✅ Optionales Ablaufdatum (1-30 Tage)
- ✅ **Automatisches Löschen abgelaufener Dateien**
- ✅ **IP-basierte Zugriffskontrolle (VPN/LAN Support)**
- ✅ SQLite-Datenbank für Metadaten
- ✅ Responsive Web-Interface
- ✅ Token-basierte sichere URLs
- ✅ Cross-Platform (Windows/Linux/macOS)

## Sicherheit & Zugriffskontrolle

**Standard-Verhalten:**
- **Interne IPs (VPN/LAN)**: Upload + Download ✅
- **Externe IPs**: Nur Download ✅

**Standard interne Netzwerke:**
- `192.168.0.0/16` (Privates LAN)
- `10.0.0.0/8` (VPN/Private Networks)
- `172.16.0.0/12` (Docker/Private Networks)
- `127.0.0.1/32` (Localhost)

**Konfiguration:**
```bash
# Eigene interne Netzwerke definieren
INTERNAL_NETWORKS="192.168.1.0/24,10.0.0.0/8,172.20.0.0/16"

# Upload für alle erlauben (nicht empfohlen)
ALLOW_EXTERNAL_UPLOAD=true
```

## Automatisches Cleanup

Das System löscht abgelaufene Dateien automatisch:
- **Standard**: Cleanup alle 1 Stunde
- **Konfigurierbar** über Umgebungsvariable `CLEANUP_INTERVAL_HOURS`
- Läuft im Hintergrund während die App aktiv ist
- Löscht sowohl Datei als auch Datenbank-Eintrag

## Setup

```bash
python -m venv .venv
source .venv/bin/activate # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

## Umgebungsvariablen

```bash
BASE_URL=https://files.deine-domain.tld       # Optional: Basis-URL für Links
DEFAULT_EXPIRE_DAYS=7                         # Standard-Ablaufzeit in Tagen
MAX_EXPIRE_DAYS=30                            # Maximum Ablaufzeit in Tagen
CLEANUP_INTERVAL_HOURS=1                      # Cleanup-Intervall in Stunden

# Sicherheit
INTERNAL_NETWORKS="192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,127.0.0.1/32"
ALLOW_EXTERNAL_UPLOAD=false                   # Upload für externe IPs verbieten
```

## API Endpoints

- `GET /` - Web-Interface
- `POST /api/upload` - Datei hochladen (nur interne IPs)
- `GET /d/{token}` - Datei herunterladen (alle IPs)
- `GET /api/access-info` - Zugriffsinformationen der aktuellen IP
- `DELETE /api/purge-expired` - Manuelles Cleanup
- `GET /api/cleanup-status` - Cleanup-Status anzeigen

## Monitoring

Zugriffsinformationen prüfen:
```bash
curl http://localhost:8000/api/access-info
```

Cleanup-Status abfragen:
```bash
curl http://localhost:8000/api/cleanup-status
```

Manuelles Cleanup:
```bash
curl -X DELETE http://localhost:8000/api/purge-expired
```

## VPN/Reverse Proxy Setup

### VPN-Konfiguration

Wenn du einen VPN verwendest, stelle sicher, dass die echte Client-IP weitergegeben wird:

#### 1. Standard VPN-Netzwerke
Die App erkennt automatisch diese Standard-Netzwerke als "intern":
- `192.168.0.0/16` - Private LANs (Router-Standard)
- `10.0.0.0/8` - VPN & Private Networks (OpenVPN, WireGuard)
- `172.16.0.0/12` - Docker & Container Networks
- `127.0.0.1/32` - Localhost

#### 2. Eigene VPN-Netzwerke konfigurieren

**Für OpenVPN (10.8.0.0/24):**
```bash
INTERNAL_NETWORKS="10.8.0.0/24,192.168.1.0/24" python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

**Für WireGuard (10.10.0.0/24):**
```bash
INTERNAL_NETWORKS="10.10.0.0/24" python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

**Mehrere VPN-Netzwerke:**
```bash
export INTERNAL_NETWORKS="10.8.0.0/24,10.10.0.0/24,192.168.100.0/24"
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

#### 3. VPN-Server Konfiguration

**Deine VPN-IP herausfinden:**
```bash
# Über die App
curl http://deine-domain.com:8000/api/access-info

# Oder direkt
ip addr show tun0  # OpenVPN
ip addr show wg0   # WireGuard
```

**Beispiel-Antwort:**
```json
{
  "client_ip": "10.8.0.5",
  "is_internal": true,
  "can_upload": true,
  "can_download": true
}
```

### Reverse Proxy Setup

#### Nginx Konfiguration
```nginx
server {
    listen 80;
    server_name files.deine-domain.com;
    
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Für große Datei-Uploads
        client_max_body_size 1G;
        proxy_request_buffering off;
    }
}
```

#### Apache Konfiguration
```apache
<VirtualHost *:80>
    ServerName files.deine-domain.com
    
    ProxyPreserveHost On
    ProxyPass / http://localhost:8000/
    ProxyPassReverse / http://localhost:8000/
    
    # Real IP weitergeben
    ProxyAddHeaders On
    
    # Für große Uploads
    LimitRequestBody 1073741824  # 1GB
</VirtualHost>
```

#### Caddy Konfiguration
```caddyfile
files.deine-domain.com {
    reverse_proxy localhost:8000
    request_body {
        max_size 1GB
    }
}
```

### Docker Setup

#### Docker Compose
```yaml
version: '3.8'
services:
  wetransfer-light:
    build: .
    ports:
      - "8000:8000"
    environment:
      - BASE_URL=https://files.deine-domain.com
      - INTERNAL_NETWORKS=172.18.0.0/16,10.0.0.0/8,192.168.0.0/16
      - CLEANUP_INTERVAL_HOURS=2
    volumes:
      - ./storage:/app/storage
      - ./files.db:/app/files.db
    networks:
      - default

networks:
  default:
    driver: bridge
    ipam:
      config:
        - subnet: 172.18.0.0/16
```

### Troubleshooting

#### Problem: "Upload nicht verfügbar" obwohl im VPN
**Lösung:** IP-Bereich prüfen und anpassen
```bash
# 1. Aktuelle IP prüfen
curl http://localhost:8000/api/access-info

# 2. Netzwerk-Bereich anpassen
INTERNAL_NETWORKS="deine-vpn-ip/24" python -m uvicorn app:app
```

## Building the admin desktop EXE (Windows)

A helper script `build_admin_exe.ps1` is included to create a single-file EXE using PyInstaller.

Steps (PowerShell):

1. Create and activate a venv in the project root:
  .\.venv\Scripts\activate; python -m pip install -r requirements.txt

2. Run the build helper (uses the venv python):
  .\build_admin_exe.ps1

The built executable will be in `dist\admin_desktop`.

Notes and troubleshooting:
- If your app uses templates/static assets, ensure `templates/` and `static/` are present — the spec bundles them.
- Windows Explorer caches icons. If the tray icon or exe icon doesn't update after rebuilding, try restarting Explorer or log out/in.


#### Problem: Externe IPs werden als intern erkannt
**Lösung:** Netzwerk-Bereiche einschränken
```bash
# Nur spezifische VPN-Range
INTERNAL_NETWORKS="10.8.0.0/24" python -m uvicorn app:app
```

#### Problem: Reverse Proxy übergibt falsche IP
**Lösung:** Proxy-Headers prüfen
```bash
# Headers checken
curl -H "X-Forwarded-For: 1.2.3.4" http://localhost:8000/api/access-info
```

### Sicherheits-Tipps

1. **Nie ALLOW_EXTERNAL_UPLOAD=true in Produktion**
2. **Immer spezifische VPN-Ranges verwenden**
3. **Reverse Proxy mit HTTPS konfigurieren**
4. **Regelmäßige Cleanup-Intervalle setzen**

### Beispiel-Setups

#### Home-Lab mit WireGuard
```bash
# WireGuard VPN: 10.10.0.0/24
# Home LAN: 192.168.1.0/24
INTERNAL_NETWORKS="10.10.0.0/24,192.168.1.0/24"
BASE_URL="https://files.home.lab"
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

#### Büro mit OpenVPN
```bash
# OpenVPN: 10.8.0.0/24  
# Büro LAN: 192.168.100.0/24
INTERNAL_NETWORKS="10.8.0.0/24,192.168.100.0/24"
CLEANUP_INTERVAL_HOURS=1
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```



Remove-Item -Recurse -Force .venv
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt