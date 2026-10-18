# YT Premiere Importer - Local Downloader Service

A lightweight, local FastAPI service running `yt-dlp` to download authorized video media and return the local file path to the Premiere Pro UXP extension panel.

---

## Legal & Compliance Notice

This downloader is designed and intended strictly for videos and content that the user is authorized to download and use (e.g. personal footage, open-access/Creative Commons media, or licensed assets). It does not contain or support DRM circumvention, paywall bypasses, or authentication workarounds.

---

## File Overview

* **`server.py`**: FastAPI application running strictly on `127.0.0.1:8000`. Exposes `/health`, `/download`, and `/status/{job_id}` endpoints with local CORS support.
* **`downloader.py`**: Safe wrapper around `yt-dlp`'s Python API with format mapping, non-overwriting destination controls, and in-memory progress tracking.
* **`config.py`**: Defines server host, port, supported resolution presets, and default output directory.
* **`requirements.txt`**: Pinned Python dependencies (`fastapi`, `uvicorn`, `yt-dlp`, `pydantic`).

---

## Setup & Execution

### 1. Virtual Environment
The virtual environment is created locally inside `downloader\.venv`:

```bash
# Windows Command Prompt / PowerShell:
cd "D:\pr extension\YT-Premiere-Importer\downloader"
python -m venv .venv
```

To activate the environment:
```bash
# In CMD:
.venv\Scripts\activate.bat

# In PowerShell:
.venv\Scripts\Activate.ps1
```

### 2. Installing Requirements
```bash
.venv\Scripts\pip install -r requirements.txt
```

### 3. Starting the Server
Run the server bound strictly to localhost (`127.0.0.1:8000`):

```bash
# From downloader folder:
.venv\Scripts\python server.py

# Or via uvicorn directly:
.venv\Scripts\uvicorn server:app --host 127.0.0.1 --port 8000
```

### 4. Stopping the Server
Press `Ctrl + C` in the terminal where the server is running.

---

## API Endpoints

### 1. Health Check
* **Method**: `GET`
* **URL**: `http://127.0.0.1:8000/health`
* **Response**:
```json
{
  "status": "ok"
}
```

### 2. Download Media
* **Method**: `POST`
* **URL**: `http://127.0.0.1:8000/download`
* **Headers**: `Content-Type: application/json`
* **Body**:
```json
{
  "url": "https://www.youtube.com/watch?v=YOUR_VIDEO_ID",
  "quality": "1080",
  "output_dir": "D:\\YT-Premiere-Downloads",
  "async_mode": false
}
```
* **Success Response**:
```json
{
  "success": true,
  "job_id": "a1b2c3d4",
  "title": "Example Video Title",
  "filename": "Example Video Title.mp4",
  "path": "D:\\YT-Premiere-Downloads\\Example Video Title.mp4",
  "message": "Download completed."
}
```

### 3. Job Status Check
* **Method**: `GET`
* **URL**: `http://127.0.0.1:8000/status/{job_id}`
* **Response**:
```json
{
  "job_id": "a1b2c3d4",
  "status": "downloading",
  "progress": 72,
  "filename": "Example Video Title.mp4",
  "path": "D:\\YT-Premiere-Downloads\\Example Video Title.mp4",
  "message": "Downloading... 72%",
  "error": null
}
```
*(Possible statuses: `queued`, `downloading`, `completed`, `error`)*
