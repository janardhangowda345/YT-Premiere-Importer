"""
Configuration settings for YT Premiere Importer Downloader Service.
"""

from typing import List

# Network Binding - Strictly local loopback for security
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000

# Supported quality options mapped to resolutions
SUPPORTED_QUALITIES: List[str] = [
    "best",
    "2160",
    "1440",
    "1080",
    "720",
    "480",
    "360"
]


def get_format_selector(quality: str) -> str:
    """
    Returns format selector prioritizing H.264/AVC (avc1) video and AAC (mp4a) audio
    for native, crash-free Adobe Premiere Pro compatibility.
    Avoids AV1 (av01) and VP9 whenever an H.264 option is available.
    Falls back to best available streams if AVC is absent (which will then be
    transcoded by the downloader fallback if required).
    """
    q = quality.strip().lower()

    if q == "best":
        return (
            "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
            "bestvideo[vcodec^=avc1]+bestaudio/"
            "best[vcodec^=avc1]/"
            "bestvideo+bestaudio/"
            "best"
        )

    try:
        height = int(q)
        return (
            f"bestvideo[vcodec^=avc1][height<={height}]+bestaudio[acodec^=mp4a]/"
            f"bestvideo[vcodec^=avc1][height<={height}]+bestaudio/"
            f"best[vcodec^=avc1][height<={height}]/"
            f"bestvideo[height<={height}]+bestaudio/"
            f"best[height<={height}]/best"
        )
    except ValueError:
        return (
            "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
            "bestvideo[vcodec^=avc1]+bestaudio/"
            "best[vcodec^=avc1]/"
            "bestvideo+bestaudio/"
            "best"
        )


# Default output directory
DEFAULT_OUTPUT_DIR = r"D:\YT-Premiere-Downloads"
