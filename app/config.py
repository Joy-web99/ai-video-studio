"""
Studio configuration: workspace paths, 5 agents, and provider registry.
No fake data - only what is actually reachable via runtime engines.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = Path(os.getenv("STUDIO_WORKSPACE", str(BASE_DIR / "workspace")))

PROJECTS_DIR = WORKSPACE_DIR / "projects"
UPLOADS_DIR = WORKSPACE_DIR / "uploads"
OUTPUTS_DIR = WORKSPACE_DIR / "outputs"
TEMP_DIR = WORKSPACE_DIR / "temp"
CACHE_DIR = WORKSPACE_DIR / "cache"
STATE_FILE = WORKSPACE_DIR / "studio_state.json"

STATIC_DIR = BASE_DIR / "static"

def ensure_dirs() -> None:
    for d in (WORKSPACE_DIR, PROJECTS_DIR, UPLOADS_DIR, OUTPUTS_DIR, TEMP_DIR, CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)

ensure_dirs()

# ------------------------------------------------------------------
# Five core agents
# ------------------------------------------------------------------
AGENT_ORDER: List[str] = ["director", "image", "video", "audio", "editing"]

AGENTS: Dict[str, Dict[str, Any]] = {
    "director": {
        "id": "director",
        "name": "Director",
        "bn_name": "ডিরেক্টর",
        "role": "Story, planning, orchestration",
        "capabilities": ["TXT", "PLAN"],
        "preferred_model_keywords": [
            "gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash",
            "gpt-4o", "claude-3.5-sonnet", "claude-3-7-sonnet",
            "deepseek-chat", "deepseek-r1", "llama-3.3-70b",
        ],
    },
    "image": {
        "id": "image",
        "name": "Image",
        "bn_name": "ইমেজ",
        "role": "Keyframes, stills, thumbnails",
        "capabilities": ["IMG"],
        "preferred_model_keywords": [
            "imagen-3", "imagen-4", "flux", "gpt-image", "sdxl",
            "gemini-2.5-flash-image", "stable-diffusion",
        ],
    },
    "video": {
        "id": "video",
        "name": "Video",
        "bn_name": "ভিডিও",
        "role": "Motion video generation (T2V / I2V)",
        "capabilities": ["VID"],
        "preferred_model_keywords": [
            "veo", "gen-4", "gen4", "gen3a", "kling", "luma",
            "ray-2", "minimax", "pika", "ltx-video",
        ],
    },
    "audio": {
        "id": "audio",
        "name": "Audio",
        "bn_name": "অডিও",
        "role": "Voice, dubbing, BGM",
        "capabilities": ["AUD"],
        "preferred_model_keywords": [
            "eleven_multilingual", "eleven_turbo", "eleven_flash",
            "tts-1", "tts-1-hd", "edge-tts", "whisper",
        ],
    },
    "editing": {
        "id": "editing",
        "name": "Editing",
        "bn_name": "এডিটিং",
        "role": "FFmpeg assembly, subtitles, final MP4",
        "capabilities": ["EDT", "VID", "AUD"],
        "preferred_model_keywords": [
            "gemini-2.5-flash", "gpt-4o-mini", "llama-3.3-70b", "deepseek-chat",
        ],
    },
}

POWER_TIERS = ["Max", "High", "Medium", "Low"]

# ------------------------------------------------------------------
# Provider registry
# ------------------------------------------------------------------
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "google": {
        "id": "google",
        "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "models_endpoint": "https://generativelanguage.googleapis.com/v1beta/models",
        "auth": "query_key",
        "key_prefixes": ["AIza"],
        "capabilities": ["TXT", "PLAN", "IMG", "VID"],
        "default_models": {
            "director": "gemini-2.5-flash",
            "image": "imagen-3.0-generate-002",
            "video": "veo-2.0-generate-001",
            "editing": "gemini-2.5-flash",
        },
    },
    "openai": {
        "id": "openai",
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models_endpoint": "https://api.openai.com/v1/models",
        "auth": "bearer",
        "key_prefixes": ["sk-proj-", "sk-svcacct-", "sk-"],
        "capabilities": ["TXT", "PLAN", "IMG", "AUD"],
        "default_models": {
            "director": "gpt-4o-mini",
            "image": "gpt-image-1",
            "audio": "tts-1-hd",
            "editing": "gpt-4o-mini",
        },
    },
    "openrouter": {
        "id": "openrouter",
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "models_endpoint": "https://openrouter.ai/api/v1/models",
        "auth": "bearer",
        "key_prefixes": ["sk-or-v1-", "sk-or-"],
        "capabilities": ["TXT", "PLAN", "IMG"],
        "default_models": {
            "director": "google/gemini-2.0-flash-exp:free",
            "image": "google/gemini-2.5-flash-image-preview",
            "editing": "meta-llama/llama-3.3-70b-instruct:free",
        },
    },
    "groq": {
        "id": "groq",
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "models_endpoint": "https://api.groq.com/openai/v1/models",
        "auth": "bearer",
        "key_prefixes": ["gsk_"],
        "capabilities": ["TXT", "PLAN"],
        "default_models": {
            "director": "llama-3.3-70b-versatile",
            "editing": "llama-3.3-70b-versatile",
        },
    },
    "anthropic": {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "base_url": "https://api.anthropic.com/v1",
        "models_endpoint": "https://api.anthropic.com/v1/models",
        "auth": "x-api-key",
        "key_prefixes": ["sk-ant-"],
        "capabilities": ["TXT", "PLAN"],
        "default_models": {
            "director": "claude-3-5-sonnet-latest",
            "editing": "claude-3-5-haiku-latest",
        },
    },
    "deepseek": {
        "id": "deepseek",
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "models_endpoint": "https://api.deepseek.com/v1/models",
        "auth": "bearer",
        "key_prefixes": ["sk-"],
        "capabilities": ["TXT", "PLAN"],
        "default_models": {
            "director": "deepseek-chat",
            "editing": "deepseek-chat",
        },
    },
    "fal": {
        "id": "fal",
        "name": "fal.ai",
        "base_url": "https://fal.run",
        "models_endpoint": "https://fal.run/fal-ai/models",
        "auth": "key",
        "key_prefixes": ["fal_", "key_"],
        "capabilities": ["IMG", "VID", "AUD"],
        "default_models": {
            "image": "fal-ai/flux/schnell",
            "video": "fal-ai/kling-video/v1.6/standard/text-to-video",
            "audio": "fal-ai/f5-tts",
        },
    },
    "runway": {
        "id": "runway",
        "name": "RunwayML",
        "base_url": "https://api.dev.runwayml.com/v1",
        "models_endpoint": "https://api.dev.runwayml.com/v1/organization",
        "auth": "bearer",
        "key_prefixes": ["key_"],
        "capabilities": ["VID"],
        "default_models": {
            "video": "gen3a_turbo",
        },
    },
    "luma": {
        "id": "luma",
        "name": "Luma Dream Machine",
        "base_url": "https://api.lumalabs.ai/dream-machine/v1",
        "models_endpoint": "https://api.lumalabs.ai/dream-machine/v1/generations",
        "auth": "bearer",
        "key_prefixes": ["luma-"],
        "capabilities": ["VID", "IMG"],
        "default_models": {
            "video": "ray-2",
            "image": "photon-1",
        },
    },
    "elevenlabs": {
        "id": "elevenlabs",
        "name": "ElevenLabs",
        "base_url": "https://api.elevenlabs.io/v1",
        "models_endpoint": "https://api.elevenlabs.io/v1/models",
        "auth": "xi-api-key",
        "key_prefixes": ["sk_"],
        "capabilities": ["AUD"],
        "default_models": {
            "audio": "eleven_multilingual_v2",
        },
    },
    "replicate": {
        "id": "replicate",
        "name": "Replicate",
        "base_url": "https://api.replicate.com/v1",
        "models_endpoint": "https://api.replicate.com/v1/account",
        "auth": "bearer",
        "key_prefixes": ["r8_"],
        "capabilities": ["IMG", "VID", "AUD"],
        "default_models": {
            "image": "black-forest-labs/flux-schnell",
            "video": "minimax/video-01",
        },
    },
}

def get_provider(provider_id: str) -> Optional[Dict[str, Any]]:
    return PROVIDERS.get(provider_id)

def detect_provider_by_key(api_key: str) -> Optional[str]:
    key = (api_key or "").strip()
    if not key:
        return None
    # Check most specific prefixes first
    for prefix, pid in (
        ("sk-or-v1-", "openrouter"),
        ("sk-or-", "openrouter"),
        ("sk-proj-", "openai"),
        ("sk-svcacct-", "openai"),
        ("sk-ant-", "anthropic"),
        ("gsk_", "groq"),
        ("AIza", "google"),
        ("r8_", "replicate"),
        ("fal_", "fal"),
        ("luma-", "luma"),
        ("key_", "runway"),
        ("sk_", "elevenlabs"),
        ("sk-", "deepseek"),
    ):
        if key.startswith(prefix):
            return pid
    return None

def load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_state(state: Dict[str, Any]) -> None:
    ensure_dirs()
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
  )
