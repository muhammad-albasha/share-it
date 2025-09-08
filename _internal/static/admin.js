// Share-It Admin Interface JavaScript
console.log("🚀 Admin.js loading...");

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
  console.log("🔧 DOM ready, initializing admin interface...");
  initAdminInterface();
});

function initAdminInterface() {
  console.log("📋 Testing element availability...");
  
  // Test critical elements
  const elements = {
    networkForm: document.getElementById("networkForm"),
    appForm: document.getElementById("appForm"),
    refreshStatus: document.getElementById("refreshStatus")
  };
  
  console.log("📋 Elements found:", elements);
  
  // Setup form handlers
  setupFormHandlers();
  
  // Load initial data
  loadInitialData();
}

function setupFormHandlers() {
  console.log("📝 Setting up form handlers...");
  
  // Network form
  const networkForm = document.getElementById("networkForm");
  if (networkForm) {
    networkForm.addEventListener("submit", handleNetworkForm);
  }
  
  // App form  
  const appForm = document.getElementById("appForm");
  if (appForm) {
    appForm.addEventListener("submit", handleAppForm);
  }
  
  // Manual cleanup button
  const manualCleanupBtn = document.getElementById("manualCleanup");
  if (manualCleanupBtn) {
    manualCleanupBtn.addEventListener("click", handleManualCleanup);
  }
  
  // Purge all button
  const purgeAllBtn = document.getElementById("purgeAll");
  if (purgeAllBtn) {
    purgeAllBtn.addEventListener("click", handlePurgeAll);
  }
  
  // Update expiry button
  const updateExpiryBtn = document.getElementById("updateExpiry");
  if (updateExpiryBtn) {
    updateExpiryBtn.addEventListener("click", handleUpdateExpiry);
  }
  
  // Refresh status button
  const refreshStatusBtn = document.getElementById("refreshStatus");
  if (refreshStatusBtn) {
    refreshStatusBtn.addEventListener("click", handleRefreshStatus);
  }
  
  // Export config button
  const exportConfigBtn = document.getElementById("exportConfig");
  if (exportConfigBtn) {
    exportConfigBtn.addEventListener("click", handleExportConfig);
  }
}

async function handleNetworkForm(e) {
  e.preventDefault();
  console.log("📡 Network form submitted");
  
  const formData = new FormData(e.target);
  const networks = formData.get("internal_networks")
    .split("\n")
    .map(line => line.trim())
    .filter(line => line.length > 0);

  const config = {
    internal_networks: networks,
    allow_external_upload: formData.get("allow_external_upload") === "on"
  };

  await saveConfig("network", config);
}

async function handleAppForm(e) {
  e.preventDefault();
  console.log("📱 App form submitted");
  
  const formData = new FormData(e.target);
  const config = {
    base_url: formData.get("base_url") || "",
    default_expire_days: parseInt(formData.get("default_expire_days")) || 7,
    max_expire_days: parseInt(formData.get("max_expire_days")) || 30,
    cleanup_interval_hours: parseFloat(formData.get("cleanup_interval_hours")) || 1
  };

  await saveConfig("app", config);
}

async function handleManualCleanup() {
  console.log("🗑️ Manual cleanup requested");
  
  if (!confirm("Alle abgelaufenen Dateien jetzt löschen?")) return;

  const btn = document.getElementById("manualCleanup");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Lösche...";
  }

  try {
    console.log("🔄 Calling cleanup API...");
    const response = await fetch("/api/purge-expired", { method: "DELETE" });
    const result = await response.json();

    console.log("🔄 Cleanup result:", result);

    if (response.ok) {
      showMessage("✅ " + result.removed + " Dateien gelöscht", "success");
      
      // Zeige Debug-Informationen wenn verfügbar
      if (result.debug_info && result.debug_info.length > 0) {
        console.log("📊 Cleanup Debug-Info:", result.debug_info);
        
        // Kurze Zusammenfassung anzeigen
        const expiredFiles = result.debug_info.filter(f => f.is_expired).length;
        const totalFiles = result.debug_info.length;
        
        if (result.removed === 0 && expiredFiles === 0) {
          showMessage("ℹ️ Keine abgelaufenen Dateien gefunden", "info");
        } else if (result.removed === 0 && expiredFiles > 0) {
          showMessage("⚠️ " + expiredFiles + " abgelaufene Dateien gefunden, aber Löschung fehlgeschlagen", "warning");
        }
      }
      
      loadSystemStatus();
    } else {
      showMessage("Fehler: " + result.detail, "error");
    }
  } catch (error) {
    console.error("❌ Cleanup error:", error);
    showMessage("Fehler beim Cleanup: " + error.message, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Jetzt aufräumen";
    }
  }
}

async function handlePurgeAll() {
  console.log("💥 PURGE ALL requested");
  
  if (!confirm("⚠️ WARNUNG: Wirklich ALLE Dateien löschen?\n\nDies kann nicht rückgängig gemacht werden!")) return;
  if (!confirm("🚨 LETZTE WARNUNG: Alle Dateien werden unwiderruflich gelöscht!\n\nFortfahren?")) return;

  const btn = document.getElementById("purgeAll");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Lösche ALLE...";
  }

  try {
    console.log("💥 Calling PURGE ALL API...");
    const response = await fetch("/api/purge-all", { method: "DELETE" });
    const result = await response.json();

    console.log("💥 Purge ALL result:", result);

    if (response.ok && result.success) {
      showMessage(`💥 ALLE Dateien gelöscht! ${result.removed_count} Dateien entfernt.`, "success");
      loadSystemStatus(); // Refresh to show updated counts
    } else {
      showMessage("Fehler beim Löschen aller Dateien: " + (result.message || result.detail), "error");
    }
  } catch (error) {
    console.error("❌ Purge ALL error:", error);
    showMessage("Fehler beim Löschen aller Dateien: " + error.message, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Alle löschen";
    }
  }
}

async function handleUpdateExpiry() {
  console.log("🔄 Update expiry requested");
  
  if (!confirm("Ablaufzeiten aller Dateien basierend auf aktueller Konfiguration aktualisieren?")) return;

  const btn = document.getElementById("updateExpiry");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Aktualisiere...";
  }

  try {
    console.log("🔄 Calling update expiry API...");
    const response = await fetch("/api/update-expiry-based-on-config", { method: "POST" });
    const result = await response.json();

    console.log("🔄 Update expiry result:", result);

    if (response.ok && result.success) {
      showMessage(`✅ ${result.updated_count} Dateien aktualisiert (${result.current_expire_days} Tage)`, "success");
      loadSystemStatus(); // Refresh to show updated info
    } else {
      showMessage("Fehler beim Aktualisieren: " + (result.message || result.detail), "error");
    }
  } catch (error) {
    console.error("❌ Update expiry error:", error);
    showMessage("Fehler beim Aktualisieren: " + error.message, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Ablaufzeiten aktualisieren";
    }
  }
}

async function handleRefreshStatus() {
  console.log("🔄 Refresh status requested");
  
  const btn = document.getElementById("refreshStatus");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Lade...";
  }
  
  try {
    await loadSystemStatus();
    showMessage("Status aktualisiert", "info");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Status neu laden";
    }
  }
}

async function handleExportConfig() {
  console.log("📋 Export config requested");
  
  try {
    const response = await fetch("/admin/api/config/export");
    const config = await response.json();
    
    const blob = new Blob([JSON.stringify(config, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    
    const a = document.createElement("a");
    a.href = url;
    a.download = "share-it-config-" + new Date().toISOString().split('T')[0] + ".json";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    
    showMessage("Konfiguration exportiert", "success");
  } catch (error) {
    showMessage("Fehler beim Export", "error");
  }
}

function loadInitialData() {
  console.log("📊 Loading initial data...");
  loadSystemStatus();
  loadCurrentConfig();
  
  // Auto-refresh every 30 seconds
  setInterval(loadSystemStatus, 30000);
}

async function loadSystemStatus() {
  try {
    console.log("📊 Loading system status...");
    const [accessInfo, cleanupStatus] = await Promise.all([
      fetch("/api/access-info").then(r => r.json()),
      fetch("/api/cleanup-status").then(r => r.json())
    ]);

    console.log("Status data:", { accessInfo, cleanupStatus });

    // Update current IP
    const currentIpEl = document.getElementById("currentIp");
    if (currentIpEl && accessInfo.client_ip) {
      currentIpEl.textContent = accessInfo.client_ip;
    }

    // Update file counts
    const totalFilesEl = document.getElementById("totalFiles");
    const expiredFilesEl = document.getElementById("expiredFiles");
    const cleanupStatusEl = document.getElementById("cleanupStatus");

    if (totalFilesEl) totalFilesEl.textContent = cleanupStatus.total_files || 0;
    if (expiredFilesEl) expiredFilesEl.textContent = cleanupStatus.expired_files_pending || 0;
    if (cleanupStatusEl) cleanupStatusEl.textContent = cleanupStatus.cleanup_running ? "🟢 Aktiv" : "🔴 Gestoppt";

  } catch (error) {
    console.error("Error loading system status:", error);
    showMessage("Fehler beim Laden des System-Status", "error");
  }
}

async function loadCurrentConfig() {
  try {
    console.log("⚙️ Loading current config...");
    const response = await fetch("/admin/api/config");
    if (response.ok) {
      const config = await response.json();
      console.log("Config loaded:", config);
      populateConfigForms(config);
    }
  } catch (error) {
    console.error("Error loading config:", error);
  }
}

function populateConfigForms(config) {
  console.log("📝 Populating forms with config:", config);
  
  // Network form
  const internalNetworksEl = document.getElementById("internalNetworks");
  const allowExternalUploadEl = document.getElementById("allowExternalUpload");

  if (internalNetworksEl && config.internal_networks) {
    internalNetworksEl.value = config.internal_networks.join("\n");
  }
  if (allowExternalUploadEl) {
    allowExternalUploadEl.checked = config.allow_external_upload || false;
  }

  // App form
  const baseUrlEl = document.getElementById("baseUrl");
  const defaultExpireDaysEl = document.getElementById("defaultExpireDays");
  const maxExpireDaysEl = document.getElementById("maxExpireDays");
  const cleanupIntervalEl = document.getElementById("cleanupInterval");

  if (baseUrlEl) baseUrlEl.value = config.base_url || "";
  if (defaultExpireDaysEl) defaultExpireDaysEl.value = config.default_expire_days || 7;
  if (maxExpireDaysEl) maxExpireDaysEl.value = config.max_expire_days || 30;
  if (cleanupIntervalEl) cleanupIntervalEl.value = config.cleanup_interval_hours || 1;
}

async function saveConfig(type, config) {
  try {
    console.log("💾 Saving " + type + " config:", config);
    const response = await fetch("/admin/api/config/" + type, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(config)
    });

    if (response.ok) {
      const result = await response.json();
      showMessage((type === 'network' ? 'Netzwerk' : 'App') + "-Konfiguration gespeichert!", "success");
      
      if (result.restart_required) {
        showMessage("⚠️ Neustart erforderlich für vollständige Aktivierung", "warning");
      }
      
      // Reload status after config change
      setTimeout(loadSystemStatus, 1000);
    } else {
      const error = await response.json();
      showMessage("Fehler: " + (error.detail || "Unbekannter Fehler"), "error");
    }
  } catch (error) {
    console.error("Error saving config:", error);
    showMessage("Verbindungsfehler beim Speichern", "error");
  }
}

function showMessage(text, type) {
  type = type || "info";
  const messageEl = document.getElementById("statusMessage");
  const textEl = document.getElementById("statusText");
  
  if (!messageEl || !textEl) {
    console.log("Message:", text, type);
    return;
  }
  
  // Remove existing classes
  messageEl.className = "status-message";
  messageEl.classList.add(type);
  
  textEl.textContent = text;
  messageEl.classList.remove("hidden");
  
  // Auto hide after 5 seconds
  setTimeout(function() {
    messageEl.classList.add("hidden");
  }, 5000);
}

console.log("✅ Admin.js loaded successfully");
