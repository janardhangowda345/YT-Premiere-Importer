# YT Premiere Importer

A custom Adobe Premiere Pro (2026+) UXP panel to download and import videos directly into your Premiere Pro project in one click.

## Architecture
- **extension/**: UXP Plugin (HTML/CSS/JS) running inside Premiere Pro.
- **downloader/**: Python helper (FastAPI + yt-dlp) running locally on port 8000.

## Current Stage: Stage 1
- Initial empty dockable UXP panel setup and verification in Premiere Pro.
