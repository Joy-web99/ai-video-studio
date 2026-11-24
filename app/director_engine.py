# ==============================================================================
# AI Video Production Studio - Director AI, Style-DNA & Re-Briefing (Part C2)
# Covers: YouTube Reference Style-DNA Learner, Autonomous Spec & Scene Planner,
#         Interactive Spec Re-Briefing, Board Meeting & Dubbing Translation
# ==============================================================================

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

import yt_dlp

from app.models import (
    AgentSlot,
    BeatEnergyMap,
    ResourceItem,
    ScenePlan,
    VideoSpec,
)
from app.provider_engine import call_llm_slot


# ------------------------------------------------------------------------------
# 1. JSON EXTRACTION HELPER (ZERO-HALLUCINATION PARSER)
# ------------------------------------------------------------------------------
def extract_json_object(raw_text: str) -> Dict[str, Any]:
    """Safely extract a JSON dictionary from LLM output even if wrapped in markdown."""
    text = (raw_text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


# ------------------------------------------------------------------------------
# 2. NATIVE YOUTUBE REFERENCE STYLE-DNA LEARNER
# ------------------------------------------------------------------------------
def _extract_youtube_meta_sync(url: str) -> Dict[str, Any]:
    """Extract metadata, pacing cues, and tags from a YouTube reference URL safely."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "noplaylist": True,
        "socket_timeout": 15,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False) or {}
        return {
            "title": info.get("title", ""),
            "description": (info.get("description") or "")[:600],
            "duration": info.get("duration", 0),
            "tags": (info.get("tags") or [])[:15],
            "categories": info.get("categories") or [],
            "uploader": info.get("uploader", ""),
        }


async def learn_youtube_style_dna(
    youtube_url: str,
    director_slot: Optional[AgentSlot] = None,
) -> Dict[str, Any]:
    """Learn cinematic pacing, visual style, and editing DNA from a YouTube link."""
    try:
        meta = await asyncio.to_thread(_extract_youtube_meta_sync, youtube_url)
    except Exception as exc:
        meta = {"title": youtube_url, "error": str(exc)}

    dna: Dict[str, Any] = {
        "source_url": youtube_url,
        "reference_title": meta.get("title", "Reference Video"),
        "visual_style": "High-Detail 2D Anime Cinema with Dynamic Lighting",
        "pacing": "dynamic_cinematic",
        "camera_grammar": "Smooth Ken Burns push-ins with dramatic beat cuts",
        "color_palette": "Rich deep shadows, vibrant rim highlights, cinematic contrast",
        "editing_rhythm": "Cut on emotional peaks and musical transitions",
    }

    if director_slot:
        sys_prompt = (
            "You are a Master Film & Animation Director. Analyze the reference video metadata "
            "and extract a concise Style-DNA JSON with keys: visual_style, pacing, "
            "camera_grammar, color_palette, editing_rhythm."
        )
        user_prompt = f"Reference Video Metadata:\n{json.dumps(meta, ensure_ascii=False)}"
        try:
            raw = await call_llm_slot(
                director_slot, sys_prompt, user_prompt, temperature=0.4, max_tokens=600
            )
            parsed = extract_json_object(raw)
            if parsed:
                dna.update(parsed)
        except Exception:
            pass

    return dna


# ------------------------------------------------------------------------------
# 3. LANGUAGE & NEURAL VOICE DETECTION
# ------------------------------------------------------------------------------
def detect_voice_for_language(language: str) -> str:
    """Select natural Edge-TTS neural voice for detected language."""
    low = (language or "").lower()
    if any(k in low for k in ("bengali", "bangla", "বাংলা")):
        return "bn-IN-BashkarNeural"
    if any(k in low for k in ("hindi", "হিন্দি")):
        return "hi-IN-MadhurNeural"
    if any(k in low for k in ("arabic", "আরবি")):
        return "ar-SA-HamedNeural"
    if any(k in low for k in ("spanish",)):
        return "es-ES-AlvaroNeural"
    return "en-US-GuyNeural"


def _detect_language_from_prompt(prompt: str) -> str:
    """Detect primary language from Unicode script or explicit language keywords."""
    if re.search(r"[\u0980-\u09FF]", prompt):
        return "Bengali"
    if re.search(r"[\u0900-\u097F]", prompt):
        return "Hindi"
    low = prompt.lower()
    if any(k in low for k in ("bangla", "bengali")):
        return "Bengali"
    if "hindi" in low:
        return "Hindi"
    return "English"
      # ------------------------------------------------------------------------------
# 4. SAFE LITERAL SANITIZERS & SCENE BUILDERS (ZERO-HALLUCINATION)
# ------------------------------------------------------------------------------
VALID_MOTIONS = {
    "ken_burns_in", "ken_burns_out", "pan_left",
    "pan_right", "zoom_punch", "shake_impact", "static",
}
VALID_TRANSITIONS = {"fade", "cut_beat", "flash", "dissolve", "wipe"}
VALID_RATIOS = {"16:9", "9:16", "1:1", "4:5"}
VALID_RESOLUTIONS = {"720p", "1080p", "4K"}
VALID_MODES = {
    "text_to_video", "image_to_video", "photo_edit",
    "music_beat_video", "music_video_edit", "video_dubbing",
}


def _infer_project_mode(prompt: str, resources: List[ResourceItem]) -> str:
    """Detect the best production mode from user prompt and uploaded resources."""
    low = prompt.lower()
    kinds = {r.kind for r in resources}
    if any(k in low for k in ("dub", "dubbing", "ডাবিং", "ভয়েস বদলা", "translate video")):
        return "video_dubbing"
    if "audio" in kinds and "video" in kinds:
        return "music_video_edit"
    if "audio" in kinds or any(k in low for k in ("beat sync", "music video", "বিট সিঙ্ক", "গানের ভিডিও")):
        return "music_beat_video"
    if any(k in low for k in ("edit photo", "photo edit", "ছবি এডিট", "thumbnail", "থাম্বনেইল")):
        return "photo_edit"
    if "image" in kinds and "video" not in kinds:
        return "image_to_video"
    return "text_to_video"


def _build_scene_objects(
    raw_scenes: List[Dict[str, Any]],
    spec: VideoSpec,
    beat_map: Optional[BeatEnergyMap] = None,
) -> List[ScenePlan]:
    """Validate and construct ScenePlan objects aligned with spec and beat timestamps."""
    count = max(1, min(12, int(spec.scene_count or 4)))
    default_dur = round(max(2.5, spec.target_duration_sec / count), 2)
    drops = list(beat_map.bass_drop_timestamps) if beat_map else []
    beats = list(beat_map.beat_timestamps) if beat_map else []

    scenes: List[ScenePlan] = []
    for idx in range(count):
        item = raw_scenes[idx] if idx < len(raw_scenes) and isinstance(raw_scenes[idx], dict) else {}
        motion = item.get("camera_motion", "ken_burns_in")
        if motion not in VALID_MOTIONS:
            motion = "zoom_punch" if spec.enable_beat_sync else "ken_burns_in"

        trans = item.get("transition", "cut_beat" if spec.enable_beat_sync else "fade")
        if trans not in VALID_TRANSITIONS:
            trans = "cut_beat" if spec.enable_beat_sync else "fade"

        trigger = None
        if spec.enable_beat_sync:
            if idx < len(drops):
                trigger = drops[idx]
                motion = "zoom_punch"
            elif idx < len(beats):
                trigger = beats[idx]

        visual = str(item.get("visual_prompt") or "").strip()
        if not visual:
            visual = (
                f"{spec.visual_style}, cinematic frame {idx + 1} of {spec.title or 'story'}: "
                f"{spec.story_outline[:180]}. Highly detailed characters, rich atmospheric lighting, "
                "studio anime production quality, ultra sharp."
            )
        elif spec.visual_style.lower() not in visual.lower():
            visual = f"{spec.visual_style}, {visual}"

        narration = str(item.get("narration_text") or "").strip()
        subtitle = str(item.get("subtitle_text") or narration).strip()
        try:
            dur = float(item.get("duration_sec", default_dur))
            dur = max(2.0, min(15.0, dur))
        except (TypeError, ValueError):
            dur = default_dur

        scenes.append(
            ScenePlan(
                scene_number=idx + 1,
                visual_prompt=visual,
                narration_text=narration,
                subtitle_text=subtitle,
                duration_sec=dur,
                camera_motion=motion,
                transition=trans,
                beat_trigger_sec=trigger,
            )
        )
    return scenes


# ------------------------------------------------------------------------------
# 5. DIRECTOR PLANNER (INITIAL BRIEF -> POPULATED SPEC + BOARD MEETING)
# ------------------------------------------------------------------------------
async def build_director_plan(
    prompt: str,
    resources: List[ResourceItem],
    director_slot: Optional[AgentSlot] = None,
    secondary_slot: Optional[AgentSlot] = None,
    beat_map: Optional[BeatEnergyMap] = None,
) -> Dict[str, Any]:
    """
    Analyze prompt + resources + Style-DNA + Beat-Map to populate the
    Left-Corner Spec Inspector (lifecycle='populated') and draft ScenePlans.
    """
    lang = _detect_language_from_prompt(prompt)
    mode = _infer_project_mode(prompt, resources)
    voice = detect_voice_for_language(lang)
    ratio = "9:16" if any(k in prompt.lower() for k in ("short", "reel", "9:16", "vertical", "শর্ট")) else "16:9"
    dna_list = [r.style_dna for r in resources if r.style_dna]
    style_hint = dna_list[0].get("visual_style") if dna_list else "2D High-Quality Anime Cinema"

    spec = VideoSpec(
        lifecycle="populated",
        title=prompt[:60].strip() or "Studio Cinema Project",
        project_mode=mode if mode in VALID_MODES else "text_to_video",
        aspect_ratio=ratio,
        resolution="1080p",
        fps=30,
        visual_style=style_hint,
        language=lang,
        voice_profile=voice,
        enable_subtitles=True,
        enable_beat_sync=bool(beat_map or mode in ("music_beat_video", "music_video_edit")),
        scene_count=4,
        target_duration_sec=int(beat_map.duration_sec) if beat_map and 8 <= beat_map.duration_sec <= 60 else 20,
        story_outline=prompt,
    )

    raw_scenes: List[Dict[str, Any]] = []
    seo_metadata: Dict[str, Any] = {"title": spec.title, "tags": ["AI Studio", "2D Animation"]}
    board_notes: List[str] = []

    if director_slot:
        sys_prompt = (
            "You are the Chief Director AI of a Professional Video Production Studio. "
            "Return ONLY valid JSON with keys: "
            "title, visual_style, aspect_ratio (16:9|9:16|1:1|4:5), resolution (720p|1080p|4K), "
            "fps (24|30|60), scene_count (3..8), target_duration_sec, bgm_mood, story_outline, "
            "board_meeting_notes (array of 3 short agent coordination lines), "
            "seo_metadata ({title, description, tags}), and scenes (array of objects with "
            "visual_prompt in detailed English for 2D/Cinema AI image/video gen, narration_text in user language, "
            "subtitle_text, duration_sec, camera_motion, transition)."
        )
        ctx = {
            "user_prompt": prompt,
            "detected_language": lang,
            "detected_mode": mode,
            "style_dna": dna_list,
            "beat_bpm": beat_map.bpm if beat_map else None,
        }
        try:
            raw = await call_llm_slot(
                director_slot, sys_prompt, json.dumps(ctx, ensure_ascii=False), temperature=0.65, max_tokens=2400
            )
            parsed = extract_json_object(raw)
            if parsed:
                spec.title = str(parsed.get("title") or spec.title)[:90]
                spec.visual_style = str(parsed.get("visual_style") or spec.visual_style)
                if parsed.get("aspect_ratio") in VALID_RATIOS:
                    spec.aspect_ratio = parsed["aspect_ratio"]
                if parsed.get("resolution") in VALID_RESOLUTIONS:
                    spec.resolution = parsed["resolution"]
                if parsed.get("fps") in (24, 30, 60):
                    spec.fps = parsed["fps"]
                if isinstance(parsed.get("scene_count"), int):
                    spec.scene_count = max(2, min(10, parsed["scene_count"]))
                if isinstance(parsed.get("target_duration_sec"), (int, float)):
                    spec.target_duration_sec = max(8, min(120, int(parsed["target_duration_sec"])))
                spec.bgm_mood = str(parsed.get("bgm_mood") or spec.bgm_mood)
                spec.story_outline = str(parsed.get("story_outline") or spec.story_outline)
                raw_scenes = parsed.get("scenes") if isinstance(parsed.get("scenes"), list) else []
                if isinstance(parsed.get("seo_metadata"), dict):
                    seo_metadata = parsed["seo_metadata"]
                if isinstance(parsed.get("board_meeting_notes"), list):
                    board_notes = [str(x) for x in parsed["board_meeting_notes"][:5]]
        except Exception:
            pass

    # Optional Secondary Director Dual-Model Polish
    if secondary_slot and raw_scenes:
        try:
            polish_sys = (
                "You are Co-Director AI. Refine each scene's visual_prompt for studio-grade 2D/cinema detail "
                "and return JSON: {\"scenes\": [...]}. Preserve exact scene count and narration_text."
            )
            raw_p = await call_llm_slot(
                secondary_slot, polish_sys, json.dumps({"scenes": raw_scenes}, ensure_ascii=False), 0.5, 2000
            )
            parsed_p = extract_json_object(raw_p)
            if isinstance(parsed_p.get("scenes"), list) and len(parsed_p["scenes"]) == len(raw_scenes):
                raw_scenes = parsed_p["scenes"]
                board_notes.append("Co-Director (Secondary AI) refined visual keyframes for higher cinema detail.")
        except Exception:
            pass

    scenes = _build_scene_objects(raw_scenes, spec, beat_map)
    return {
        "spec": spec,
        "scenes": scenes,
        "seo_metadata": seo_metadata,
        "board_notes": board_notes or [
            f"Director briefed team: {spec.visual_style} | {spec.aspect_ratio} {spec.resolution} @ {spec.fps}fps.",
            f"Image/Video agents assigned {len(scenes)} cinematic keyframes.",
            f"Audio/Editing agents locked {spec.language} voice ({spec.voice_profile}) & FFmpeg cinema assembly.",
        ],
    }


# ------------------------------------------------------------------------------
# 6. RE-BRIEFING ENGINE (AFTER USER EDITS & CLICKS APPROVE IN SPEC INSPECTOR)
# ------------------------------------------------------------------------------
async def re_brief_after_approval(
    prompt: str,
    approved_spec: VideoSpec,
    director_slot: Optional[AgentSlot] = None,
    beat_map: Optional[BeatEnergyMap] = None,
) -> List[ScenePlan]:
    """Regenerate and lock exact ScenePlans matching the user-approved VideoSpec."""
    approved_spec.lifecycle = "approved"
    approved_spec.voice_profile = approved_spec.voice_profile or detect_voice_for_language(approved_spec.language)
    raw_scenes: List[Dict[str, Any]] = []

    if director_slot:
        sys_prompt = (
            "You are Director AI executing a strict Re-Briefing after user approval. "
            "Follow EVERY user setting strictly (scene_count, visual_style, language, custom_notes, dubbing). "
            "Return ONLY valid JSON: {\"scenes\": [{visual_prompt, narration_text, subtitle_text, "
            "duration_sec, camera_motion, transition}]}."
        )
        payload = {
            "original_prompt": prompt,
            "approved_spec": approved_spec.model_dump(),
        }
        try:
            raw = await call_llm_slot(
                director_slot, sys_prompt, json.dumps(payload, ensure_ascii=False), temperature=0.55, max_tokens=2200
            )
            parsed = extract_json_object(raw)
            if isinstance(parsed.get("scenes"), list):
                raw_scenes = parsed["scenes"]
        except Exception:
            pass

    return _build_scene_objects(raw_scenes, approved_spec, beat_map)


# ------------------------------------------------------------------------------
# 7. DUBBING TRANSLATOR & DIRECT 5-AGENT CHAT
# ------------------------------------------------------------------------------
async def translate_dubbing_script(
    source_text: str,
    target_language: str,
    director_slot: Optional[AgentSlot] = None,
) -> str:
    """Translate or adapt dialogue naturally for neural video dubbing."""
    if not source_text.strip() or not director_slot:
        return source_text
    sys_prompt = (
        f"You are a professional dubbing scriptwriter. Translate the dialogue naturally into {target_language} "
        "keeping timing and emotion intact. Return ONLY the translated dialogue text."
    )
    try:
        return (await call_llm_slot(director_slot, sys_prompt, source_text, temperature=0.35, max_tokens=1000)).strip()
    except Exception:
        return source_text


async def direct_agent_chat_reply(
    agent_id: str,
    message: str,
    project_context: str,
    slot: Optional[AgentSlot] = None,
) -> str:
    """Respond directly as one of the 5 specialist agents inside the Workflow Box."""
    if not slot:
        return f"[{agent_id.upper()} Agent] এই এজেন্টে এখনও কোনো সক্রিয় API Key যুক্ত করা হয়নি। Settings থেকে Key দিন।"
    sys_prompt = (
        f"You are the specialist {agent_id.upper()} Agent inside an AI Video Production Studio. "
        "Answer concisely in the user's language (Bangla or English) with actionable studio guidance."
    )
    user_payload = f"Project Context:\n{project_context[:800]}\n\nUser Message:\n{message}"
    return (await call_llm_slot(slot, sys_prompt, user_payload, temperature=0.6, max_tokens=800)).strip()
