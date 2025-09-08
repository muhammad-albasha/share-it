(function () {
  // Get DOM elements
  const fileInput = document.getElementById("fileInput");
  const fileName = document.getElementById("fileName");
  const form = document.getElementById("uploadForm");
  const status = document.getElementById("status");
  const progressWrap = document.getElementById("progressWrap");
  const result = document.getElementById("result");
  const progressBar = document.getElementById("progressBar");
  const link = document.getElementById("link");
  const copyBtn = document.getElementById("copyBtn");
  const expires = document.getElementById("expires");

  // Add event listeners for drag and drop
  const dropzone = document.querySelector('.dropzone');
  
  document.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("drag");
  });
  
  document.addEventListener("dragleave", (e) => {
    e.preventDefault();
    dropzone.classList.remove("drag");
  });

  document.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("drag");
    if (e.dataTransfer.files && e.dataTransfer.files.length) {
      fileInput.files = e.dataTransfer.files;
      fileName.textContent =
        e.dataTransfer.files[0].name +
        " (" +
        prettyBytes(e.dataTransfer.files[0].size) +
        ")";
    }
  });

  // Add click handler for dropzone
  dropzone.addEventListener("click", () => {
    fileInput.click();
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files && fileInput.files.length) {
      fileName.textContent =
        fileInput.files[0].name +
        " (" +
        prettyBytes(fileInput.files[0].size) +
        ")";
    }
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();

    // Prüfe ob Upload erlaubt ist
    const uploadControls = document.getElementById("uploadControls");
    if (!uploadControls || uploadControls.style.display === "none") {
      status.textContent = "Upload ist für externe Benutzer nicht verfügbar.";
      return;
    }

    if (!fileInput.files || !fileInput.files.length) {
      status.textContent = "Bitte eine Datei auswählen.";
      return;
    }

    const fd = new FormData();
    fd.append("file", fileInput.files[0]);
    fd.append("expires_in_days", expires.value || "7");

    progressWrap.classList.remove("hidden");
    result.classList.add("hidden");
    status.textContent = "Upload läuft…";
    progressBar.style.width = "0%";

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");

    xhr.upload.addEventListener("progress", (evt) => {
      if (evt.lengthComputable) {
        const pct = Math.round((evt.loaded / evt.total) * 100);
        progressBar.style.width = pct + "%";
      }
    });

    xhr.onload = function () {
      try {
        const data = JSON.parse(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300 && data.ok) {
          link.value = data.download_url;
          document.getElementById("expiresNote").textContent = data.expires_at
            ? `Läuft ab am ${new Date(data.expires_at).toLocaleString()}`
            : "Kein Ablaufdatum gesetzt.";
          result.classList.remove("hidden");
          status.textContent = "Fertig! Link kann kopiert werden.";
        } else {
          status.textContent =
            data && data.detail ? data.detail : "Fehler beim Upload.";
        }
      } catch (err) {
        status.textContent = "Unerwartete Antwort vom Server.";
      }
    };

    xhr.onerror = function () {
      status.textContent = "Netzwerkfehler beim Upload.";
    };

    xhr.send(fd);
  });

  copyBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(link.value);
      status.textContent = "Link kopiert.";
    } catch {
      link.select();
      document.execCommand("copy");
      status.textContent = "Link kopiert.";
    }
  });

  function prettyBytes(bytes) {
    if (bytes === 0) return "0 B";
    const k = 1024,
      dm = 1,
      sizes = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + " " + sizes[i];
  }
})();
