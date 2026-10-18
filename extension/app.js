/**
 * YT Premiere Importer - Stage 4 UXP Controller
 * Connects the Premiere Pro panel UI to the local FastAPI downloader (127.0.0.1:8000),
 * polls real-time download progress, and automatically imports completed media into Premiere Pro.
 */

const SERVER_BASE_URL = "http://127.0.0.1:8000";

// -------------------------------------------------------------
// 1. UXP Entrypoint Registration
// -------------------------------------------------------------
try {
  const { entrypoints } = require("uxp");

  entrypoints.setup({
    panels: {
      mainPanel: {
        show(event) {
          console.log("[YT Importer] Panel shown in Premiere Pro.");
        },
        hide(event) {
          console.log("[YT Importer] Panel hidden.");
        }
      }
    }
  });

  console.log("[YT Importer] UXP Entrypoint registered successfully.");
} catch (err) {
  console.log("[YT Importer] Notice: Running outside UXP host context or entrypoints already set.");
}

// -------------------------------------------------------------
// 2. DOM Elements & State
// -------------------------------------------------------------
let urlInput = null;
let qualitySelect = null;
let saveLocationInput = null;
let browseBtn = null;
let downloadBtn = null;
let statusState = null;
let statusMessage = null;
let statusDot = null;

let currentPollTimer = null;

// -------------------------------------------------------------
// 3. Status Management Helper
// -------------------------------------------------------------
function updateStatus(stateText, messageText, type = "ready") {
  if (statusState) statusState.textContent = stateText;
  if (statusMessage) statusMessage.textContent = messageText;

  if (statusDot) {
    statusDot.className = "status-dot";
    switch (type) {
      case "checking":
        statusDot.classList.add("status-dot-checking");
        break;
      case "downloading":
        statusDot.classList.add("status-dot-downloading");
        break;
      case "completed":
      case "download-ready":
        statusDot.classList.add("status-dot-completed");
        break;
      case "error":
        statusDot.classList.add("status-dot-error");
        break;
      case "ready":
      default:
        statusDot.classList.add("status-dot-ready");
        break;
    }
  }
}

function setButtonDisabled(disabled) {
  if (downloadBtn) {
    downloadBtn.disabled = disabled;
  }
}

function stopPolling() {
  if (currentPollTimer) {
    clearTimeout(currentPollTimer);
    currentPollTimer = null;
  }
}

// -------------------------------------------------------------
// 4. URL Validation Logic
// -------------------------------------------------------------
function validateYouTubeUrl(inputUrl) {
  if (!inputUrl || !inputUrl.trim()) {
    return {
      isValid: false,
      state: "Error",
      message: "Please enter a YouTube URL."
    };
  }

  const trimmed = inputUrl.trim();
  const ytRegex = /^(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?(?:.*&)?v=|shorts\/|embed\/|v\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})(?:[?&].*)?$/i;

  if (ytRegex.test(trimmed)) {
    return {
      isValid: true,
      state: "Ready to download",
      message: "Ready to download."
    };
  } else {
    return {
      isValid: false,
      state: "Error",
      message: "Please enter a valid YouTube URL."
    };
  }
}

// -------------------------------------------------------------
// 5. Premiere Pro Media Import (Official UXP DOM API)
// -------------------------------------------------------------
async function importFileToPremiere(filePath, fileName) {
  try {
    let ppro = null;
    try {
      ppro = require("premierepro");
    } catch (requireErr) {
      console.warn("[YT Importer] premierepro module not found in this runtime context:", requireErr);
    }

    if (!ppro || !ppro.Project) {
      console.warn("[YT Importer] Premiere Pro DOM API is not active in this context.");
      return {
        success: true,
        imported: false,
        note: "Downloaded to disk. Note: Premiere Pro DOM API not found in preview context."
      };
    }

    // 1. Get the active project
    const project = await ppro.Project.getActiveProject();
    if (!project) {
      return {
        success: true,
        imported: false,
        note: "Downloaded to disk, but no active Premiere project is currently open."
      };
    }

    // 2. Retrieve root bin (or target bin)
    let rootItem = null;
    try {
      if (typeof project.getRootItem === "function") {
        rootItem = await project.getRootItem();
      }
    } catch (rootErr) {
      console.warn("[YT Importer] Could not retrieve project root item:", rootErr);
    }

    // 3. Import media file into Project
    let importSuccess = false;
    if (typeof project.importFiles === "function") {
      if (rootItem) {
        importSuccess = await project.importFiles([filePath], true, rootItem);
      } else {
        importSuccess = await project.importFiles([filePath]);
      }
    } else if (typeof ppro.importFiles === "function") {
      importSuccess = await ppro.importFiles(project, [filePath]);
    }

    return {
      success: true,
      imported: !!importSuccess,
      note: importSuccess ? null : "project.importFiles returned false"
    };

  } catch (err) {
    console.error("[YT Importer] Import exception:", err);
    return {
      success: false,
      error: err.message || String(err)
    };
  }
}

// -------------------------------------------------------------
// 6. Polling Download Progress from FastAPI Backend
// -------------------------------------------------------------
async function pollJobStatus(jobId, fallbackName = "") {
  try {
    const res = await fetch(`${SERVER_BASE_URL}/status/${jobId}`);
    if (!res.ok) {
      throw new Error(`HTTP ${res.status} checking job status`);
    }

    const data = await res.json();
    const jobStatus = data.status;
    const progress = data.progress !== undefined ? data.progress : 0;
    const filename = data.filename || fallbackName || "video";
    const filePath = data.path;

    if (jobStatus === "queued") {
      updateStatus("Queued", "Download queued in downloader...", "checking");
      currentPollTimer = setTimeout(() => pollJobStatus(jobId, filename), 500);
    } else if (jobStatus === "downloading") {
      updateStatus("Downloading...", `Downloading... ${progress}%`, "downloading");
      currentPollTimer = setTimeout(() => pollJobStatus(jobId, filename), 500);
    } else if (jobStatus === "completed") {
      stopPolling();

      // Download completed -> Begin automatic Premiere Pro Import
      updateStatus("Importing...", `Download finished. Importing ${filename} into Premiere Pro...`, "checking");

      const importResult = await importFileToPremiere(filePath, filename);

      if (importResult.success) {
        if (importResult.imported) {
          updateStatus("Complete", `✓ Imported into Project: ${filename}`, "completed");
          console.log(`[YT Importer] Successfully imported ${filePath} into Premiere Pro.`);
        } else {
          updateStatus("Complete", `✓ Downloaded: ${filename} (${importResult.note || "Saved to disk"})`, "completed");
        }
      } else {
        updateStatus("Import Warning", `Downloaded to disk, but Premiere import failed: ${importResult.error}`, "error");
      }

      setButtonDisabled(false);
    } else if (jobStatus === "error") {
      stopPolling();
      updateStatus("Error", data.error || data.message || "Download failed.", "error");
      setButtonDisabled(false);
    } else {
      // Continue polling for unexpected intermediate status
      currentPollTimer = setTimeout(() => pollJobStatus(jobId, filename), 500);
    }

  } catch (err) {
    console.warn("[YT Importer] Status polling retry:", err.message);
    // Retry polling after short delay
    currentPollTimer = setTimeout(() => pollJobStatus(jobId, fallbackName), 1000);
  }
}

// -------------------------------------------------------------
// 7. Action Button Click Handler (Download & Import Workflow)
// -------------------------------------------------------------
async function handleDownloadClick() {
  const currentUrl = urlInput ? urlInput.value.trim() : "";
  const qualityVal = qualitySelect ? qualitySelect.value : "1080";
  const saveLocationVal = saveLocationInput ? saveLocationInput.value.trim() : "D:\\YT-Premiere-Downloads";

  // 1. Local validation
  const validation = validateYouTubeUrl(currentUrl);
  if (!validation.isValid) {
    updateStatus(validation.state, validation.message, "error");
    return;
  }

  // 2. Disable action button and clean up any ongoing poll
  setButtonDisabled(true);
  stopPolling();

  // 3. Initiate request to local backend
  updateStatus("Checking URL...", "Connecting to local downloader...", "checking");

  try {
    const response = await fetch(`${SERVER_BASE_URL}/download`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        url: currentUrl,
        quality: qualityVal,
        output_dir: saveLocationVal,
        async_mode: true
      })
    });

    if (!response.ok) {
      throw new Error(`Server returned HTTP ${response.status}`);
    }

    const data = await response.json();

    if (!data.success) {
      updateStatus("Error", data.error || "Download rejected by service.", "error");
      setButtonDisabled(false);
      return;
    }

    const jobId = data.job_id;
    if (!jobId) {
      updateStatus("Complete", data.message || "Download finished.", "completed");
      setButtonDisabled(false);
      return;
    }

    // 4. Begin polling progress
    updateStatus("Queued", "Download job queued...", "checking");
    pollJobStatus(jobId);

  } catch (err) {
    console.error("[YT Importer] Connection error:", err);
    updateStatus(
      "Error",
      `Cannot connect to downloader at ${SERVER_BASE_URL}. Ensure server.py is running.`,
      "error"
    );
    setButtonDisabled(false);
  }
}

// -------------------------------------------------------------
// 8. Browse Folder Handler (UXP FileSystem API)
// -------------------------------------------------------------
async function handleBrowseClick() {
  try {
    const uxp = require("uxp");
    if (uxp && uxp.storage && uxp.storage.localFileSystem) {
      const folder = await uxp.storage.localFileSystem.getFolder();
      if (folder && folder.nativePath) {
        saveLocationInput.value = folder.nativePath;
        updateStatus("Ready", `Save folder selected: ${folder.nativePath}`, "ready");
        console.log("[YT Importer] Destination folder changed:", folder.nativePath);
      }
    }
  } catch (err) {
    if (err && err.message && err.message.toLowerCase().includes("cancel")) {
      console.log("[YT Importer] Folder picker cancelled.");
    } else {
      console.warn("[YT Importer] Folder selection exception:", err);
      updateStatus("Error", "Could not open folder picker.", "error");
    }
  }
}

// -------------------------------------------------------------
// 9. Initialization & Event Binding
// -------------------------------------------------------------
function initApp() {
  urlInput = document.getElementById("url-input");
  qualitySelect = document.getElementById("quality-select");
  saveLocationInput = document.getElementById("save-location-input");
  browseBtn = document.getElementById("browse-btn");
  downloadBtn = document.getElementById("download-btn");
  statusState = document.getElementById("status-state");
  statusMessage = document.getElementById("status-message");
  statusDot = document.getElementById("status-dot");

  if (downloadBtn) {
    downloadBtn.addEventListener("click", handleDownloadClick);
  }

  if (browseBtn) {
    browseBtn.addEventListener("click", handleBrowseClick);
  }

  if (urlInput) {
    urlInput.addEventListener("input", () => {
      const text = urlInput.value.trim();
      if (!text && statusState && statusState.textContent === "Error") {
        updateStatus("Ready", "Waiting for URL input...", "ready");
      }
    });

    urlInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !downloadBtn.disabled) {
        handleDownloadClick();
      }
    });
  }

  if (qualitySelect) {
    qualitySelect.value = "1080";
    qualitySelect.addEventListener("change", () => {
      console.log(`[YT Importer] Target quality set to: ${qualitySelect.value}`);
    });
  }

  // Initial UI state
  updateStatus("Ready", "Waiting for URL input...", "ready");
  console.log("[YT Importer] Stage 4 UXP Controller initialized.");
}

// Initialize when DOM content is loaded
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initApp);
} else {
  initApp();
}
