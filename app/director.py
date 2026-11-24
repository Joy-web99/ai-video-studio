"""
Director AI Engine: Learns styles, plans scenes, and builds the VideoSpec.
Zero-hallucination parser ensures AI bad formatting never crashes the system.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

import yt_dlp

from app.models import (
    KeySlot, ResourceItem, ScenePlan, VideoSpec,
)
from app.providers import call_llm_slot


# ------------------------------------------------------------------------------
# 1. ZERO-HALLUCINATION JSON PARSER
# ------------------------------------------------------------------------------
def extract_json_object(raw_text: str) -> Dict[str, Any]:
    """Safely extract JSON from LLM output even if wrapped in markdown fences."""
    text = (raw_text or "").strip()
    # Try to find JSON inside ```json ... ```
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        # Try to find the first { and last }
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
# 2. YOUTUBE STYLE-DNA LEARNER
# ------------------------------------------------------------------------------
def _extract_youtube_meta_sync(url: str) -> Dict[str, Any]:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
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
        }

async def learn_youtube_style_dna(youtube_url: str, director_slot: Optional[KeySlot] = None) -> Dict[str, Any]:
    try:
        meta = await asyncio.to_thread(_extract_youtube_meta_sync, youtube_url)
    except Exception as exc:
        meta = {"title": "Unknown Reference", "error": str(exc)}

    dna = {
        "source_url": youtube_url,
        "visual_style": "High-Detail Cinematic 2D Anime",
        "pacing": "dynamic",
        "color_palette": "Rich shadows, vibrant highlights",
    }

    if director_slot:
        sys_prompt = (
            "You are a Master Director. Analyze this video metadata and extract a Style-DNA JSON "
            "with keys: visual_style, pacing, color_palette. Keep it brief."
        )
        try:
            raw = await call_llm_slot(director_slot, sys_prompt, json.dumps(meta), temperature=0.4, max_tokens=400)
            parsed = extract_json_object(raw)
            if parsed:
                dna.update(parsed)
        except Exception:
            pass

    return dna


# ------------------------------------------------------------------------------
# 3. LANGUAGE & MODE DETECTION
# ------------------------------------------------------------------------------
def detect_language(prompt: str) -> str:
    if re.search(r"[\u0980-\u09FF]", prompt): return "Bengali"
    if re.search(r"[\u0900-\u097F]", prompt): return "Hindi"
    low = prompt.lower()
    if "bangla" in low or "bengali" in low: return "Bengali"
    if "hindi" in low: return "Hindi"
    return "English"

def detect_voice(language: str) -> str:
    low = (language or "").lower()
    if "bengali" in low or "bangla" in low: return "bn-IN-BashkarNeural"
    if "hindi" in low: return "hi-IN-MadhurNeural"
    return "en-US-GuyNeural"

def infer_project_mode(prompt: str, resources: List[ResourceItem]) -> str:
    low = prompt.lower()
    kinds = {r.kind for r in resources}
    if any(k in low for k in ("dub", "dubbing", "ডাবিং")): return "video_dubbing"
    if "audio" in kinds and "video" in kinds: return "music_video_edit"
    if "audio" in kinds or any(k in low for k in ("beat sync", "music video", "বিট সিঙ্ক")): return "music_beat_video"
    if any(k in low for k in ("edit photo", "photo edit", "ছবি এডিট")): return "photo_edit"
    if "image" in kinds and "video" not in kinds: return "image_to_video"
    return "text_to_video"


# ------------------------------------------------------------------------------
# 4. MAIN DIRECTOR PLANNER
# ------------------------------------------------------------------------------
async def build_director_plan(
    prompt: str,
    resources: List[ResourceItem],
    director_slot: Optional[KeySlot] = None,
) -> Dict[str, Any]:
    """Analyze user prompt and build a structured VideoSpec and ScenePlan list."""
    lang = detect_language(prompt)
    mode = infer_project_mode(prompt, resources)
    voice = detect_voice(lang)
    ratio = "9:16" if any(k in prompt.lower() for k in ("short", "reel", "9:16", "শর্ট")) else "16:9"

    spec = VideoSpec(
        lifecycle="populated",
        title=prompt[:50].strip() or "Studio Project",
        project_mode=mode,
        aspect_ratio=ratio,
        resolution="1080p",
        fps=30,
        language=lang,
        voice_profile=voice,
        enable_subtitles=True,
        enable_beat_sync=(mode in ("music_beat_video", "music_video_edit")),
        scene_count=4,
        target_duration_sec=20,
        story_outline=prompt,
    )

    raw_scenes = []
    
    if director_slot:
        sys_prompt = (
            "You are the Chief Director AI. Return ONLY valid JSON with keys: "
            "title, visual_style, story_outline, "
            "scenes (array of objects with visual_prompt in detailed English, "
            "narration_text in user language, duration_sec)."
        )
        try:
            raw = await call_llm_slot(director_slot, sys_prompt, prompt, temperature=0.7, max_tokens=2000)
            parsed = extract_json_object(raw)
            if parsed:
                spec.title = str(parsed.get("title") or spec.title)[:60]
                spec.visual_style = str(parsed.get("visual_style") or spec.visual_style)
                spec.story_outline = str(parsed.get("story_outline") or spec.story_outline)
                raw_scenes = parsed.get("scenes", [])
        except Exception:
            pass # Fallback to manual generation below

    # Build actual ScenePlan objects (with fallback if AI failed)
    scenes = []
    count = max(1, min(10, len(raw_scenes) if raw_scenes else spec.scene_count))
    for idx in range(count):
        item = raw_scenes[idx] if idx < len(raw_scenes) else {}
        
        visual = str(item.get("visual_prompt") or f"{spec.visual_style}, scene {idx+1}: {prompt[:100]}")
        narration = str(item.get("narration_text") or "")
        
        scenes.append(
            ScenePlan(
                scene_number=idx + 1,
                visual_prompt=visual,
                narration_text=narration,
                duration_sec=float(item.get("duration_sec", 4.0)),
                camera_motion="ken_burns_in",
                transition="fade"
            )
        )

    return {"spec": spec, "scenes": scenes}


# ------------------------------------------------------------------------------
# 5. DIRECT AGENT CHAT (For Workflow Box)
# ------------------------------------------------------------------------------
async def direct_agent_chat_reply(
    agent_id: str,
    message: str,
    slot: Optional[KeySlot] = None,
) -> str:
    """Respond directly as one of the 5 specialist agents."""
    if not slot or not slot.api_key:
        return f"[{agent_id.upper()} Agent] এই এজেন্টে এখনও কোনো সক্রিয় API Key যুক্ত করা হয়নি। Settings থেকে Key দিন।"
        
    sys_prompt = (
        f"You are the specialist {agent_id.upper()} Agent inside an AI Video Production Studio. "
        "Answer concisely in the user's language (Bangla or English) with actionable studio guidance."
    )
    try:
        return await call_llm_slot(slot, sys_prompt, message, temperature=0.6, max_tokens=800)
    except Exception as e:
        return f"[{agent_id.upper()} Agent] Error: {str(e)}"
