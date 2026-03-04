/* ═══════════════════════════════════════════════════════════════════════
   app.js — Frontend para Music Downloader Web
   Maneja:  inicio de descarga → SSE en tiempo real → lista de archivos
   ═══════════════════════════════════════════════════════════════════════ */

let currentJobId = null;
let eventSource  = null;

// ── Elementos del DOM ──────────────────────────────────────────────────
const urlInput      = document.getElementById("urlInput");
const downloadBtn   = document.getElementById("downloadBtn");
const progressTrack = document.getElementById("progressTrack");
const logBox        = document.getElementById("logBox");
const filesSection  = document.getElementById("filesSection");
const filesList     = document.getElementById("filesList");
const zipBtn        = document.getElementById("zipBtn");

// Permitir Enter para descargar
urlInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") startDownload();
});


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

    try {
        const resp = await fetch("/api/download", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url }),
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
        } else if (text.includes("──") || text.includes("🔗") || text.includes("📋")) {
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
    } else {
        downloadBtn.disabled = false;
        downloadBtn.innerHTML = '<span class="btn__icon">⬇</span> D E S C A R G A R';
        progressTrack.classList.remove("active");
    }
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}
