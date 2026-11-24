# ==============================================================================
# AI Video Production Studio - Core Configuration & Provider Registry (Part B1)
# Covers: Workspace Paths, 5 Agent Definitions, Dynamic Capability Badges,
#         Universal Provider Registry (Top 3 Paid vs Free), & Auto-Learn Memory
# ==============================================================================

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# ------------------------------------------------------------------------------
# 1. WORKSPACE & RUNTIME DIRECTORIES
# ------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = Path(os.getenv("STUDIO_WORKSPACE", str(BASE_DIR / "workspace")))

PROJECTS_DIR = WORKSPACE_DIR / "projects"
UPLOADS_DIR = WORKSPACE_DIR / "uploads"
OUTPUTS_DIR = WORKSPACE_DIR / "outputs"
TEMP_DIR = WORKSPACE_DIR / "temp"
CACHE_DIR = WORKSPACE_DIR / "cache"
PROVIDERS_DIR = WORKSPACE_DIR / "providers"
CUSTOM_PROVIDERS_FILE = PROVIDERS_DIR / "custom_providers.json"
STUDIO_STATE_FILE = PROVIDERS_DIR / "studio_state.json"

STATIC_DIR = BASE_DIR / "static"


def ensure_workspace_dirs() -> None:
    """Create all required runtime directories safely."""
    for d in (
        WORKSPACE_DIR,
        PROJECTS_DIR,
        UPLOADS_DIR,
        OUTPUTS_DIR,
        TEMP_DIR,
        CACHE_DIR,
        PROVIDERS_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)


# Initialize directories on module load
ensure_workspace_dirs()

# ------------------------------------------------------------------------------
# 2. FIVE AGENT CATEGORIES & POWER LEVELS
# ------------------------------------------------------------------------------
AGENT_ORDER: List[str] = ["director", "image", "video", "audio", "editing"]

AGENT_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "director": {
        "id": "director",
        "name": "Director",
        "bn_name": "ডিরেক্টর",
        "role": "Story, Script, Style-DNA, Board Meeting & Multi-Agent Orchestrator",
        "required_capabilities": ["reasoning", "script"],
        "optional_capabilities": ["vision", "coding", "translation", "metadata", "planning"],
    },
    "image": {
        "id": "image",
        "name": "Image",
        "bn_name": "ইমেজ",
        "role": "2D Animation Art, Cinematic Keyframes, Photo Editing & Thumbnails",
        "required_capabilities": ["image_gen"],
        "optional_capabilities": ["graphics", "image_edit", "upscale", "style_transfer"],
    },
    "video": {
        "id": "video",
        "name": "Video",
        "bn_name": "ভিডিও",
        "role": "Text-to-Video (T2V), Image-to-Video (I2V) & Motion Synthesis",
        "required_capabilities": ["video_gen"],
        "optional_capabilities": ["i2v", "t2v", "motion_fx", "cinema_render"],
    },
    "audio": {
        "id": "audio",
        "name": "Audio",
        "bn_name": "অডিও",
        "role": "Neural Voiceover, Bangla/Hindi Dubbing, BGM & Beat-Sync DSP",
        "required_capabilities": ["audio_tts"],
        "optional_capabilities": ["dubbing", "music_gen", "voice_clone", "beat_dsp"],
    },
    "editing": {
        "id": "editing",
        "name": "Editing",
        "bn_name": "এডিটিং",
        "role": "FFmpeg Cinema Assembly, Velocity Beat-Cut, Subtitles & Color Grading",
        "required_capabilities": ["editing"],
        "optional_capabilities": ["beat_sync", "subtitles", "color_grade", "auto_ducking", "coding"],
    },
}

# Dynamic Capability Badges (displayed in the middle of each agent row)
CAPABILITY_CATALOG: Dict[str, Dict[str, str]] = {
    "reasoning": {"label": "Reasoning", "icon": "brain", "color": "#60a5fa"},
    "script": {"label": "Script", "icon": "file-text", "color": "#818cf8"},
    "vision": {"label": "Vision", "icon": "eye", "color": "#38bdf8"},
    "coding": {"label": "Coding", "icon": "code", "color": "#34d399"},
    "planning": {"label": "Planning", "icon": "git-branch", "color": "#a78bfa"},
    "translation": {"label": "Translate", "icon": "languages", "color": "#f472b6"},
    "metadata": {"label": "SEO/Title", "icon": "tag", "color": "#fbbf24"},
    "image_gen": {"label": "Image Gen", "icon": "image", "color": "#c084fc"},
    "graphics": {"label": "2D/Art", "icon": "palette", "color": "#e879f9"},
    "image_edit": {"label": "Photo Edit", "icon": "wand", "color": "#f472b6"},
    "upscale": {"label": "HD Upscale", "icon": "sparkles", "color": "#2dd4bf"},
    "video_gen": {"label": "Video Gen", "icon": "film", "color": "#fb923c"},
    "t2v": {"label": "T2V", "icon": "clapperboard", "color": "#f97316"},
    "i2v": {"label": "I2V", "icon": "play-circle", "color": "#fb7185"},
    "cinema_render": {"label": "Cinema MP4", "icon": "video", "color": "#f59e0b"},
    "audio_tts": {"label": "Voice TTS", "icon": "mic", "color": "#22d3ee"},
    "dubbing": {"label": "Dubbing", "icon": "globe", "color": "#38bdf8"},
    "music_gen": {"label": "BGM/Music", "icon": "music", "color": "#a3e635"},
    "beat_dsp": {"label": "Beat DSP", "icon": "activity", "color": "#4ade80"},
    "editing": {"label": "Pro Edit", "icon": "scissors", "color": "#facc15"},
    "beat_sync": {"label": "Beat-Sync", "icon": "zap", "color": "#fbbf24"},
    "subtitles": {"label": "Subtitles", "icon": "subtitles", "color": "#94a3b8"},
    "color_grade": {"label": "Color Grade", "icon": "sliders", "color": "#f43f5e"},
    "auto_ducking": {"label": "Auto-Duck", "icon": "volume-2", "color": "#2dd4bf"},
}

POWER_LEVELS = ("Max", "High", "Medium", "Low")

# ------------------------------------------------------------------------------
# 3. UNIVERSAL BUILT-IN PROVIDER REGISTRY (3-Tier Auto-Detect + Top 3 Paid/Free)
# ------------------------------------------------------------------------------
PROVIDER_REGISTRY: Dict[str, Dict[str, Any]] = {
    "google_gemini": {
        "id": "google_gemini",
        "name": "Google Gemini",
        "brand_short": "Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "openai_compat_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "models_endpoint": "https://generativelanguage.googleapis.com/v1beta/models",
        "auth_type": "query_key",
        "key_prefixes": ["AIza"],
        "capabilities": [
            "reasoning", "script", "vision", "coding", "planning",
            "translation", "metadata", "image_gen", "graphics", "editing",
        ],
        "supports_agents": ["director", "image", "editing", "audio"],
        "default_models": {
            "director": "gemini-2.5-flash",
            "image": "imagen-3.0-generate-002",
            "editing": "gemini-2.5-flash",
            "audio": "gemini-2.5-flash",
        },
        "top_paid": [
            {"id": "gemini-2.5-pro", "note": "Flagship Reasoning, Script & Vision"},
            {"id": "imagen-3.0-generate-002", "note": "Studio 2D/3D High-Res Image Gen"},
            {"id": "veo-2.0-generate-001", "note": "Cinematic AI Video Generation"},
        ],
        "top_free": [
            {"id": "gemini-2.5-flash", "note": "Fast Free Tier Director & Vision"},
            {"id": "gemini-2.0-flash", "note": "High-Speed Free Multimodal Engine"},
            {"id": "gemini-2.0-flash-exp-image-generation", "note": "Free Native Image Generation"},
        ],
    },
    "openrouter": {
        "id": "openrouter",
        "name": "OpenRouter",
        "brand_short": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "models_endpoint": "https://openrouter.ai/api/v1/models",
        "auth_type": "bearer",
        "key_prefixes": ["sk-or-v1-", "sk-or-"],
        "capabilities": [
            "reasoning", "script", "vision", "coding", "planning",
            "translation", "metadata", "image_gen", "editing",
        ],
        "supports_agents": ["director", "image", "editing"],
        "default_models": {
            "director": "google/gemini-2.0-flash-exp:free",
            "image": "google/gemini-2.5-flash-image-preview",
            "editing": "meta-llama/llama-3.3-70b-instruct:free",
        },
        "top_paid": [
            {"id": "anthropic/claude-3.7-sonnet", "note": "Master Storytelling & Coding"},
            {"id": "openai/gpt-4o", "note": "All-Round Vision & Director Brain"},
            {"id": "google/gemini-2.5-pro-preview", "note": "Long-Context Cinema Planning"},
        ],
        "top_free": [
            {"id": "google/gemini-2.0-flash-exp:free", "note": "Top Free Multimodal Director"},
            {"id": "deepseek/deepseek-r1:free", "note": "Deep Free Reasoning Engine"},
            {"id": "meta-llama/llama-3.3-70b-instruct:free", "note": "Fast Free 70B Script Writer"},
        ],
    },
    "fal_ai": {
        "id": "fal_ai",
        "name": "Fal.ai",
        "brand_short": "Fal.ai",
        "base_url": "https://fal.run",
        "queue_url": "https://queue.fal.run",
        "models_endpoint": "https://api.fal.ai/v1/models",
        "auth_type": "fal_key",
        "key_prefixes": ["fal_", "key_"],
        "capabilities": [
            "image_gen", "graphics", "image_edit", "upscale",
            "video_gen", "t2v", "i2v", "cinema_render", "audio_tts", "music_gen",
        ],
        "supports_agents": ["image", "video", "audio"],
        "default_models": {
            "image": "fal-ai/flux/schnell",
            "video": "fal-ai/kling-video/v1.6/standard/text-to-video",
            "audio": "fal-ai/f5-tts",
        },
        "top_paid": [
            {"id": "fal-ai/kling-video/v2/master/text-to-video", "note": "Pro Cinema Video (T2V/I2V)"},
            {"id": "fal-ai/flux-pro/v1.1-ultra", "note": "Ultra 2D/Cinema Keyframe Art"},
            {"id": "fal-ai/minimax/video-01-live", "note": "High-Quality 2D Anime Motion"},
        ],
        "top_free": [
            {"id": "fal-ai/flux/schnell", "note": "Ultra-Fast Low-Cost FLUX Art"},
            {"id": "fal-ai/fast-sdxl", "note": "Lightweight Rapid 2D Art"},
            {"id": "fal-ai/ltx-video", "note": "Fast Lightweight Video Gen"},
        ],
    },
    "groq": {
        "id": "groq",
        "name": "Groq",
        "brand_short": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "models_endpoint": "https://api.groq.com/openai/v1/models",
        "auth_type": "bearer",
        "key_prefixes": ["gsk_"],
        "capabilities": [
            "reasoning", "script", "vision", "coding", "planning",
            "translation", "metadata", "editing", "audio_tts",
        ],
        "supports_agents": ["director", "editing", "audio"],
        "default_models": {
            "director": "llama-3.3-70b-versatile",
            "editing": "llama-3.3-70b-versatile",
            "audio": "whisper-large-v3-turbo",
        },
        "top_paid": [
            {"id": "llama-3.3-70b-versatile", "note": "High-Throughput 70B Director"},
            {"id": "meta-llama/llama-4-maverick-17b-128e-instruct", "note": "Next-Gen Vision & Script"},
            {"id": "deepseek-r1-distill-llama-70b", "note": "Fast Deep Reasoning"},
        ],
        "top_free": [
            {"id": "llama-3.3-70b-versatile", "note": "Generous Free Tier 70B Model"},
            {"id": "llama-3.1-8b-instant", "note": "Instant Ultra-Fast Chat & Edit"},
            {"id": "whisper-large-v3-turbo", "note": "Free Ultra-Fast Audio Transcribe"},
        ],
    },
    "openai": {
        "id": "openai",
        "name": "OpenAI",
        "brand_short": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models_endpoint": "https://api.openai.com/v1/models",
        "auth_type": "bearer",
        "key_prefixes": ["sk-proj-", "sk-svcacct-", "sk-"],
        "capabilities": [
            "reasoning", "script", "vision", "coding", "planning",
            "translation", "metadata", "image_gen", "graphics", "audio_tts", "editing",
        ],
        "supports_agents": ["director", "image", "audio", "editing"],
        "default_models": {
            "director": "gpt-4o-mini",
            "image": "gpt-image-1",
            "audio": "tts-1-hd",
            "editing": "gpt-4o-mini",
        },
        "top_paid": [
            {"id": "gpt-4o", "note": "Flagship Multimodal Director"},
            {"id": "gpt-image-1", "note": "Pro 2D/3D Image & Text Rendering"},
            {"id": "tts-1-hd", "note": "Studio-Grade Neural Voice"},
        ],
        "top_free": [
            {"id": "gpt-4o-mini", "note": "Most Affordable Fast Model"},
            {"id": "tts-1", "note": "Standard Low-Cost Voice"},
            {"id": "whisper-1", "note": "Accurate Audio Transcription"},
        ],
    },
    "huggingface": {
        "id": "huggingface",
        "name": "Hugging Face",
        "brand_short": "HuggingFace",
        "base_url": "https://router.huggingface.co/hf-inference",
        "models_endpoint": "https://huggingface.co/api/whoami-v2",
        "auth_type": "bearer",
        "key_prefixes": ["hf_"],
        "capabilities": [
            "reasoning", "script", "image_gen", "graphics",
            "video_gen", "audio_tts", "music_gen",
        ],
        "supports_agents": ["image", "director", "video", "audio"],
        "default_models": {
            "image": "black-forest-labs/FLUX.1-schnell",
            "director": "Qwen/Qwen2.5-72B-Instruct",
            "video": "Lightricks/LTX-Video",
            "audio": "facebook/musicgen-small",
        },
        "top_paid": [
            {"id": "black-forest-labs/FLUX.1-dev", "note": "Pro Dedicated FLUX Image Art"},
            {"id": "Qwen/Qwen2.5-72B-Instruct", "note": "Dedicated Pro 72B Script Brain"},
            {"id": "Wan-AI/Wan2.1-T2V-14B", "note": "Dedicated Open-Weight Video Gen"},
        ],
        "top_free": [
            {"id": "black-forest-labs/FLUX.1-schnell", "note": "Best Free 2D/Cinema Image Gen"},
            {"id": "stabilityai/stable-diffusion-xl-base-1.0", "note": "Reliable Free SDXL Art"},
            {"id": "Qwen/Qwen2.5-72B-Instruct", "note": "Free Serverless Director LLM"},
        ],
    },
    "elevenlabs": {
        "id": "elevenlabs",
        "name": "ElevenLabs",
        "brand_short": "ElevenLabs",
        "base_url": "https://api.elevenlabs.io/v1",
        "models_endpoint": "https://api.elevenlabs.io/v1/models",
        "auth_type": "xi-api-key",
        "key_prefixes": ["sk_"],
        "capabilities": ["audio_tts", "dubbing", "voice_clone", "music_gen"],
        "supports_agents": ["audio"],
        "default_models": {
            "audio": "eleven_multilingual_v2",
        },
        "top_paid": [
            {"id": "eleven_multilingual_v2", "note": "Ultra-Realistic Bangla/Hindi/EN Voice"},
            {"id": "eleven_v3", "note": "Expressive Cinematic Acting Voice"},
            {"id": "eleven_turbo_v2_5", "note": "Pro Low-Latency Dubbing"},
        ],
        "top_free": [
            {"id": "eleven_multilingual_v2", "note": "10k Free Chars/Month Multilingual"},
            {"id": "eleven_flash_v2_5", "note": "Fastest Free-Quota Voice"},
            {"id": "eleven_turbo_v2_5", "note": "Balanced Free-Quota Dubbing"},
        ],
    },
    "deepseek": {
        "id": "deepseek",
        "name": "DeepSeek",
        "brand_short": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "models_endpoint": "https://api.deepseek.com/v1/models",
        "auth_type": "bearer",
        "key_prefixes": ["sk-"],
        "capabilities": ["reasoning", "script", "coding", "planning", "translation", "editing"],
        "supports_agents": ["director", "editing"],
        "default_models": {
            "director": "deepseek-chat",
            "editing": "deepseek-chat",
        },
        "top_paid": [
            {"id": "deepseek-reasoner", "note": "R1 Deep Story & Logic Planner"},
            {"id": "deepseek-chat", "note": "V3 High-Speed Script & Coding"},
            {"id": "deepseek-coder", "note": "Dedicated Code & FFmpeg Logic"},
        ],
        "top_free": [
            {"id": "deepseek-chat", "note": "Ultra-Low Cost V3 Engine"},
            {"id": "deepseek-reasoner", "note": "Cost-Effective Reasoning"},
            {"id": "deepseek-chat", "note": "Use via OpenRouter :free for $0"},
        ],
    },
    "anthropic": {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "brand_short": "Claude",
        "base_url": "https://api.anthropic.com/v1",
        "models_endpoint": "https://api.anthropic.com/v1/models",
        "auth_type": "x-api-key",
        "key_prefixes": ["sk-ant-"],
        "capabilities": ["reasoning", "script", "vision", "coding", "planning", "translation", "editing"],
        "supports_agents": ["director", "editing"],
        "default_models": {
            "director": "claude-3-7-sonnet-latest",
            "editing": "claude-3-5-haiku-latest",
        },
        "top_paid": [
            {"id": "claude-3-7-sonnet-latest", "note": "Best Creative Script & Coding"},
            {"id": "claude-3-5-sonnet-latest", "note": "High-Precision Scene Direction"},
            {"id": "claude-3-5-haiku-latest", "note": "Fast Affordable Editing Brain"},
        ],
        "top_free": [
            {"id": "claude-3-5-haiku-latest", "note": "Lowest-Cost Claude Tier"},
            {"id": "claude-3-haiku-20240307", "note": "Ultra-Light Backup Tier"},
            {"id": "claude-3-5-sonnet-latest", "note": "Balanced Credit Usage"},
        ],
    },
    "together": {
        "id": "together",
        "name": "Together AI",
        "brand_short": "Together",
        "base_url": "https://api.together.xyz/v1",
        "models_endpoint": "https://api.together.xyz/v1/models",
        "auth_type": "bearer",
        "key_prefixes": ["tgp_v1_"],
        "capabilities": ["reasoning", "script", "coding", "image_gen", "graphics", "editing"],
        "supports_agents": ["director", "image", "editing"],
        "default_models": {
            "director": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "image": "black-forest-labs/FLUX.1-schnell-Free",
            "editing": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        },
        "top_paid": [
            {"id": "black-forest-labs/FLUX.1.1-pro", "note": "Pro 2D/Cinema Image Art"},
            {"id": "deepseek-ai/DeepSeek-R1", "note": "Full-Power Deep Reasoning"},
            {"id": "Qwen/Qwen2.5-72B-Instruct-Turbo", "note": "Fast Multilingual Script"},
        ],
        "top_free": [
            {"id": "black-forest-labs/FLUX.1-schnell-Free", "note": "Free FLUX Image Generation"},
            {"id": "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free", "note": "Free 70B Director"},
            {"id": "deepseek-ai/DeepSeek-R1-Distill-Llama-70B-free", "note": "Free Reasoning"},
        ],
    },
    "nvidia_nim": {
        "id": "nvidia_nim",
        "name": "NVIDIA NIM",
        "brand_short": "NVIDIA",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "models_endpoint": "https://integrate.api.nvidia.com/v1/models",
        "auth_type": "bearer",
        "key_prefixes": ["nvapi-"],
        "capabilities": ["reasoning", "script", "vision", "coding", "image_gen", "editing"],
        "supports_agents": ["director", "image", "editing"],
        "default_models": {
            "director": "meta/llama-3.3-70b-instruct",
            "image": "black-forest-labs/flux.1-schnell",
            "editing": "meta/llama-3.3-70b-instruct",
        },
        "top_paid": [
            {"id": "deepseek-ai/deepseek-r1", "note": "Enterprise GPU Reasoning"},
            {"id": "meta/llama-3.1-405b-instruct", "note": "405B Heavyweight Story Brain"},
            {"id": "black-forest-labs/flux.1-dev", "note": "Pro High-Detail Art"},
        ],
        "top_free": [
            {"id": "meta/llama-3.3-70b-instruct", "note": "Free Developer Credits 70B"},
            {"id": "black-forest-labs/flux.1-schnell", "note": "Free Developer Credits FLUX"},
            {"id": "qwen/qwen2.5-coder-32b-instruct", "note": "Free Coding & FFmpeg Brain"},
        ],
    },
}

# Auto-load extended providers (Runway, Luma, Stability, Mistral, Replicate, xAI, etc.)
try:
    from app.extra_providers import EXTRA_PROVIDERS
    PROVIDER_REGISTRY.update(EXTRA_PROVIDERS)
except ImportError:
    pass


# ------------------------------------------------------------------------------
# 4. PERSISTENT CUSTOM PROVIDER MEMORY (AUTO-LEARN BASE URL)
# ------------------------------------------------------------------------------
def load_custom_providers() -> Dict[str, Dict[str, Any]]:
    """Load user-taught custom Base URL providers from persistent JSON."""
    if not CUSTOM_PROVIDERS_FILE.exists():
        return {}
    try:
        data = json.loads(CUSTOM_PROVIDERS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_custom_provider(provider_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a newly discovered custom Base URL provider so it is never asked twice."""
    ensure_workspace_dirs()
    current = load_custom_providers()
    current[provider_id] = config
    CUSTOM_PROVIDERS_FILE.write_text(
        json.dumps(current, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return config


def get_all_providers() -> Dict[str, Dict[str, Any]]:
    """Return merged dictionary of built-in + auto-learned custom providers."""
    merged = dict(PROVIDER_REGISTRY)
    merged.update(load_custom_providers())
    return merged


def get_provider_by_id(provider_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single provider definition from built-in or custom registry."""
    return get_all_providers().get(provider_id)
  
