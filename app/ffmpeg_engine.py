"""
FFmpeg Media Engine: Handles cinematic assembly, audio sync, subtitles, and atomic publishing.
This is the fallback magic: it turns static AI images + audio into a REAL MP4 video 
with smooth cinematic motion (Ken Burns effect) if video APIs are unavailable.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import TEMP_DIR, OUTPUTS_DIR
from app.models import Asset, utc_now_iso


# ------------------------------------------------------------------------------
# 1. VERIFICATION TOOLS (The "No Fake Video" Guard)
# ------------------------------------------------------------------------------
def probe_media(file_path: Path) -> Dict[str, Any]:
    """Verify if a file is a valid media file using FFprobe. Returns duration and codec."""
    if not file_path.exists() or file_path.stat().st_size < 1000:
        return {"valid": False, "error": "File is empty or too small."}

    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration,format_name",
        "-show_entries", "stream=codec_name,codec_type", "-of", "json", str(file_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return {"valid": False, "error": result.stderr}
        
        import json
        data = json.loads(result.stdout)
        duration = float(data.get("format", {}).get("duration", 0))
        format_name = data.get("format", {}).get("format_name", "")
        
        if duration <= 0:
            return {"valid": False, "error": "Zero duration media."}

        # Check if it actually has a video stream
        has_video = False
        codec = ""
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                has_video = True
                codec = stream.get("codec_name", "")
                break

        if not has_video and file_path.suffix == ".mp4":
            return {"valid": False, "error": "File has no video stream."}

        return {
            "valid": True,
            "duration": round(duration, 2),
            "format": format_name,
            "codec": codec
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}


# ------------------------------------------------------------------------------
# 2. CINEMATIC IMAGE-TO-VIDEO (Ken Burns Effect)
# ------------------------------------------------------------------------------
def create_cinematic_clip(
    image_path: Path,
    output_path: Path,
    duration_sec: float,
    aspect_ratio: str = "16:9",
    motion: str = "ken_burns_in",
    fps: int = 30
) -> bool:
    """Takes a static image and adds smooth motion using FFmpeg zoompan filter."""
    if not image_path.exists():
        return False

    # Determine resolution based on aspect ratio
    if aspect_ratio == "16:9":
        w, h = 1920, 1080
    elif aspect_ratio == "9:16":
        w, h = 1080, 1920
    elif aspect_ratio == "1:1":
        w, h = 1080, 1080
    else:
        w, h = 1920, 1080

    # Zoompan filter logic
    # z: zoom expression, x/y: position, d: duration in frames
    # We scale up first to allow room for panning (e.g., 2x scale)
    zoom_expr = "min(zoom+0.0015,1.5)" # Smooth zoom in
    x_expr = "iw/2-(iw/zoom/2)"
    y_expr = "ih/2-(ih/zoom/2)"

    if motion == "pan_left":
        zoom_expr = "1.15"
        x_expr = "iw/2-(iw/zoom/2)-(t*20)"
    elif motion == "pan_right":
        zoom_expr = "1.15"
        x_expr = "iw/2-(iw/zoom/2)+(t*20)"
    elif motion == "zoom_out":
        zoom_expr = "if(lte(zoom,1.0),1.5,max(1.001,zoom-0.0015))"

    filter_complex = (
        f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,"
        f"crop={w*2}:{h*2},"
        f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':d={int(duration_sec*fps)}:s={w}x{h}:fps={fps},"
        f"format=yuv420p"
    )

    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", str(image_path),
        "-vf", filter_complex,
        "-t", str(duration_sec),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        str(output_path)
    ]

    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=60)
        return True
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg Clip Error: {e.stderr.decode()}")
        return False


# ------------------------------------------------------------------------------
# 3. ASSEMBLE SCENES + AUDIO + SUBTITLES INTO FINAL MP4
# ------------------------------------------------------------------------------
async def assemble_final_video(
    scene_clips: List[Path],
    audio_path: Optional[Path],
    subtitle_path: Optional[Path],
    output_filename: str,
    aspect_ratio: str = "16:9",
) -> Dict[str, Any]:
    """
    Concatenates scene clips, adds audio, burns subtitles, and outputs a final MP4.
    Uses ATOMIC PUBLISHING: writes to .partial.mp4, verifies it, then renames to .mp4.
    """
    if not scene_clips:
        return {"ok": False, "error": "No scene clips to assemble."}

    # 1. Create a text file listing all clips for concat
    concat_file = TEMP_DIR / f"concat_{uuid.uuid4().hex[:6]}.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for clip in scene_clips:
            f.write(f"file '{clip.as_posix()}'\n")

    # 2. Define output paths (Atomic Publish)
    partial_name = f"{output_filename}.partial.mp4"
    final_name = f"{output_filename}.mp4"
    
    partial_path = OUTPUTS_DIR / partial_name
    final_path = OUTPUTS_DIR / final_name

    # 3. Build FFmpeg command
    cmd = [
        "ffmpeg", "-y", 
        "-f", "concat", "-safe", "0", "-i", str(concat_file)
    ]

    # Add audio if exists
    if audio_path and audio_path.exists():
        cmd.extend(["-i", str(audio_path)])
    
    # Add subtitles filter if exists
    vf_filters = []
    if subtitle_path and subtitle_path.exists():
        # Escape path for Windows/Linux FFmpeg subtitle filter compatibility
        sub_path_escaped = str(subtitle_path).replace("\\", "/").replace(":", "\\:")
        vf_filters.append(f"subtitles='{sub_path_escaped}':force_style='FontName=Noto Sans Bengali,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000'")

    if vf_filters:
        cmd.extend(["-vf", ",".join(vf_filters)])

    # Encoding settings
    cmd.extend([
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", # Crucial for web playback
        "-shortest", # Match audio/video length
        str(partial_path)
    ])

    try:
        # Run encoding
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            err_text = stderr.decode()[-500:] # Get last 500 chars of error
            return {"ok": False, "error": f"FFmpeg Assembly Failed: {err_text}"}

        # 4. VERIFY THE PARTIAL FILE (Decode Test Gate)
        probe = probe_media(partial_path)
        if not probe.get("valid"):
            partial_path.unlink(missing_ok=True)
            return {"ok": False, "error": f"Video generated but verification failed: {probe.get('error')}"}

        # 5. ATOMIC PUBLISH (Rename from .partial to final)
        if final_path.exists():
            final_path.unlink()
        partial_path.rename(final_path)

        # Clean up concat file
        concat_file.unlink(missing_ok=True)

        return {
            "ok": True,
            "path": final_path,
            "public_url": f"/outputs/{final_name}",
            "duration": probe.get("duration", 0),
            "size_bytes": final_path.stat().st_size
        }

    except Exception as e:
        return {"ok": False, "error": f"Assembly crashed: {str(e)}"}
