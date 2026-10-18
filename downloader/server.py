
import os
import logging
from typing import Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import SERVER_HOST, SERVER_PORT, SUPPORTED_QUALITIES, DEFAULT_OUTPUT_DIR
from downloader import (
    is_valid_youtube_url,
    create_job,
    get_job_status,
    execute_download_sync,
    start_download_async,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("yt_importer_server")

# FastAPI App initialization
app = FastAPI(
    title="YT Premiere Importer Service",
    description="Local backend service for downloading authorized YouTube media for Premiere Pro.",
    version="1.0.0"
)

# CORS Middleware - permits requests from local UXP panels
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request & Response Schemas
class DownloadRequest(BaseModel):
    url: str = Field(..., description="YouTube video URL")
    quality: str = Field("1080", description="Target video quality (best, 2160, 1440, 1080, 720, 480, 360)")
    output_dir: Optional[str] = Field(DEFAULT_OUTPUT_DIR, description="Local folder to save downloaded file")
    async_mode: Optional[bool] = Field(True, description="Whether to execute download asynchronously in background")


class DownloadResponse(BaseModel):
    success: bool
    job_id: Optional[str] = None
    title: Optional[str] = None
    filename: Optional[str] = None
    path: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


class StatusResponse(BaseModel):
    job_id: str
    status: str
    progress: int
    filename: Optional[str] = ""
    path: Optional[str] = ""
    title: Optional[str] = ""
    message: Optional[str] = ""
    error: Optional[str] = None


@app.get("/health", summary="Health Check")
async def health():
    """Verify that the service is running and accessible."""
    return {"status": "ok"}


@app.post("/download", response_model=DownloadResponse, summary="Download Video")
async def download(req: DownloadRequest):
    """
    Validate input and download YouTube video using yt-dlp.
    Validates:
      - URL presence and YouTube URL format
      - Quality is in supported qualities
      - Output directory exists or can be created
    """
    logger.info(f"Received download request: url={req.url}, quality={req.quality}, dir={req.output_dir}, async={req.async_mode}")

    # 1. Validate URL presence and format
    if not req.url or not req.url.strip():
        logger.warning("Download rejected: URL is empty.")
        return DownloadResponse(
            success=False,
            error="Please enter a YouTube URL."
        )

    if not is_valid_youtube_url(req.url):
        logger.warning(f"Download rejected: Invalid YouTube URL: {req.url}")
        return DownloadResponse(
            success=False,
            error="Please enter a valid YouTube URL."
        )

    # 2. Validate Quality
    quality_val = str(req.quality).strip().lower()
    if quality_val not in SUPPORTED_QUALITIES:
        logger.warning(f"Download rejected: Unsupported quality '{req.quality}'.")
        return DownloadResponse(
            success=False,
            error=f"Unsupported quality '{req.quality}'. Supported: {', '.join(SUPPORTED_QUALITIES)}"
        )

    # 3. Validate / Prepare Output Directory
    target_dir = req.output_dir.strip() if req.output_dir and req.output_dir.strip() else DEFAULT_OUTPUT_DIR
    try:
        os.makedirs(target_dir, exist_ok=True)
    except Exception as e:
        logger.error(f"Cannot access or create output directory '{target_dir}': {e}")
        return DownloadResponse(
            success=False,
            error=f"Cannot access or create output directory: {str(e)}"
        )

    # 4. Execute Download
    if req.async_mode:
        # Start background job
        job_id = start_download_async(req.url.strip(), quality_val, target_dir)
        logger.info(f"Async download job created: {job_id}")
        return DownloadResponse(
            success=True,
            job_id=job_id,
            message="Download queued."
        )
    else:
        # Synchronous download
        job_id = create_job(req.url.strip(), quality_val, target_dir)
        result = execute_download_sync(req.url.strip(), quality_val, target_dir, job_id)
        if result.get("success"):
            logger.info(f"Download completed: {result.get('filename')} -> {result.get('path')}")
            return DownloadResponse(
                success=True,
                job_id=job_id,
                title=result.get("title"),
                filename=result.get("filename"),
                path=result.get("path"),
                message="Download completed."
            )
        else:
            logger.error(f"Download failed for job {job_id}: {result.get('error')}")
            return DownloadResponse(
                success=False,
                job_id=job_id,
                error=result.get("error", "Unknown download error.")
            )


@app.get("/status/{job_id}", response_model=StatusResponse, summary="Get Download Status")
async def get_status(job_id: str):
    """Retrieve progress and status of a download job."""
    job_info = get_job_status(job_id)
    if not job_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job ID '{job_id}' not found."
        )

    return StatusResponse(
        job_id=job_info["job_id"],
        status=job_info["status"],
        progress=job_info["progress"],
        filename=job_info.get("filename", ""),
        path=job_info.get("path", ""),
        title=job_info.get("title", ""),
        message=job_info.get("message", ""),
        error=job_info.get("error")
    )


if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting YT Premiere Importer Downloader service on http://{SERVER_HOST}:{SERVER_PORT}...")
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
