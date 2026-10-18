"""
yt-dlp wrapper and download manager for YT Premiere Importer.
Handles safe, local downloads with in-memory job status tracking,
H.264/AAC Premiere compatibility enforcement, and automated transcoding fallback.
"""

import os
import re
import shutil
import subprocess
import threading
import uuid
from typing import Dict, Any, Optional, Tuple

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

from config import get_format_selector, DEFAULT_OUTPUT_DIR

# Regex for YouTube URL validation (Standard watch, shorts, youtu.be, embed)
YOUTUBE_URL_REGEX = re.compile(
    r"^(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?(?:.*&)?v=|shorts\/|embed\/|v\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})(?:[?&].*)?$",
    re.IGNORECASE
)

# In-memory storage for download jobs
# Structure: { job_id: { "job_id": str, "status": str, "progress": int, "filename": str, "path": str, "title": str, "message": str, "error": Optional[str] } }
_download_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def get_ffmpeg_path() -> Optional[str]:
    """
    Locates FFmpeg binary:
    1. Checks system PATH.
    2. Checks imageio_ffmpeg bundled in the project virtual environment.
    """
    sys_path = shutil.which("ffmpeg")
    if sys_path:
        return sys_path

    try:
        import imageio_ffmpeg
        bundled_exe = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled_exe and os.path.exists(bundled_exe):
            return bundled_exe
    except Exception:
        pass

    return None


def get_node_path() -> Optional[str]:
    """
    Locates Node.js binary on the system to provide JavaScript runtime
    capabilities for yt-dlp challenge execution.
    """
    node_sys = shutil.which("node")
    if node_sys:
        return node_sys

    standard_paths = [
        r"C:\Program Files\nodejs\node.exe",
        r"C:\Program Files (x86)\nodejs\node.exe",
        os.path.expandvars(r"%APPDATA%\npm\node.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\node\node.exe"),
    ]
    for candidate in standard_paths:
        if os.path.exists(candidate):
            return candidate

    return None


def get_file_codecs(file_path: str) -> Dict[str, str]:
    """Inspects the video and audio codecs of a media file using bundled FFmpeg."""
    ffmpeg = get_ffmpeg_path()
    if not ffmpeg or not os.path.exists(file_path):
        return {"video": "unknown", "audio": "unknown"}

    cmd = [ffmpeg, "-i", file_path, "-hide_banner"]
    res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    output = res.stderr

    video_codec = "unknown"
    audio_codec = "unknown"

    for line in output.splitlines():
        if "Stream #" in line:
            if "Video:" in line and video_codec == "unknown":
                parts = line.split("Video:", 1)[-1].strip().split(",")
                video_codec = parts[0].strip()
            elif "Audio:" in line and audio_codec == "unknown":
                parts = line.split("Audio:", 1)[-1].strip().split(",")
                audio_codec = parts[0].strip()

    return {"video": video_codec, "audio": audio_codec}


def ensure_premiere_compatible_codecs(file_path: str, job_id: Optional[str] = None) -> Tuple[str, Dict[str, str]]:
    """
    Verifies that the downloaded file uses video codecs natively supported by Premiere Pro (H.264/AVC).
    If the file is encoded in AV1 (av01) or VP9, or has non-AAC audio, safely transcodes using bundled FFmpeg.
    """
    ffmpeg = get_ffmpeg_path()
    if not ffmpeg or not os.path.exists(file_path):
        return file_path, get_file_codecs(file_path)

    codecs = get_file_codecs(file_path)
    v_raw = codecs["video"].lower()
    a_raw = codecs["audio"].lower()

    is_h264 = "h264" in v_raw or "avc" in v_raw or "avc1" in v_raw
    is_aac = "aac" in a_raw or "mp4a" in a_raw

    # If already H.264 video and AAC audio, no transcoding is needed
    if is_h264 and is_aac:
        return file_path, codecs

    # Needs transcoding to ensure 100% Premiere Pro compatibility
    if job_id:
        with _jobs_lock:
            if job_id in _download_jobs:
                _download_jobs[job_id]["message"] = "Optimizing media codecs for Premiere Pro (H.264/AAC)..."

    dir_name = os.path.dirname(file_path)
    base_name, _ = os.path.splitext(os.path.basename(file_path))
    temp_output = os.path.join(dir_name, f"{base_name}_premiere_transcoded.mp4")

    cmd = [ffmpeg, "-y", "-i", file_path]

    if is_h264:
        # Video is already H.264, only convert audio to AAC
        cmd.extend(["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"])
    else:
        # Video is AV1/VP9, transcode video to standard H.264 (yuv420p) and audio to AAC
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k"
        ])

    cmd.append(temp_output)

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        if res.returncode == 0 and os.path.exists(temp_output):
            os.replace(temp_output, file_path)
        else:
            if os.path.exists(temp_output):
                os.remove(temp_output)
    except Exception as e:
        if os.path.exists(temp_output):
            os.remove(temp_output)

    final_codecs = get_file_codecs(file_path)
    return file_path, final_codecs


def is_valid_youtube_url(url: str) -> bool:
    """Check if the provided URL matches YouTube URL patterns."""
    if not url or not isinstance(url, str):
        return False
    return bool(YOUTUBE_URL_REGEX.match(url.strip()))


def create_job(url: str, quality: str, output_dir: str) -> str:
    """Create a new queued download job and return its job_id."""
    job_id = str(uuid.uuid4())[:8]
    with _jobs_lock:
        _download_jobs[job_id] = {
            "job_id": job_id,
            "url": url,
            "quality": quality,
            "output_dir": output_dir,
            "status": "queued",
            "progress": 0,
            "filename": "",
            "path": "",
            "title": "",
            "message": "Download queued.",
            "error": None
        }
    return job_id


def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve the current state of a download job."""
    with _jobs_lock:
        job = _download_jobs.get(job_id)
        if job:
            return dict(job)
    return None


def execute_download_sync(url: str, quality: str, output_dir: str, job_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Execute download synchronously using yt-dlp Python API.
    Updates the job status if job_id is provided.
    Enforces Premiere Pro H.264/AAC compatibility.
    """
    if not yt_dlp:
        err = "yt-dlp is not installed in the Python environment."
        if job_id:
            with _jobs_lock:
                _download_jobs[job_id]["status"] = "error"
                _download_jobs[job_id]["error"] = err
                _download_jobs[job_id]["message"] = err
        return {"success": False, "error": err}

    # Ensure output directory exists
    try:
        os.makedirs(output_dir, exist_ok=True)
    except Exception as e:
        err = f"Failed to create output directory: {str(e)}"
        if job_id:
            with _jobs_lock:
                _download_jobs[job_id]["status"] = "error"
                _download_jobs[job_id]["error"] = err
        return {"success": False, "error": err}

    # Ensure job entry exists in dictionary
    if job_id:
        with _jobs_lock:
            if job_id not in _download_jobs:
                _download_jobs[job_id] = {
                    "job_id": job_id,
                    "url": url,
                    "quality": quality,
                    "output_dir": output_dir,
                    "status": "downloading",
                    "progress": 0,
                    "filename": "",
                    "path": "",
                    "title": "",
                    "message": "Initializing download...",
                    "error": None
                }

    # Format selector, ffmpeg, and node JS runtime
    format_selector = get_format_selector(quality)
    ffmpeg_binary = get_ffmpeg_path()
    node_binary = get_node_path()

    # Progress hook callback
    def progress_hook(data: Dict[str, Any]):
        if not job_id:
            return
        status = data.get("status")
        with _jobs_lock:
            job = _download_jobs.get(job_id)
            if not job:
                return

            if status == "downloading":
                total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
                downloaded = data.get("downloaded_bytes") or 0
                pct = int((downloaded / total) * 100) if total > 0 else 0
                job["status"] = "downloading"
                job["progress"] = pct
                job["message"] = f"Downloading... {pct}%"
            elif status == "finished":
                job["progress"] = 99
                job["message"] = "Processing download..."

    # Configure yt-dlp options
    outtmpl = os.path.join(output_dir, "%(title)s.%(ext)s")

    ydl_opts = {
        "format": format_selector,
        "outtmpl": outtmpl,
        "nooverwrites": False,  # Allow clean replacement if redownloading same URL
        "noplaylist": True,     # Download single video only
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": False,
        "windowsfilenames": True,  # Sanitize for Windows filesystem
    }

    # Configure Node.js runtime for JavaScript challenge solving
    if node_binary:
        ydl_opts["js_runtimes"] = {
            "node": {"path": node_binary}
        }

    # Fallback player clients to ensure resilience against YouTube CDN changes
    ydl_opts["extractor_args"] = {
        "youtube": {
            "player_client": ["default", "web", "android"],
        }
    }

    if ffmpeg_binary:
        ydl_opts["ffmpeg_location"] = ffmpeg_binary
        ydl_opts["merge_output_format"] = "mp4"

    try:
        if job_id:
            with _jobs_lock:
                _download_jobs[job_id]["status"] = "downloading"
                _download_jobs[job_id]["message"] = "Fetching video metadata..."

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                raise ValueError("Could not extract video metadata from the provided URL.")

            title = info.get("title", "Video")
            expected_filepath = ydl.prepare_filename(info)

            # Check if postprocessor changed the extension (e.g. mp4, mkv, webm)
            final_filepath = expected_filepath
            if not os.path.exists(final_filepath):
                base, _ = os.path.splitext(expected_filepath)
                for ext in [".mp4", ".mkv", ".webm", ".mov"]:
                    candidate = base + ext
                    if os.path.exists(candidate):
                        final_filepath = candidate
                        break

            # -------------------------------------------------------------
            # Enforce Premiere Pro Codec Compatibility (H.264 + AAC in MP4)
            # -------------------------------------------------------------
            final_filepath, final_codecs = ensure_premiere_compatible_codecs(final_filepath, job_id)
            filename = os.path.basename(final_filepath)

            # Update job state
            if job_id:
                with _jobs_lock:
                    _download_jobs[job_id]["status"] = "completed"
                    _download_jobs[job_id]["progress"] = 100
                    _download_jobs[job_id]["title"] = title
                    _download_jobs[job_id]["filename"] = filename
                    _download_jobs[job_id]["path"] = final_filepath
                    _download_jobs[job_id]["message"] = "Download completed."

            return {
                "success": True,
                "job_id": job_id,
                "title": title,
                "filename": filename,
                "path": final_filepath,
                "codecs": final_codecs,
                "message": "Download completed."
            }

    except Exception as e:
        error_msg = str(e)
        if "ERROR:" in error_msg:
            error_msg = error_msg.split("ERROR:", 1)[-1].strip()

        if job_id:
            with _jobs_lock:
                _download_jobs[job_id]["status"] = "error"
                _download_jobs[job_id]["error"] = error_msg
                _download_jobs[job_id]["message"] = f"Download failed: {error_msg}"

        return {
            "success": False,
            "job_id": job_id,
            "error": error_msg
        }


def start_download_async(url: str, quality: str, output_dir: str) -> str:
    """Start download in a background daemon thread and return the job_id."""
    job_id = create_job(url, quality, output_dir)
    thread = threading.Thread(
        target=execute_download_sync,
        args=(url, quality, output_dir, job_id),
        daemon=True
    )
    thread.start()
    return job_id
