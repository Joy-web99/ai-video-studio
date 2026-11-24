# ==============================================================================
# AI Video Production Studio - Cinematic FFmpeg Video Assembler (Part C5)
# Covers: Ken Burns / Beat Zoom-Punch Motion, Bangla/Hindi/EN ASS Subtitles,
#         Auto-Ducking BGM Mix, Video Dubbing & Guaranteed H.264 .mp4 Export
# ==============================================================================

from __future__ import annotations

import asyncio
import subprocess
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from app.config import OUTPUTS_DIR, TEMP_DIR
from app.media_engine import aspect_ratio_to_dimensions
from app.models import ScenePlan, VideoSpec


# ------------------------------------------------------------------------------
# 1. ASYNC FFMPEG RUNNER & SUBTITLE HELPERS
# ------------------------------------------------------------------------------
def _run_ffmpeg_sync(cmd: List[str], timeout: int = 240) -> None:
    """Execute an FFmpeg command cleanly and raise detailed error on failure."""
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if proc.returncode != 0:
        err_tail = proc.stderr.decode("utf-8", errors="ignore")[-500:]
        raise RuntimeError(f"FFmpeg failed (code {proc.returncode}): {err_tail}")


async def run_ffmpeg(cmd: List[str], timeout: int = 240) -> None:
    """Non-blocking async wrapper around FFmpeg execution."""
    await asyncio.to_thread(_run_ffmpeg_sync, cmd, timeout)


def _format_ass_time(seconds: float) -> str:
    """Convert float seconds into ASS timestamp format H:MM:SS.cc."""
    total_cs = max(0, int(round(seconds * 100)))
    h = total_cs // 360000
    m = (total_cs % 360000) // 6000
    s = (total_cs % 6000) // 100
    cs = total_cs % 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _write_ass_subtitles(
    scenes: List[ScenePlan],
    width: int,
    height: int,
    language: str,
    out_path: Path,
) -> Path:
    """Generate a studio-styled ASS subtitle file supporting Bangla, Hindi & English."""
    low = (language or "").lower()
    if any(k in low for k in ("bengali", "bangla", "বাংলা")):
        font_name = "Noto Sans Bengali"
    elif any(k in low for k in ("hindi", "হিন্দি")):
        font_name = "Noto Sans Devanagari"
    else:
        font_name = "DejaVu Sans"

    font_size = max(28, int(height * 0.045))
    margin_v = max(36, int(height * 0.065))

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "WrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Studio,{font_name},{font_size},&H00FFFFFF,&H0000FFFF,&H00101010,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,3,1,2,40,40,{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines = [header]
    cursor = 0.0
    for sc in scenes:
        dur = max(1.5, float(sc.duration_sec))
        text = (sc.subtitle_text or sc.narration_text or "").strip().replace("\n", "\\N")
        if text:
            start_ts = _format_ass_time(cursor + 0.1)
            end_ts = _format_ass_time(cursor + dur - 0.1)
            lines.append(f"Dialogue: 0,{start_ts},{end_ts},Studio,,0,0,0,,{text}\n")
        cursor += dur

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(lines), encoding="utf-8")
    return out_path


# ------------------------------------------------------------------------------
# 2. CINEMATIC SCENE CLIP RENDERER (IMAGE MOTION OR AI VIDEO NORMALIZATION)
# ------------------------------------------------------------------------------
def _build_zoompan_filter(motion: str, frames: int, w: int, h: int, fps: int) -> str:
    """Build smooth FFmpeg zoompan expression for Ken Burns, pan, or beat-punch."""
    f_safe = max(1, frames)
    if motion == "ken_burns_out":
        expr = "z='if(lte(zoom,1.0),1.20,max(1.0,zoom-0.0014))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    elif motion == "pan_left":
        expr = f"z='1.14':x='max(0,(iw-iw/zoom)*(1-on/{f_safe}))':y='ih/2-(ih/zoom/2)'"
    elif motion == "pan_right":
        expr = f"z='1.14':x='min(iw-iw/zoom,(iw-iw/zoom)*(on/{f_safe}))':y='ih/2-(ih/zoom/2)'"
    elif motion == "zoom_punch":
        expr = "z='if(lt(on,10),1.0+0.024*on,max(1.04,1.24-0.003*(on-10)))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    elif motion == "shake_impact":
        expr = (
            "z='1.12':x='iw/2-(iw/zoom/2)+if(lt(on,14),sin(on*2.6)*14,0)':"
            "y='ih/2-(ih/zoom/2)+if(lt(on,14),cos(on*2.6)*10,0)'"
        )
    elif motion == "static":
        expr = "z='1.0':x='0':y='0'"
    else:  # ken_burns_in
        expr = "z='min(zoom+0.0014,1.20)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"

    return (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,"
        f"zoompan={expr}:d={f_safe}:s={w}x{h}:fps={fps},format=yuv420p"
    )


async def render_scene_clip(
    scene: ScenePlan,
    spec: VideoSpec,
    out_dir: Optional[Path] = None,
) -> Path:
    """
    Render a single standardized scene .mp4 clip with uniform codec, fps, resolution,
    and guaranteed stereo audio track (narration or silent bed) for seamless concat.
    """
    w, h = aspect_ratio_to_dimensions(spec.aspect_ratio, spec.resolution)
    fps = int(spec.fps or 30)
    dur = max(2.0, float(scene.duration_sec))
    frames = max(fps * 2, int(round(dur * fps)))

    save_dir = out_dir or TEMP_DIR
    save_dir.mkdir(parents=True, exist_ok=True)
    clip_out = save_dir / f"scene_{scene.scene_number:02d}_{uuid.uuid4().hex[:6]}.mp4"

    has_video = bool(scene.video_clip_path and Path(scene.video_clip_path).exists())
    has_image = bool(scene.image_path and Path(scene.image_path).exists())
    has_audio = bool(scene.audio_clip_path and Path(scene.audio_clip_path).exists())

    if not has_video and not has_image:
        raise RuntimeError(f"Scene {scene.scene_number} has neither verified AI image nor AI video clip.")

    cmd: List[str] = ["ffmpeg", "-y"]
    if has_video:
        cmd += ["-stream_loop", "-1", "-i", str(scene.video_clip_path)]
        vf = (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
            f"fps={fps},setsar=1,format=yuv420p"
        )
    else:
        cmd += ["-loop", "1", "-i", str(scene.image_path)]
        vf = _build_zoompan_filter(scene.camera_motion, frames, w, h, fps)

    # Add smooth fade in/out for non-beat transitions
    if scene.transition != "cut_beat":
        fade_out_start = max(0.2, dur - 0.35)
        vf += f",fade=t=in:st=0:d=0.3,fade=t=out:st={fade_out_start:.2f}:d=0.35"

    if has_audio:
        cmd += ["-i", str(scene.audio_clip_path)]
        audio_args = ["-map", "0:v:0", "-map", "1:a:0", "-af", f"apad,atrim=0:{dur:.3f}"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        audio_args = ["-map", "0:v:0", "-map", "1:a:0", "-af", f"atrim=0:{dur:.3f}"]

    cmd += [
        "-vf", vf,
        *audio_args,
        "-t", f"{dur:.3f}",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "44100",
        "-ac", "2",
        "-movflags", "+faststart",
        str(clip_out),
    ]
    await run_ffmpeg(cmd)
    return clip_out
import shutil


# ------------------------------------------------------------------------------
# 3. FULL CINEMA ASSEMBLY (CONCAT + AUTO-DUCK BGM + SUBTITLES -> FINAL .MP4)
# ------------------------------------------------------------------------------
def _escape_ffmpeg_filter_path(path: Path) -> str:
    """Escape path safely for FFmpeg libass subtitle filter."""
    raw = str(path.resolve()).replace("\\", "/")
    return raw.replace(":", "\\:").replace("'", "\\'")


async def assemble_final_video(
    scenes: List[ScenePlan],
    spec: VideoSpec,
    project_id: str,
    bgm_path: Optional[Path] = None,
    work_dir: Optional[Path] = None,
) -> Path:
    """
    Assemble all verified scenes into a guaranteed playable H.264/AAC .mp4:
      1. Render each scene into a uniform motion/video clip.
      2. Concatenate seamlessly with zero A/V drift.
      3. Mix optional BGM with smart auto-ducking so narration stays crystal clear.
      4. Burn studio ASS subtitles (Bangla/Hindi/English) if enabled.
    """
    if not scenes:
        raise RuntimeError("No scenes available to assemble final video.")

    w, h = aspect_ratio_to_dimensions(spec.aspect_ratio, spec.resolution)
    fps = int(spec.fps or 30)
    run_dir = work_dir or (TEMP_DIR / f"asm_{project_id}_{uuid.uuid4().hex[:6]}")
    run_dir.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Render individual standardized scene clips
    clip_paths: List[Path] = []
    for sc in scenes:
        clip = await render_scene_clip(sc, spec, out_dir=run_dir)
        clip_paths.append(clip)

    # Step 2: Concatenate all scene clips cleanly
    concat_txt = run_dir / "concat_list.txt"
    concat_lines = [
        f"file '{p.resolve().as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n"
        for p in clip_paths
    ]
    concat_txt.write_text("".join(concat_lines), encoding="utf-8")

    stitched_mp4 = run_dir / "stitched.mp4"
    await run_ffmpeg([
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_txt),
        "-c", "copy",
        "-movflags", "+faststart",
        str(stitched_mp4),
    ])

    # Step 3: Optional ASS Subtitles & BGM Auto-Ducking Master Pass
    has_bgm = bool(bgm_path and bgm_path.exists())
    has_subs = bool(spec.enable_subtitles and any((s.subtitle_text or s.narration_text).strip() for s in scenes))
    has_narration = any(bool(s.audio_clip_path and Path(s.audio_clip_path).exists()) for s in scenes)

    final_mp4 = OUTPUTS_DIR / f"{project_id}_{uuid.uuid4().hex[:6]}.mp4"

    if not has_bgm and not has_subs:
        shutil.move(str(stitched_mp4), str(final_mp4))
    else:
        cmd: List[str] = ["ffmpeg", "-y", "-i", str(stitched_mp4)]
        filter_parts: List[str] = []
        v_map = "0:v:0"
        a_map = "0:a:0"

        if has_bgm:
            cmd += ["-stream_loop", "-1", "-i", str(bgm_path)]
            bgm_vol = 0.22 if has_narration else 0.85
            if has_narration:
                filter_parts.append(
                    f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo,volume={bgm_vol:.2f}[bgm];"
                    "[0:a]aformat=sample_rates=44100:channel_layouts=stereo,asplit=2[voice_main][voice_sc];"
                    "[bgm][voice_sc]sidechaincompress=threshold=0.03:ratio=6:attack=25:release=350[bgm_ducked];"
                    "[voice_main][bgm_ducked]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,"
                    "loudnorm=I=-16:TP=-1.5:LRA=11[aout]"
                )
            else:
                filter_parts.append(
                    f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo,volume={bgm_vol:.2f}[bgm];"
                    "[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[aout]"
                )
            a_map = "[aout]"

        if has_subs:
            ass_path = _write_ass_subtitles(scenes, w, h, spec.language, run_dir / "subs.ass")
            escaped_ass = _escape_ffmpeg_filter_path(ass_path)
            filter_parts.append(f"[0:v]ass='{escaped_ass}'[vout]")
            v_map = "[vout]"

        cmd += [
            "-filter_complex", ";".join(filter_parts),
            "-map", v_map,
            "-map", a_map,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "21",
            "-pix_fmt", "yuv420p",
            "-r", str(fps),
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "44100",
            "-ac", "2",
            "-shortest",
            "-movflags", "+faststart",
            str(final_mp4),
        ]
        await run_ffmpeg(cmd)

    if not final_mp4.exists() or final_mp4.stat().st_size < 10_000:
        raise RuntimeError("Final assembled .mp4 video is missing or empty.")
    return final_mp4


# ------------------------------------------------------------------------------
# 4. VIDEO DUBBING ASSEMBLER (GUARANTEED MOBILE-COMPATIBLE H.264 .MP4)
# ------------------------------------------------------------------------------
async def assemble_dubbed_video(
    source_video: Path,
    dub_audio: Path,
    spec: VideoSpec,
    project_id: str,
    subtitle_text: str = "",
) -> Path:
    """
    Create a dubbed .mp4 by replacing original speech with the newly synthesized
    Bangla/Hindi/English neural voice track while guaranteeing mobile playback.
    """
    if not source_video.exists() or not dub_audio.exists():
        raise RuntimeError("Source video or dubbed audio file is missing.")

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = TEMP_DIR / f"dub_{project_id}_{uuid.uuid4().hex[:6]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    final_mp4 = OUTPUTS_DIR / f"dub_{project_id}_{uuid.uuid4().hex[:6]}.mp4"

    w, h = aspect_ratio_to_dimensions(spec.aspect_ratio, spec.resolution)
    cmd: List[str] = ["ffmpeg", "-y", "-i", str(source_video), "-i", str(dub_audio)]

    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
    if spec.enable_subtitles and subtitle_text.strip():
        dummy_scene = ScenePlan(
            scene_number=1,
            visual_prompt="dubbed video",
            subtitle_text=subtitle_text.strip(),
            duration_sec=max(4.0, float(spec.target_duration_sec or 15)),
        )
        ass_path = _write_ass_subtitles(
            [dummy_scene], w, h, spec.dubbing_target_lang or spec.language, run_dir / "dub.ass"
        )
        escaped_ass = _escape_ffmpeg_filter_path(ass_path)
        vf += f",ass='{escaped_ass}'"

    cmd += [
        "-vf", vf,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "21",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "44100",
        "-ac", "2",
        "-shortest",
        "-movflags", "+faststart",
        str(final_mp4),
    ]

    await run_ffmpeg(cmd)
    if not final_mp4.exists() or final_mp4.stat().st_size < 10_000:
        raise RuntimeError("Dubbed .mp4 output failed verification.")
    return final_mp4
