/* ═══════════════════════════════════════════════════════════════════════
   app.js — Frontend para Music Downloader Web
   
   ✅ Carpeta: File System Access API (showDirectoryPicker)
      → Abre el explorador de archivos NATIVO del PC del usuario
      → Funciona en Chrome, Edge, Brave (tanto local como Render)
      → Los archivos se guardan DIRECTAMENTE en la carpeta elegida
   
   ✅ Cookies: 100% automáticas — zero esfuerzo del usuario
      → En LOCAL: se leen del navegador Chrome automáticamente
      → En RENDER: extractor_args con clientes alternativos de YouTube
   ═══════════════════════════════════════════════════════════════════════ */

let currentJobId      = null;
let eventSource       = null;
let isLocal           = false;     // se detecta al cargar
let selectedDirHandle = null;      // FileSystemDirectoryHandle (File System Access API)

// ── Elementos del DOM ──────────────────────────────────────────────────
const urlInput         = document.getElementById("urlInput");
const destInput        = document.getElementById("destInput");
const downloadBtn      = document.getElementById("downloadBtn");
const stopBtn          = document.getElementById("stopBtn");
const progressTrack    = document.getElementById("progressTrack");
const logBox           = document.getElementById("logBox");
const filesSection     = document.getElementById("filesSection");
const filesList        = document.getElementById("filesList");
const zipBtn           = document.getElementById("zipBtn");
const browseFolderBtn  = document.getElementById("browseFolderBtn");
const folderStatus     = document.getElementById("folderStatus");
const clearFolderBtn   = document.getElementById("clearFolderBtn");
const folderSection    = document.getElementById("folderSection");
const folderApiWarning = document.getElementById("folderApiWarning");

// Permitir Enter para descargar
urlInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") startDownload();
});


// ═══════════════════════════════════════════════════════════════════════
// DETECCIÓN DE ENTORNO + FILE SYSTEM ACCESS API
// ═══════════════════════════════════════════════════════════════════════

async function detectEnvironment() {
    try {
        const resp = await fetch("/api/environment");
        const data = await resp.json();
        isLocal = data.is_local;
    } catch (e) {
        isLocal = false;
    }

    // Comprobar soporte de File System Access API
    const hasFileSystemAPI = ("showDirectoryPicker" in window);

    if (!hasFileSystemAPI && !isLocal) {
        // Ni File System API ni local → ocultar botón, mostrar aviso
        browseFolderBtn.style.display = "none";
        folderApiWarning.style.display = "block";
        folderStatus.textContent = "Los archivos se descargarán al navegador";
    } else if (!hasFileSystemAPI && isLocal) {
        // Sin File System API pero en local → usar endpoint del servidor (tkinter)
        // browseFolder() llamará a /api/browse-folder como fallback
    }
    // Si tiene File System API → browseFolder() usará showDirectoryPicker
}

// Ejecutar al cargar la página
detectEnvironment();


// ═══════════════════════════════════════════════════════════════════════
// SELECTOR DE CARPETA — File System Access API
// ═══════════════════════════════════════════════════════════════════════

async function browseFolder() {
    const hasFileSystemAPI = ("showDirectoryPicker" in window);

    if (hasFileSystemAPI) {
        // ── MÉTODO PRINCIPAL: File System Access API ──
        // Abre el explorador de archivos NATIVO del PC del usuario
        // Funciona en Chrome/Edge/Brave, tanto en local como desde Render
        browseFolderBtn.disabled = true;
        browseFolderBtn.textContent = "📁 Abriendo explorador…";

        try {
            const dirHandle = await window.showDirectoryPicker({
                mode: "readwrite",
            });

            // Guardar el handle para usarlo al descargar archivos
            selectedDirHandle = dirHandle;
            destInput.value = "__browser_fs__";  // Marcador interno

            folderStatus.textContent = "✅ " + dirHandle.name;
            folderStatus.className = "folder-status active";
            clearFolderBtn.style.display = "inline-flex";

            addLog("📂 Carpeta seleccionada: " + dirHandle.name, "accent");

        } catch (err) {
            // El usuario canceló el diálogo — no es un error
            if (err.name !== "AbortError") {
                addLog("❌ Error seleccionando carpeta: " + err.message, "error");
            }
        }

        browseFolderBtn.disabled = false;
        browseFolderBtn.textContent = "📁 Seleccionar Carpeta / Pendrive";

    } else if (isLocal) {
        // ── FALLBACK LOCAL: tkinter en el servidor ──
        browseFolderBtn.disabled = true;
        browseFolderBtn.textContent = "📁 Abriendo explorador…";

        try {
            const resp = await fetch("/api/browse-folder", { method: "POST" });
            const data = await resp.json();

            if (data.folder) {
                destInput.value = data.folder;
                folderStatus.textContent = "✅ " + data.folder;
                folderStatus.className = "folder-status active";
                clearFolderBtn.style.display = "inline-flex";
            }
        } catch (e) {
            addLog("❌ Error abriendo explorador: " + e.message, "error");
        }

        browseFolderBtn.disabled = false;
        browseFolderBtn.textContent = "📁 Seleccionar Carpeta / Pendrive";

    } else {
        addLog("⚠️ Tu navegador no soporta selección de carpetas.", "dim");
    }
}

function clearFolder() {
    destInput.value = "";
    selectedDirHandle = null;
    folderStatus.textContent = "⚠ Ninguna carpeta seleccionada — se descargarán al navegador";
    folderStatus.className = "folder-status";
    clearFolderBtn.style.display = "none";
}


// ═══════════════════════════════════════════════════════════════════════
// GUARDAR ARCHIVOS EN CARPETA SELECCIONADA (File System Access API)
// ═══════════════════════════════════════════════════════════════════════

/**
 * Descarga todos los archivos del job y los guarda directamente
 * en la carpeta que el usuario seleccionó con showDirectoryPicker().
 */
async function saveFilesToFolder(jobId, files) {
    if (!selectedDirHandle || files.length === 0) return false;

    let saved = 0;

    for (const f of files) {
        try {
            addLog("💾 Guardando: " + f.name + "…", "accent");

            // Descargar el archivo desde el servidor
            const resp = await fetch("/api/download-file/" + jobId + "/" + encodeURIComponent(f.name));
            if (!resp.ok) {
                addLog("❌ Error descargando " + f.name + " del servidor", "error");
                continue;
            }
            const blob = await resp.blob();

            // Escribir directamente en la carpeta del usuario
            const fileHandle = await selectedDirHandle.getFileHandle(f.name, { create: true });
            const writable = await fileHandle.createWritable();
            await writable.write(blob);
            await writable.close();

            saved++;
            addLog("✅ Guardado: " + f.name + " (" + f.size_mb + " MB)", "accent");

        } catch (err) {
            addLog("❌ Error guardando " + f.name + ": " + err.message, "error");
        }
    }

    if (saved > 0) {
        addLog("\n📂 " + saved + " archivo(s) guardado(s) en: " + selectedDirHandle.name, "accent");
    }

    return saved > 0;
}


// ═══════════════════════════════════════════════════════════════════════
// INICIAR DESCARGA
// ═══════════════════════════════════════════════════════════════════════

async function startDownload() {
    const url = urlInput.value.trim();
    if (!url) {
        addLog("⚠️  Pega una URL antes de descargar.", "dim");
        return;
    }

    // Limpiar estado anterior
    clearLog();
    hideFiles();
    setLoading(true);

    const body = { url };

    // Carpeta destino: solo enviar si es servidor local con ruta real del sistema
    // (no si es File System Access API — eso se maneja en el navegador)
    const dest = destInput.value.trim();
    if (isLocal && dest && dest !== "__browser_fs__") {
        body.dest_folder = dest;
    }

    // Cookies: 100% automáticas — no se envía nada desde el frontend
    // En LOCAL: web_app.py usa cookies_from_browser="chrome" automáticamente
    // En RENDER: extractor_args en downloader.py evita detección de bots

    try {
        const resp = await fetch("/api/download", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            addLog("❌  Error: " + (err.error || resp.statusText), "error");
            setLoading(false);
            return;
        }

        const data = await resp.json();
        currentJobId = data.job_id;

        // Conectar al stream SSE
        connectSSE(currentJobId);

    } catch (e) {
        addLog("❌  Error de conexión: " + e.message, "error");
        setLoading(false);
    }
}


// ═══════════════════════════════════════════════════════════════════════
// DETENER DESCARGA
// ═══════════════════════════════════════════════════════════════════════

async function stopDownload() {
    if (!currentJobId) return;

    try {
        await fetch("/api/stop/" + currentJobId, { method: "POST" });
        addLog("⛔ Solicitando parada…", "accent");
        stopBtn.disabled = true;
    } catch (e) {
        addLog("❌ Error al intentar parar: " + e.message, "error");
    }
}


// ═══════════════════════════════════════════════════════════════════════
// SSE — RECIBIR LOG EN TIEMPO REAL
// ═══════════════════════════════════════════════════════════════════════

function connectSSE(jobId) {
    if (eventSource) eventSource.close();

    eventSource = new EventSource("/api/stream/" + jobId);

    eventSource.onmessage = (e) => {
        const text = e.data.replace(/\\n/g, "\n");
        // Detectar tipo de línea para colorear
        if (text.includes("❌") || text.includes("Error")) {
            addLog(text, "error");
        } else if (text.includes("──") || text.includes("🔗") || text.includes("📋") || text.includes("⛔")) {
            addLog(text, "accent");
        } else {
            addLog(text);
        }
    };

    eventSource.addEventListener("done", (e) => {
        eventSource.close();
        eventSource = null;
        setLoading(false);

        // Mostrar archivos disponibles (y auto-guardar si hay carpeta seleccionada)
        loadFiles(jobId);
    });

    eventSource.onerror = () => {
        setTimeout(() => {
            if (eventSource && eventSource.readyState === EventSource.CLOSED) {
                setLoading(false);
                loadFiles(jobId);
            }
        }, 2000);
    };
}


// ═══════════════════════════════════════════════════════════════════════
// CARGAR Y MOSTRAR ARCHIVOS DESCARGADOS
// ═══════════════════════════════════════════════════════════════════════

async function loadFiles(jobId) {
    try {
        const resp = await fetch("/api/files/" + jobId);
        if (!resp.ok) return;

        const data = await resp.json();
        if (!data.files || data.files.length === 0) return;

        // ── Si hay carpeta seleccionada con File System Access API ──
        // Guardar archivos directamente en la carpeta del usuario
        if (selectedDirHandle) {
            const saved = await saveFilesToFolder(jobId, data.files);
            if (saved) {
                // Mostrar resumen (ya guardados, no necesitan links)
                filesSection.style.display = "block";
                filesList.innerHTML = "";

                data.files.forEach((f) => {
                    const item = document.createElement("div");
                    item.className = "file-item";
                    item.innerHTML =
                        '<div class="file-item__info">' +
                            '<span class="file-item__name">' + escapeHtml(f.name) + '</span>' +
                            '<span class="file-item__size">' + f.size_mb + ' MB</span>' +
                        '</div>' +
                        '<span class="file-item__saved">✅ Guardado</span>';
                    filesList.appendChild(item);
                });

                zipBtn.style.display = "none"; // No necesario
                return;
            }
            // Si falló, mostrar links normales como fallback
        }

        // ── Fallback: mostrar links de descarga normales ──
        filesList.innerHTML = "";

        data.files.forEach((f) => {
            const item = document.createElement("div");
            item.className = "file-item";
            item.innerHTML =
                '<div class="file-item__info">' +
                    '<span class="file-item__name">' + escapeHtml(f.name) + '</span>' +
                    '<span class="file-item__size">' + f.size_mb + ' MB</span>' +
                '</div>' +
                '<a class="file-item__dl" href="/api/download-file/' + jobId + '/' + encodeURIComponent(f.name) + '" download>' +
                    '⬇ Descargar' +
                '</a>';
            filesList.appendChild(item);
        });

        // Botón ZIP si hay más de 1 archivo
        zipBtn.style.display = data.files.length > 1 ? "block" : "none";
        filesSection.style.display = "block";

    } catch (e) {
        console.error("Error cargando archivos:", e);
    }
}

function downloadZip() {
    if (currentJobId) {
        window.location.href = "/api/download-zip/" + currentJobId;
    }
}


// ═══════════════════════════════════════════════════════════════════════
// HELPERS DE UI
// ═══════════════════════════════════════════════════════════════════════

function addLog(text, type) {
    const line = document.createElement("span");
    line.className = "log-line";
    if (type === "error")  line.classList.add("log-line--error");
    if (type === "dim")    line.classList.add("log-line--dim");
    if (type === "accent") line.classList.add("log-line--accent");
    line.textContent = text;
    logBox.appendChild(line);

    // Auto-scroll al final
    logBox.scrollTop = logBox.scrollHeight;
}

function clearLog() {
    logBox.innerHTML = "";
}

function hideFiles() {
    filesSection.style.display = "none";
    filesList.innerHTML = "";
    zipBtn.style.display = "none";
}

function setLoading(loading) {
    if (loading) {
        downloadBtn.disabled = true;
        downloadBtn.innerHTML = '<span class="btn__icon">⏳</span> D E S C A R G A N D O …';
        progressTrack.classList.add("active");
        stopBtn.style.display = "inline-flex";
        stopBtn.disabled = false;
    } else {
        downloadBtn.disabled = false;
        downloadBtn.innerHTML = '<span class="btn__icon">⬇</span> D E S C A R G A R';
        progressTrack.classList.remove("active");
        stopBtn.style.display = "none";
    }
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}
