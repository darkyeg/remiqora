"""Serve a compact MP3 download without keeping a second copy in the library."""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .routes_yue2_upload import get_ffmpeg_bin


async def mp3_download(source: Path, filename: str) -> FileResponse:
    if source.suffix.lower() == ".mp3":
        return FileResponse(source, media_type="audio/mpeg", filename=filename)

    ffmpeg = get_ffmpeg_bin()
    if not ffmpeg:
        raise HTTPException(status_code=503, detail="FFmpeg is unavailable for MP3 export")

    fd, output = tempfile.mkstemp(prefix="remiqora-export-", suffix=".mp3")
    os.close(fd)
    try:
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(source), "-map", "0:a:0", "-vn", "-codec:a", "libmp3lame",
            "-q:a", "2", output,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"MP3 export failed: {stderr.decode('utf-8', 'replace').strip()[:500]}",
            )
        return FileResponse(
            output, media_type="audio/mpeg", filename=filename,
            background=BackgroundTask(Path(output).unlink, missing_ok=True),
        )
    except BaseException:
        Path(output).unlink(missing_ok=True)
        raise
