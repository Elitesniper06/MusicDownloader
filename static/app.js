/* ═══════════════════════════════════════════════════════════════════════
   app.js — Frontend para Music Downloader Web
   Maneja:  inicio de descarga → SSE en tiempo real → lista de archivos
            parar descarga, subir cookies, carpeta destino
   ═══════════════════════════════════════════════════════════════════════ */

let currentJobId = null;
let eventSource  = null;

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
const cookiesFileInput = document.getElementById("cookiesFileInput");
const cookiesStatus    = document.getElementById("cookiesStatus");
const deleteCookiesBtn = document.getElementById("deleteCookiesBtn");

// Permitir Enter para descargar
urlInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") startDownload();
});

// Listener para subir cookies al seleccionar archivo
cookiesFileInput.addEventListener("change", uploadCookies);

// Comprobar estado de cookies al cargar
checkCookiesStatus();


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
    const dest = destInput.value.trim();
    if (dest) body.dest_folder = dest;

    try {
        const resp = await fetch("/api/download", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            addLog(`❌  Error: ${err.error || resp.statusText}`, "error");
            setLoading(false);
            return;
        }

        const data = await resp.json();
        currentJobId = data.job_id;

        // Conectar al stream SSE
        connectSSE(currentJobId);

    } catch (e) {
        addLog(`❌  Error de conexión: ${e.message}`, "error");
        setLoading(false);
    }
}


// ═══════════════════════════════════════════════════════════════════════
// DETENER DESCARGA
// ═══════════════════════════════════════════════════════════════════════

async function stopDownload() {
    if (!currentJobId) return;

    try {
        await fetch(`/api/stop/${currentJobId}`, { method: "POST" });
        addLog("⛔ Solicitando parada…", "accent");
        stopBtn.disabled = true;
    } catch (e) {
        addLog(`❌ Error al intentar parar: ${e.message}`, "error");
    }
}


// ═══════════════════════════════════════════════════════════════════════
// COOKIES — SUBIR / ELIMINAR / COMPROBAR
// ═══════════════════════════════════════════════════════════════════════

async function uploadCookies() {
    const file = cookiesFileInput.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);

    try {
        const resp = await fetch("/api/upload-cookies", { method: "POST", body: formData });
        const data = await resp.json();

        if (resp.ok) {
            setCookiesUI(true);
            addLog("🍪 Cookies subidas correctamente.", "accent");
        } else {
            addLog(`❌ Error subiendo cookies: ${data.error}`, "error");
        }
    } catch (e) {
        addLog(`❌ Error de conexión: ${e.message}`, "error");
    }

    // Limpiar input para poder volver a subir el mismo archivo
    cookiesFileInput.value = "";
}

async function deleteCookies() {
    try {
        await fetch("/api/delete-cookies", { method: "POST" });
        setCookiesUI(false);
        addLog("🗑️ Cookies eliminadas.", "dim");
    } catch (e) {
        addLog(`❌ Error: ${e.message}`, "error");
    }
}

async function checkCookiesStatus() {
    try {
        const resp = await fetch("/api/cookies-status");
        const data = await resp.json();
        setCookiesUI(data.has_cookies);
    } catch (e) {
        // Silenciar — no es crítico
    }
}

function setCookiesUI(hasCookies) {
    if (hasCookies) {
        cookiesStatus.textContent = "✅ Cookies cargadas";
        cookiesStatus.classList.add("active");
        deleteCookiesBtn.style.display = "inline-flex";
    } else {
        cookiesStatus.textContent = "Sin cookies";
        cookiesStatus.classList.remove("active");
        deleteCookiesBtn.style.display = "none";
    }
}


// ═══════════════════════════════════════════════════════════════════════
// SSE — RECIBIR LOG EN TIEMPO REAL
// ═══════════════════════════════════════════════════════════════════════

function connectSSE(jobId) {
    if (eventSource) eventSource.close();

    eventSource = new EventSource(`/api/stream/${jobId}`);

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

        // Mostrar archivos disponibles
        loadFiles(jobId);
    });

    eventSource.onerror = () => {
        // SSE se reconecta automáticamente, pero si el job ya terminó
        // simplemente cerramos
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
        const resp = await fetch(`/api/files/${jobId}`);
        if (!resp.ok) return;

        const data = await resp.json();
        if (!data.files || data.files.length === 0) return;

        filesList.innerHTML = "";

        data.files.forEach((f) => {
            const item = document.createElement("div");
            item.className = "file-item";
            item.innerHTML = `
                <div class="file-item__info">
                    <span class="file-item__name">${escapeHtml(f.name)}</span>
                    <span class="file-item__size">${f.size_mb} MB</span>
                </div>
                <a class="file-item__dl"
                   href="/api/download-file/${jobId}/${encodeURIComponent(f.name)}"
                   download>
                   ⬇ Descargar
                </a>
            `;
            filesList.appendChild(item);
        });

        // Botón ZIP si hay más de 1 archivo
        if (data.files.length > 1) {
            zipBtn.style.display = "block";
        } else {
            zipBtn.style.display = "none";
        }

        filesSection.style.display = "block";

    } catch (e) {
        console.error("Error cargando archivos:", e);
    }
}

function downloadZip() {
    if (currentJobId) {
        window.location.href = `/api/download-zip/${currentJobId}`;
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
