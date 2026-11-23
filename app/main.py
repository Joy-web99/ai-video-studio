import os
import re
import time
import uuid
import json
import base64
import asyncio
import urllib.parse
from typing import Any, Dict, List, Optional
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="AI Production Studio V3 - Verified Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ইন-মেমরি জব স্টোরেজ (লাইভ প্রোগ্রেস, Co-Work ব্লু LED কাউন্ট ও এজেন্ট স্টেটসহ)
JOBS: Dict[str, Dict[str, Any]] = {}
MAX_JOBS = 120

# প্রতিটি এজেন্টের জন্য Paid ও Free সেরা মডেলের অগ্রাধিকার তালিকা
ROLE_PREFS_PAID = {
    "director": ["gemini-2.5-pro", "claude-3.7-sonnet", "claude-3.5-sonnet", "gpt-4o", "deepseek-r1", "gemini-2.5-flash", "gpt-4o-mini"],
    "image": ["gpt-image-1", "flux-1.1-pro", "flux-pro", "imagen-3", "gemini-2.5-flash-image", "dall-e-3", "recraft", "gemini-2.5-flash"],
    "video": ["gen4_turbo", "gen3a_turbo", "veo", "kling", "minimax", "gemini-2.5-pro", "gpt-4o"],
    "audio": ["eleven_multilingual_v2", "eleven_v3", "eleven_turbo_v2_5", "gemini-2.5-flash", "gpt-4o-mini"],
    "editing": ["gemini-2.5-flash", "gpt-4o-mini", "claude-3.5-haiku", "llama-3.3-70b", "deepseek-chat"],
}

ROLE_PREFS_FREE = {
    "director": ["deepseek-r1:free", "gemini-2.0-flash-exp:free", "llama-3.3-70b-instruct:free", "qwen", "openrouter/free", "gemini-2.5-flash", "gemini-2.0-flash", "llama-3.3-70b-versatile"],
    "image": ["gemini-2.0-flash-exp:free", "flux:free", "openrouter/free", "gemini-2.5-flash", "gemini-2.0-flash", "llama-3.3-70b-versatile"],
    "video": ["llama-3.3-70b-instruct:free", "deepseek-r1:free", "openrouter/free", "gemini-2.5-flash", "llama-3.3-70b-versatile"],
    "audio": ["gemini-2.0-flash-exp:free", "openrouter/free", "gemini-2.5-flash", "llama-3.3-70b-versatile"],
    "editing": ["llama-3.3-70b-instruct:free", "gemini-2.0-flash-exp:free", "openrouter/free", "gemini-2.5-flash", "llama-3.3-70b-versatile"],
}

# প্রতিটি প্রোভাইডারের ডিফল্ট ক্ষমতা ও টায়ার
PROVIDER_META = {
    "google": {"caps": ["TXT", "IMG", "VID", "AUD", "EDT"], "tier": "Max"},
    "openrouter": {"caps": ["TXT", "IMG", "VID", "EDT"], "tier": "Max"},
    "openai": {"caps": ["TXT", "IMG", "AUD", "EDT"], "tier": "Max"},
    "anthropic": {"caps": ["TXT", "EDT"], "tier": "High"},
    "groq": {"caps": ["TXT", "EDT"], "tier": "High"},
    "deepseek": {"caps": ["TXT", "EDT"], "tier": "High"},
    "mistral": {"caps": ["TXT", "EDT"], "tier": "Medium"},
    "runway": {"caps": ["VID", "IMG"], "tier": "Max"},
    "elevenlabs": {"caps": ["AUD"], "tier": "Max"},
    "custom": {"caps": ["TXT", "EDT"], "tier": "Medium"},
}

# ব্র্যান্ড অনুযায়ী কিউরেটেড Top-3 Free ও Top-3 Paid ফলব্যাক রেফারেন্স (লাইভ মডেলের সাথে মিলে কাজ করবে)
BRAND_TOP_REFERENCE = {
    "google": {
        "free": ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"],
        "paid": ["gemini-2.5-pro", "imagen-3.0-generate-002", "gemini-2.5-flash-image"],
    },
    "openrouter": {
        "free": ["openrouter/free", "deepseek/deepseek-r1:free", "meta-llama/llama-3.3-70b-instruct:free"],
        "paid": ["anthropic/claude-3.7-sonnet", "google/gemini-2.5-pro", "openai/gpt-4o"],
    },
    "groq": {
        "free": ["llama-3.3-70b-versatile", "deepseek-r1-distill-llama-70b", "llama-3.1-8b-instant"],
        "paid": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"],
    },
    "openai": {
        "free": [],
        "paid": ["gpt-4o", "gpt-image-1", "gpt-4o-mini"],
    },
    "anthropic": {
        "free": [],
        "paid": ["claude-3-7-sonnet-latest", "claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"],
    },
    "deepseek": {
        "free": [],
        "paid": ["deepseek-reasoner", "deepseek-chat"],
    },
    "mistral": {
        "free": ["mistral-small-latest", "open-mistral-nemo"],
        "paid": ["mistral-large-latest", "pixtral-large-latest", "codestral-latest"],
    },
    "runway": {
        "free": [],
        "paid": ["gen4_turbo", "gen3a_turbo", "gen4_image"],
    },
    "elevenlabs": {
        "free": ["eleven_flash_v2_5", "eleven_turbo_v2_5"],
        "paid": ["eleven_multilingual_v2", "eleven_v3", "eleven_turbo_v2_5"],
    },
}

# অ্যান্টি-হ্যালুসিনেশন ও প্রফেশনাল সিস্টেম স্কিল প্রম্পট
SYSTEM_SKILLS = {
    "director": (
        "You are the Lead Director AI of a professional 2D Animation & Video Production Studio. "
        "Reply in natural, clear Bengali unless asked otherwise. NEVER use raw markdown symbols like ** or ### in final text. "
        "STRICT ANTI-HALLUCINATION RULE: Never claim a video, audio, or image file has been created unless the backend actually renders it. "
        "If the user gives a story with specific characters and backgrounds and has not chosen Direct mode, briefly ask if they want to review Character Models and Background Samples first before full production. "
        "If there is an error or missing capability, explain clearly in numbered points (1, 2, 3) and suggest switching models or keys."
    ),
    "image": (
        "You are the Lead 2D Character & Scene Art Director. Design consistent character appearances, lighting, mood, "
        "and clean 2D cartoon animation compositions. Never use markdown symbols."
    ),
    "video": (
        "You are the Cinematography & Motion Director. Plan smooth camera movements, character gestures, transitions, "
        "and pacing suitable for 9:16 vertical Shorts or 16:9 widescreen. Never use markdown symbols."
    ),
    "audio": (
        "You are the Audio & Dubbing Director. Write crisp voiceover scripts in Bengali/Hindi, mark SFX cues (knock, footsteps, notification), "
        "and keep timing tight for 30-45s videos. Never use markdown symbols."
    ),
    "editing": (
        "You are the Lead Video Editor & YouTube Growth Specialist. Produce clean subtitles without markdown symbols, "
        "and generate catchy Bengali/English YouTube Titles, Descriptions, and Hashtags."
    ),
}


def cleanup_old_jobs():
    if len(JOBS) > MAX_JOBS:
        oldest_keys = list(JOBS.keys())[: len(JOBS) - MAX_JOBS]
        for k in oldest_keys:
            JOBS.pop(k, None)


def clean_text(text: str) -> str:
    """হিজিবিজি Markdown চিহ্ন (**, ###, ```) নিরাপদে পরিষ্কার করে, কিন্তু আসল লেখা মুছে ফেলে না"""
    if not text:
        return ""
    s = re.sub(r"```[a-zA-Z0-9_-]*\n?", "", text).replace("```", "")
    s = re.sub(r"\*\*(.*?)\*\*", r"\1", s)
    s = re.sub(r"__(.*?)__", r"\1", s)
    s = re.sub(r"^#{1,6}\s*", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s*\*\s+", "• ", s, flags=re.MULTILINE)
    s = s.replace("**", "").replace("###", "").strip()
    return s


def update_job_progress(
    job_id: str,
    progress: int,
    stage: str,
    agent_id: Optional[str] = None,
    agent_status: Optional[str] = None,
    agent_thought: Optional[str] = None,
    active_workers: Optional[int] = None,
    log_entry: Optional[Dict[str, str]] = None,
):
    job = JOBS.get(job_id)
    if not job:
        return
    job["progress"] = max(0, min(100, progress))
    job["stage"] = stage
    job["updated_at"] = time.time()
    if agent_id:
        st = job.setdefault("agent_states", {}).setdefault(agent_id, {})
        if agent_status is not None:
            st["status"] = agent_status
        if agent_thought is not None:
            st["thought"] = clean_text(agent_thought)[:400]
        if active_workers is not None:
            st["active_workers"] = max(0, int(active_workers))
    if log_entry:
        log_entry.setdefault("time", time.strftime("%H:%M:%S"))
        job.setdefault("team_logs", []).append(log_entry)
def _esc_xml(text: str) -> str:
    """SVG-এর ভেতর কোনো চিহ্ন যেন কোড না ভাঙে তার জন্য নিরাপদ এসকেপ"""
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def guess_provider_from_key(api_key: str, fallback: str = "google") -> str:
    k = (api_key or "").strip()
    if not k:
        return fallback
    if k.startswith("AIza"):
        return "google"
    if k.startswith("sk-or-"):
        return "openrouter"
    if k.startswith("gsk_"):
        return "groq"
    if k.startswith("sk-ant-"):
        return "anthropic"
    if k.startswith("key_"):
        return "runway"
    if k.startswith("sk_") and len(k) >= 30:
        return "elevenlabs"
    if k.startswith("sk-"):
        return "openai"
    return fallback or "openrouter"


def is_free_model_name(model_id: str, provider: str) -> bool:
    low = (model_id or "").lower()
    if ":free" in low or low == "openrouter/free" or "/free" in low:
        return True
    if provider == "groq":
        return True
    if provider == "google" and ("flash" in low and "pro" not in low):
        return True
    if provider == "mistral" and ("small" in low or "nemo" in low):
        return True
    return False


def classify_brand_models(models: List[str], provider: str) -> Dict[str, List[str]]:
    """প্রতিটি ব্র্যান্ডের জন্য সেরা ৩টি Free ও সেরা ৩টি Paid মডেল বের করে (Info Bar ছকের জন্য)"""
    ref = BRAND_TOP_REFERENCE.get(provider, {"free": [], "paid": []})
    if not models:
        return {"top_free": ref["free"][:3], "top_paid": ref["paid"][:3]}

    free_pool: List[str] = []
    paid_pool: List[str] = []

    # আগে কিউরেটেড সেরা মডেলগুলো লাইভ লিস্টের সাথে মিলিয়ে অগ্রাধিকার দেওয়া
    lower_lookup = {m.lower(): m for m in models}
    for r in ref["free"]:
        if r.lower() in lower_lookup and lower_lookup[r.lower()] not in free_pool:
            free_pool.append(lower_lookup[r.lower()])
    for r in ref["paid"]:
        if r.lower() in lower_lookup and lower_lookup[r.lower()] not in paid_pool:
            paid_pool.append(lower_lookup[r.lower()])

    # বাকি লাইভ মডেলগুলো থেকে শক্তিশালী কিওয়ার্ড অনুযায়ী পূরণ করা
    power_keywords = ["2.5-pro", "claude-3.7", "claude-3.5", "gpt-4o", "deepseek-r1", "llama-3.3-70b", "gemini-2.5-flash", "gen4", "flux", "imagen", "multilingual_v2"]
    for kw in power_keywords:
        for m in models:
            if kw in m.lower():
                if is_free_model_name(m, provider):
                    if m not in free_pool:
                        free_pool.append(m)
                else:
                    if m not in paid_pool:
                        paid_pool.append(m)

    # তবুও ৩টির কম হলে বাকি মডেল থেকে নেওয়া
    for m in models:
        if is_free_model_name(m, provider):
            if len(free_pool) < 3 and m not in free_pool:
                free_pool.append(m)
        else:
            if len(paid_pool) < 3 and m not in paid_pool:
                paid_pool.append(m)

    return {
        "top_free": (free_pool or ref["free"])[:3],
        "top_paid": (paid_pool or ref["paid"])[:3],
    }


def pick_best_model(
    models: List[str],
    agent_id: str,
    provider: str,
    mode: str = "paid",
    cycle_index: int = 0,
) -> str:
    """Paid ⇄ Free টগল এবং প্রতিবার চাপলে নতুন ভার্সন রোটেশন (রিপিটসহ)"""
    defaults_paid = {
        "google": "gemini-2.5-pro" if agent_id == "director" else "gemini-2.5-flash",
        "openrouter": "anthropic/claude-3.5-sonnet",
        "groq": "llama-3.3-70b-versatile",
        "openai": "gpt-4o" if agent_id == "director" else "gpt-4o-mini",
        "anthropic": "claude-3-5-sonnet-latest",
        "deepseek": "deepseek-chat",
        "mistral": "mistral-large-latest",
        "elevenlabs": "eleven_multilingual_v2",
        "runway": "gen4_turbo",
    }
    defaults_free = {
        "google": "gemini-2.5-flash",
        "openrouter": "openrouter/free",
        "groq": "llama-3.3-70b-versatile",
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-5-haiku-latest",
        "deepseek": "deepseek-chat",
        "mistral": "mistral-small-latest",
        "elevenlabs": "eleven_flash_v2_5",
        "runway": "gen3a_turbo",
    }

    if not models:
        return defaults_free.get(provider, "openrouter/free") if mode == "free" else defaults_paid.get(provider, "gemini-2.5-flash")

    prefs = (ROLE_PREFS_FREE if mode == "free" else ROLE_PREFS_PAID).get(agent_id, ROLE_PREFS_PAID["director"])
    lower_map = [(m, m.lower()) for m in models]

    matched: List[str] = []
    for pref in prefs:
        for orig, low in lower_map:
            if pref in low and orig not in matched:
                if mode == "free" and provider == "openrouter" and not is_free_model_name(orig, provider):
                    continue
                matched.append(orig)

    if mode == "free":
        for orig, _ in lower_map:
            if is_free_model_name(orig, provider) and orig not in matched:
                matched.append(orig)
    else:
        for orig, _ in lower_map:
            if not is_free_model_name(orig, provider) and orig not in matched:
                matched.append(orig)

    pool = matched if matched else models
    idx = abs(int(cycle_index)) % len(pool)
    return pool[idx]


async def fetch_provider_models(
    client: httpx.AsyncClient, provider: str, api_key: str, custom_url: str = ""
) -> Dict[str, Any]:
    try:
        if provider == "google":
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            r = await client.get(url, timeout=14)
            if r.status_code != 200:
                return {"ok": False, "error": f"Google API ({r.status_code}): {r.text[:220]}", "models": []}
            data = r.json()
            models = [
                m["name"].replace("models/", "")
                for m in data.get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])
                or "predict" in m.get("supportedGenerationMethods", [])
            ]
            return {"ok": True, "models": models}

        if provider == "elevenlabs":
            r = await client.get(
                "https://api.elevenlabs.io/v1/models",
                headers={"xi-api-key": api_key},
                timeout=14,
            )
            if r.status_code != 200:
                return {"ok": False, "error": f"ElevenLabs ({r.status_code}): {r.text[:220]}", "models": []}
            data = r.json()
            models = [m.get("model_id") for m in data if isinstance(m, dict) and m.get("model_id")]
            return {"ok": True, "models": models}

        if provider == "anthropic":
            r = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                timeout=14,
            )
            if r.status_code != 200:
                return {"ok": False, "error": f"Anthropic ({r.status_code}): {r.text[:220]}", "models": []}
            models = [m["id"] for m in r.json().get("data", []) if isinstance(m, dict) and "id" in m]
            return {"ok": True, "models": models}

        if provider == "runway":
            # Runway অফিশিয়াল কি ভেরিফিকেশন
            r = await client.get(
                "https://api.dev.runwayml.com/v1/organization",
                headers={"Authorization": f"Bearer {api_key}", "X-Runway-Version": "2024-11-06"},
                timeout=12,
            )
            if r.status_code in (401, 403):
                return {"ok": False, "error": f"Runway Key অবৈধ বা অনুমোদিত নয় ({r.status_code})", "models": []}
            return {"ok": True, "models": ["gen4_turbo", "gen3a_turbo", "gen4_image"]}

        base_urls = {
            "openrouter": "https://openrouter.ai/api/v1/models",
            "groq": "https://api.groq.com/openai/v1/models",
            "openai": "https://api.openai.com/v1/models",
            "deepseek": "https://api.deepseek.com/models",
            "mistral": "https://api.mistral.ai/v1/models",
        }
        url = base_urls.get(provider)
        if provider == "custom" and custom_url:
            base = custom_url.rstrip("/")
            if base.endswith("/chat/completions"):
                base = base.replace("/chat/completions", "")
            url = f"{base}/models"

        if not url:
            return {"ok": False, "error": "Custom Endpoint URL দেওয়া হয়নি।", "models": []}

        headers = {"Authorization": f"Bearer {api_key}"}
        r = await client.get(url, headers=headers, timeout=14)
        if r.status_code != 200:
            return {"ok": False, "error": f"{provider.upper()} ({r.status_code}): {r.text[:220]}", "models": []}

        data = r.json()
        raw_list = data.get("data", []) if isinstance(data, dict) else []
        models = [m["id"] for m in raw_list if isinstance(m, dict) and "id" in m]
        if provider == "openrouter" and "openrouter/free" not in models:
            models.insert(0, "openrouter/free")
        return {"ok": True, "models": models}

    except Exception as e:
        return {"ok": False, "error": str(e), "models": []}


async def call_llm_single_key(
    client: httpx.AsyncClient,
    provider: str,
    model: str,
    api_key: str,
    prompt: str,
    system_prompt: str = "",
    history: Optional[List[Dict[str, str]]] = None,
    custom_url: str = "",
) -> Dict[str, Any]:
    history = history or []
    model = (model or "").strip() or pick_best_model([], "director", provider, "free")

    try:
        # ডেডিকেটেড মিডিয়া প্রোভাইডার কখনোই ভুয়া চ্যাট উত্তর দেবে না
        if provider == "elevenlabs":
            return {"ok": False, "error": "ElevenLabs শুধু অডিও/ভয়েস/ডাবিং ইঞ্জিন—টেক্সট প্ল্যানিংয়ের জন্য টেক্সট AI Key দরকার।", "media_only": True}

        if provider == "runway":
            return {"ok": False, "error": "Runway শুধু ভিডিও/ইমেজ রেন্ডার ইঞ্জিন—টেক্সট প্ল্যানিংয়ের জন্য টেক্সট AI Key দরকার।", "media_only": True}

        if provider == "google":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            contents = []
            for h in history[-8:]:
                role = "user" if h.get("role") == "user" else "model"
                txt = (h.get("content") or "").strip()
                if txt:
                    contents.append({"role": role, "parts": [{"text": txt}]})
            contents.append({"role": "user", "parts": [{"text": prompt}]})
            payload: Dict[str, Any] = {"contents": contents}
            if system_prompt:
                payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

            r = await client.post(url, json=payload, timeout=40)
            if r.status_code != 200:
                return {"ok": False, "error": f"Google ({r.status_code}): {r.text[:260]}", "status_code": r.status_code}
            data = r.json()
            candidates = data.get("candidates") or []
            if not candidates:
                return {"ok": False, "error": "Google থেকে কোনো উত্তর পাওয়া যায়নি (Safety/Empty)।"}
            parts = candidates[0].get("content", {}).get("parts") or []
            text = "\n".join(p.get("text", "") for p in parts if p.get("text")).strip()
            if not text:
                return {"ok": False, "error": "Google ফাঁকা উত্তর দিয়েছে।"}
            return {"ok": True, "text": clean_text(text), "raw_text": text, "provider": provider, "model": model}

        if provider == "anthropic":
            url = "https://api.anthropic.com/v1/messages"
            msgs = [{"role": h.get("role", "user"), "content": h.get("content", "")} for h in history[-8:] if h.get("content")]
            msgs.append({"role": "user", "content": prompt})
            payload = {"model": model, "max_tokens": 1800, "system": system_prompt, "messages": msgs}
            r = await client.post(
                url,
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                json=payload,
                timeout=40,
            )
            if r.status_code != 200:
                return {"ok": False, "error": f"Anthropic ({r.status_code}): {r.text[:260]}", "status_code": r.status_code}
            content_list = r.json().get("content") or []
            text = content_list[0].get("text", "") if content_list else ""
            return {"ok": True, "text": clean_text(text), "raw_text": text, "provider": provider, "model": model}

        chat_urls = {
            "openrouter": "https://openrouter.ai/api/v1/chat/completions",
            "groq": "https://api.groq.com/openai/v1/chat/completions",
            "openai": "https://api.openai.com/v1/chat/completions",
            "deepseek": "https://api.deepseek.com/chat/completions",
            "mistral": "https://api.mistral.ai/v1/chat/completions",
        }
        url = chat_urls.get(provider)
        if provider == "custom" and custom_url:
            url = custom_url if "chat/completions" in custom_url else custom_url.rstrip("/") + "/chat/completions"

        if not url:
            return {"ok": False, "error": "Custom Endpoint URL দেওয়া হয়নি।"}

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for h in history[-8:]:
            if h.get("content"):
                messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        messages.append({"role": "user", "content": prompt})

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://ai-video-studio.onrender.com"
            headers["X-Title"] = "AI Production Studio V3"

        r = await client.post(url, headers=headers, json={"model": model, "messages": messages}, timeout=40)
        if r.status_code != 200:
            return {"ok": False, "error": f"{provider.upper()} ({r.status_code}): {r.text[:260]}", "status_code": r.status_code}
        choices = r.json().get("choices") or []
        text = choices[0].get("message", {}).get("content", "") if choices else ""
        if not text:
            return {"ok": False, "error": f"{provider.upper()} ফাঁকা উত্তর দিয়েছে।"}
        return {"ok": True, "text": clean_text(text), "raw_text": text, "provider": provider, "model": model}

    except Exception as e:
        return {"ok": False, "error": str(e)}


async def call_agent_with_fallbacks(
    client: httpx.AsyncClient,
    config: Dict[str, Any],
    prompt: str,
    system_prompt: str = "",
    history: Optional[List[Dict[str, str]]] = None,
    co_work: bool = False,
    job_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Primary → Secondary স্মার্ট ফলব্যাক, ডাইনামিক Primary প্রোমোশন এবং Co-Work মাল্টি-ব্লু LED সাপোর্ট"""
    keys_cfg = config.get("keys", [])
    custom_url = config.get("customUrl", "")

    candidates = []
    for idx, slot in enumerate(keys_cfg):
        prov = slot.get("provider", "google")
        mod = slot.get("model", "")
        main_k = (slot.get("apiKey") or "").strip()
        sub_k = (slot.get("subKey") or "").strip()
        if main_k:
            candidates.append((idx, prov, mod, main_k))
        if sub_k:
            candidates.append((idx, prov, mod, sub_k))

    if not candidates:
        return {"ok": False, "error": "কোনো API Key দেওয়া নেই।"}

    # Co-Work মোডে একসাথে ২-৩টি Key সমান্তরালভাবে কাজ করবে (যতগুলো কাজ করবে ততগুলো ব্লু LED)
    if co_work and len(candidates) > 1:
        active_batch = candidates[:3]
        if job_id and agent_id:
            update_job_progress(job_id, JOBS.get(job_id, {}).get("progress", 20), f"{agent_id.upper()} Co-Work ({len(active_batch)} AI active)...", agent_id, "working", active_workers=len(active_batch))
        tasks = [
            call_llm_single_key(client, p, m, k, prompt, system_prompt, history, custom_url)
            for (_, p, m, k) in active_batch
        ]
        results = await asyncio.gather(*tasks)
        ok_items = [(active_batch[i][0], r) for i, r in enumerate(results) if r.get("ok")]
        if not ok_items:
            return results[0]
        primary_slot_idx, first_ok = ok_items[0]
        extras = [{"worker": i + 2, "slot_index": s_idx, "text": r["text"], "model": r.get("model", "")} for i, (s_idx, r) in enumerate(ok_items[1:])]
        first_ok["extras"] = extras
        first_ok["used_slot_index"] = primary_slot_idx
        first_ok["promoted_primary"] = primary_slot_idx > 0
        first_ok["active_workers_used"] = len(ok_items)
        return first_ok

    last_err = "Unknown Error"
    for slot_idx, prov, mod, k in candidates:
        if job_id and agent_id:
            update_job_progress(job_id, JOBS.get(job_id, {}).get("progress", 20), f"{agent_id.upper()} working ({prov})...", agent_id, "working", active_workers=1)
        res = await call_llm_single_key(client, prov, mod, k, prompt, system_prompt, history, custom_url)
        if res.get("ok"):
            res["used_slot_index"] = slot_idx
            res["promoted_primary"] = slot_idx > 0
            res["active_workers_used"] = 1
            return res
        # OpenRouter 402 (ক্রেডিট শেষ) হলে সাথে সাথে ফ্রি মডেলে অটো-সেলফ-হিলিং চেষ্টা
        if prov == "openrouter" and res.get("status_code") == 402 and mod != "openrouter/free":
            free_res = await call_llm_single_key(client, prov, "openrouter/free", k, prompt, system_prompt, history, custom_url)
            if free_res.get("ok"):
                free_res["used_slot_index"] = slot_idx
                free_res["promoted_primary"] = slot_idx > 0
                free_res["auto_recovered_free"] = True
                free_res["active_workers_used"] = 1
                return free_res
        last_err = res.get("error", "Failed")
    return {"ok": False, "error": last_err}


def build_2d_cartoon_svg(
    title: str,
    visual_desc: str,
    scene_num: int = 1,
    aspect: str = "9:16",
    is_character_sheet: bool = False,
) -> str:
    """ফ্রি বা অফলাইন মোডেও খালি নীল স্ক্রিন নয়—সত্যিকারের 2D কার্টুন দৃশ্য/ক্যারেক্টার ভেক্টর আর্ট তৈরি করে"""
    w, h = (1080, 1920) if aspect == "9:16" else (1920, 1080)
    desc_low = (visual_desc + " " + title).lower()
    is_night = any(k in desc_low for k in ["night", "dark", "রাত", "অন্ধকার", "shadow", "ছায়া", "mystery", "রহস্য"])
    has_shadow = any(k in desc_low for k in ["shadow", "ছায়া", "silhouette", "অজানা"])
    has_phone = any(k in desc_low for k in ["phone", "message", "ফোন", "মেসেজ"])
    has_door = any(k in desc_low for k in ["door", "knock", "দরজা", "টোকা"])

    bg1, bg2 = ("#090d24", "#241345") if is_night else ("#1a365d", "#2c5282")
    accent = "#7c3aed" if is_night else "#38bdf8"
    cx, cy = w // 2, int(h * 0.54)
    scale = 1.15 if aspect == "9:16" else 0.9

    extra_props = ""
    if has_door:
        dx = int(w * 0.72)
        dy = int(h * 0.28)
        extra_props += f'''
        <rect x="{dx}" y="{dy}" width="210" height="460" rx="8" fill="#1e1b4b" stroke="#6366f1" stroke-width="5"/>
        <circle cx="{dx + 32}" cy="{dy + 240}" r="11" fill="#fbbf24"/>
        <path d="M{dx-25} {dy+120} L{dx-55} {dy+100} M{dx-25} {dy+150} L{dx-60} {dy+150}" stroke="#f59e0b" stroke-width="6" stroke-linecap="round"/>
        '''
    if has_phone:
        px, py = int(w * 0.14), int(h * 0.30)
        extra_props += f'''
        <rect x="{px}" y="{py}" width="210" height="330" rx="24" fill="#0f172a" stroke="#38bdf8" stroke-width="6"/>
        <rect x="{px+16}" y="{py+34}" width="178" height="240" rx="10" fill="#1e293b"/>
        <rect x="{px+28}" y="{py+70}" width="154" height="54" rx="12" fill="#2563eb"/>
        <circle cx="{px+105}" cy="{py+298}" r="10" fill="#38bdf8"/>
        '''

    shadow_svg = ""
    if has_shadow or is_character_sheet:
        sx = int(w * 0.64) if not is_character_sheet else int(w * 0.68)
        sy = cy - 40
        shadow_svg = f'''
        <g transform="translate({sx},{sy}) scale({scale})" opacity="0.92">
          <ellipse cx="0" cy="270" rx="85" ry="22" fill="#000000" opacity="0.6"/>
          <path d="M-55,250 L-45,50 Q-55,-30 0,-45 Q55,-30 45,50 L55,250 Z" fill="#05050a" stroke="#a855f7" stroke-width="4"/>
          <circle cx="0" cy="-95" r="52" fill="#05050a" stroke="#a855f7" stroke-width="4"/>
          <ellipse cx="-18" cy="-98" rx="9" ry="5" fill="#e879f9"/>
          <ellipse cx="18" cy="-98" rx="9" ry="5" fill="#e879f9"/>
          <path d="M-48,40 Q-115,-10 -125,-85" fill="none" stroke="#05050a" stroke-width="26" stroke-linecap="round"/>
          <path d="M48,40 Q105,80 110,135" fill="none" stroke="#05050a" stroke-width="24" stroke-linecap="round"/>
        </g>
        '''

    hero_x = int(w * 0.34) if (has_shadow or is_character_sheet) else cx
    label_txt = _esc_xml(title[:46])
    sub_txt = _esc_xml(visual_desc[:84])

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">
      <defs>
        <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="{bg1}"/>
          <stop offset="100%" stop-color="{bg2}"/>
        </linearGradient>
        <radialGradient id="glow" cx="50%" cy="35%" r="55%">
          <stop offset="0%" stop-color="{accent}" stop-opacity="0.35"/>
          <stop offset="100%" stop-color="{bg1}" stop-opacity="0"/>
        </radialGradient>
      </defs>
      <rect width="{w}" height="{h}" fill="url(#bg)"/>
      <rect width="{w}" height="{h}" fill="url(#glow)"/>
      <circle cx="{int(w*0.82)}" cy="{int(h*0.14)}" r="72" fill="#e0e7ff" opacity="0.18"/>
      <rect x="0" y="{int(h*0.74)}" width="{w}" height="{int(h*0.26)}" fill="#0b1026" opacity="0.88"/>
      <line x1="0" y1="{int(h*0.74)}" x2="{w}" y2="{int(h*0.74)}" stroke="{accent}" stroke-width="3" opacity="0.5"/>
      {extra_props}
      {shadow_svg}
      <g transform="translate({hero_x},{cy}) scale({scale})">
        <ellipse cx="0" cy="270" rx="80" ry="20" fill="#000000" opacity="0.55"/>
        <rect x="-42" y="135" width="32" height="125" rx="14" fill="#1e293b"/>
        <rect x="10" y="135" width="32" height="125" rx="14" fill="#1e293b"/>
        <path d="M-65,145 L-54,15 Q-52,-25 0,-30 Q52,-25 54,15 L65,145 Z" fill="#2563eb" stroke="#60a5fa" stroke-width="4"/>
        <path d="M-28,-22 Q0,18 28,-22" fill="none" stroke="#93c5fd" stroke-width="5"/>
        <circle cx="0" cy="-88" r="54" fill="#fed7aa" stroke="#0f172a" stroke-width="4"/>
        <path d="M-56,-92 Q-52,-152 0,-152 Q52,-152 56,-92 Q25,-118 -56,-92 Z" fill="#0f172a"/>
        <circle cx="-18" cy="-88" r="7" fill="#0f172a"/>
        <circle cx="18" cy="-88" r="7" fill="#0f172a"/>
        <circle cx="-16" cy="-90" r="2.5" fill="#ffffff"/>
        <circle cx="20" cy="-90" r="2.5" fill="#ffffff"/>
        <ellipse cx="0" cy="-60" rx="10" ry="12" fill="#7c2d12"/>
        <path d="M-54,28 Q-105,65 -92,125" fill="none" stroke="#2563eb" stroke-width="24" stroke-linecap="round"/>
        <path d="M54,28 Q112,-15 118,-70" fill="none" stroke="#2563eb" stroke-width="24" stroke-linecap="round"/>
      </g>
      <rect x="44" y="44" width="230" height="54" rx="27" fill="#0f172a" opacity="0.82" stroke="{accent}" stroke-width="2"/>
      <text x="159" y="79" text-anchor="middle" fill="#e2e8f0" font-family="sans-serif" font-size="24" font-weight="bold">SCENE {scene_num}</text>
      <rect x="40" y="{h - 190}" width="{w - 80}" height="140" rx="22" fill="#020617" opacity="0.78" stroke="#334155" stroke-width="2"/>
      <text x="{w // 2}" y="{h - 125}" text-anchor="middle" fill="#f8fafc" font-family="sans-serif" font-size="30" font-weight="bold">{label_txt}</text>
      <text x="{w // 2}" y="{h - 78}" text-anchor="middle" fill="#94a3b8" font-family="sans-serif" font-size="22">{sub_txt}</text>
    </svg>'''
    b64 = base64.b64encode(svg.encode("utf-8")).decode("utf-8")
    return f"data:image/svg+xml;base64,{b64}"


async def generate_real_image(
    client: httpx.AsyncClient,
    image_config: Dict[str, Any],
    prompt: str,
    scene_title: str = "Scene",
    scene_num: int = 1,
    aspect: str = "9:16",
    is_character_sheet: bool = False,
) -> Dict[str, Any]:
    """আসল AI ইমেজ (OpenAI / Google / OpenRouter) তৈরি করে; না পারলে ফ্রি 2D ভেক্টর সিন আর্ট দেয় (কোনো ভুয়া দাবি ছাড়া)"""
    keys_cfg = image_config.get("keys", [])
    size_openai = "1024x1536" if aspect == "9:16" else "1536x1024"

    for slot_idx, slot in enumerate(keys_cfg):
        prov = slot.get("provider", "")
        mod = (slot.get("model") or "").strip()
        api_key = (slot.get("apiKey") or "").strip()
        if not api_key:
            continue

        try:
            # ১. OpenAI Image API
            if prov == "openai" and any(k in mod.lower() for k in ["image", "dall-e"]):
                payload: Dict[str, Any] = {"model": mod, "prompt": prompt[:1000], "size": size_openai if "gpt-image" in mod else "1024x1024"}
                if "dall-e" in mod.lower():
                    payload["response_format"] = "b64_json"
                r = await client.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=55,
                )
                if r.status_code == 200:
                    d = r.json().get("data", [{}])[0]
                    if d.get("b64_json"):
                        return {"ok": True, "image_data": f"data:image/png;base64,{d['b64_json']}", "source": f"openai:{mod}", "used_slot_index": slot_idx}
                    if d.get("url"):
                        return {"ok": True, "image_data": d["url"], "source": f"openai:{mod}", "used_slot_index": slot_idx}

            # ২. Google Gemini Native Image Generation
            if prov == "google" and any(k in mod.lower() for k in ["image", "gemini-2.0-flash-exp"]):
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent?key={api_key}"
                payload = {
                    "contents": [{"parts": [{"text": f"Create a clean 2D cartoon animation frame ({aspect}): {prompt[:900]}"}]}],
                    "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
                }
                r = await client.post(url, json=payload, timeout=55)
                if r.status_code == 200:
                    parts = (r.json().get("candidates") or [{}])[0].get("content", {}).get("parts") or []
                    for p in parts:
                        inline = p.get("inlineData") or p.get("inline_data")
                        if inline and inline.get("data"):
                            mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                            return {"ok": True, "image_data": f"data:{mime};base64,{inline['data']}", "source": f"google:{mod}", "used_slot_index": slot_idx}

            # ৩. OpenRouter Image Modalities
            if prov == "openrouter" and any(k in mod.lower() for k in ["flux", "image", "gemini-2.5-flash-image"]):
                r = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": mod, "messages": [{"role": "user", "content": prompt[:900]}], "modalities": ["image", "text"]},
                    timeout=55,
                )
                if r.status_code == 200:
                    msg = (r.json().get("choices") or [{}])[0].get("message", {})
                    imgs = msg.get("images") or []
                    if imgs:
                        img_url = imgs[0].get("image_url", {}).get("url") or imgs[0].get("url")
                        if img_url:
                            return {"ok": True, "image_data": img_url, "source": f"openrouter:{mod}", "used_slot_index": slot_idx}
        except Exception:
            continue

    # কোনো পেইড ইমেজ API না থাকলে স্পষ্ট লেবেলসহ 2D ভেক্টর কার্টুন সিন তৈরি
    svg_data = build_2d_cartoon_svg(scene_title, prompt, scene_num=scene_num, aspect=aspect, is_character_sheet=is_character_sheet)
    return {"ok": True, "image_data": svg_data, "source": "2d_vector_studio", "used_slot_index": 0}


async def generate_runway_video(
    client: httpx.AsyncClient,
    api_key: str,
    prompt: str,
    model: str = "gen4_turbo",
    aspect: str = "9:16",
    prompt_image: Optional[str] = None,
) -> Dict[str, Any]:
    """Runway অফিশিয়াল API দিয়ে সত্যিকারের ভিডিও ক্লিপ রেন্ডার করে (কোনো ডামি মেসেজ নয়)"""
    if not api_key:
        return {"ok": False, "error": "Runway API Key নেই।"}
    ratio = "720:1280" if aspect == "9:16" else "1280:720"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Runway-Version": "2024-11-06",
        "Content-Type": "application/json",
    }
    try:
        endpoint = "https://api.dev.runwayml.com/v1/image_to_video" if prompt_image else "https://api.dev.runwayml.com/v1/text_to_video"
        payload: Dict[str, Any] = {
            "model": model if model in ("gen4_turbo", "gen3a_turbo") else "gen4_turbo",
            "promptText": prompt[:950],
            "ratio": ratio,
            "duration": 5,
        }
        if prompt_image:
            payload["promptImage"] = prompt_image

        r = await client.post(endpoint, headers=headers, json=payload, timeout=25)
        if r.status_code not in (200, 201):
            return {"ok": False, "error": f"Runway API ({r.status_code}): {r.text[:240]}"}
        task_id = r.json().get("id")
        if not task_id:
            return {"ok": False, "error": "Runway Task ID পাওয়া যায়নি।"}

        # সর্বোচ্চ ৯০ সেকেন্ড পর্যন্ত রেন্ডার স্ট্যাটাস পোলিং
        for _ in range(30):
            await asyncio.sleep(3)
            chk = await client.get(f"https://api.dev.runwayml.com/v1/tasks/{task_id}", headers=headers, timeout=15)
            if chk.status_code != 200:
                continue
            tdata = chk.json()
            status = tdata.get("status", "")
            if status == "SUCCEEDED":
                outputs = tdata.get("output") or []
                if outputs:
                    return {"ok": True, "video_url": outputs[0], "task_id": task_id}
                return {"ok": False, "error": "Runway ভিডিও URL ফাঁকা এসেছে।"}
            if status in ("FAILED", "CANCELLED"):
                return {"ok": False, "error": f"Runway রেন্ডার ব্যর্থ: {tdata.get('failure', status)}"}
        return {"ok": False, "error": "Runway রেন্ডার টাইমআউট হয়েছে (৯০ সেকেন্ডের বেশি সময় লাগছে)।"}
    except Exception as e:
        return {"ok": False, "error": f"Runway ত্রুটি: {str(e)}"}
async def generate_elevenlabs_audio(
    client: httpx.AsyncClient,
    api_key: str,
    text: str,
    model: str = "eleven_multilingual_v2",
    voice_id: str = "21m00Tcm4TlvDq8ikWAM",
) -> Dict[str, Any]:
    """ElevenLabs দিয়ে আসল বাংলা/হিন্দি/ইংরেজি ভয়েসওভার (.mp3) তৈরি করে"""
    if not api_key or not text.strip():
        return {"ok": False, "error": "ElevenLabs Key বা স্ক্রিপ্ট ফাঁকা।"}
    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text[:2500],
            "model_id": model or "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.48, "similarity_boost": 0.78},
        }
        r = await client.post(url, headers=headers, json=payload, timeout=45)
        if r.status_code != 200:
            return {"ok": False, "error": f"ElevenLabs ({r.status_code}): {r.text[:220]}"}
        b64 = base64.b64encode(r.content).decode("utf-8")
        return {"ok": True, "audio_data": f"data:audio/mpeg;base64,{b64}", "source": f"elevenlabs:{model}"}
    except Exception as e:
        return {"ok": False, "error": f"ElevenLabs ত্রুটি: {str(e)}"}


async def generate_elevenlabs_sfx(
    client: httpx.AsyncClient,
    api_key: str,
    sfx_prompt: str,
    duration_seconds: float = 3.0,
) -> Dict[str, Any]:
    """ElevenLabs Sound Effects (দরজায় টোকা, পায়ের শব্দ, নোটিফিকেশন) তৈরি করে"""
    if not api_key or not sfx_prompt.strip():
        return {"ok": False, "error": "SFX তৈরি করার মতো তথ্য নেই।"}
    try:
        r = await client.post(
            "https://api.elevenlabs.io/v1/sound-generation",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json={"text": sfx_prompt[:300], "duration_seconds": max(1.0, min(10.0, duration_seconds))},
            timeout=35,
        )
        if r.status_code != 200:
            return {"ok": False, "error": f"ElevenLabs SFX ({r.status_code}): {r.text[:200]}"}
        b64 = base64.b64encode(r.content).decode("utf-8")
        return {"ok": True, "audio_data": f"data:audio/mpeg;base64,{b64}", "source": "elevenlabs:sfx"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def extract_youtube_info(client: httpx.AsyncClient, text: str) -> Optional[Dict[str, str]]:
    """মেসেজে YouTube লিংক থাকলে আসল টাইটেল, চ্যানেল ও থাম্বনেল স্ক্যান করে"""
    m = re.search(r"(https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)[^\s]+)", text or "")
    if not m:
        return None
    yt_url = m.group(1)
    try:
        oembed = f"https://www.youtube.com/oembed?url={urllib.parse.quote(yt_url, safe='')}&format=json"
        r = await client.get(oembed, timeout=10)
        if r.status_code == 200:
            d = r.json()
            return {
                "url": yt_url,
                "title": d.get("title", "YouTube Video"),
                "author": d.get("author_name", "Unknown Channel"),
                "thumbnail": d.get("thumbnail_url", ""),
            }
    except Exception:
        pass
    return {"url": yt_url, "title": "YouTube Link Detected", "author": "", "thumbnail": ""}


def safe_extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    s = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(s[start : end + 1])
    except Exception:
        return None


def _find_provider_key(agent_cfg: Dict[str, Any], target_provider: str) -> Optional[Dict[str, str]]:
    for slot in agent_cfg.get("keys", []):
        if slot.get("provider") == target_provider and (slot.get("apiKey") or "").strip():
            return {"apiKey": slot["apiKey"].strip(), "model": (slot.get("model") or "").strip()}
    return None


@app.get("/")
async def serve_index():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return JSONResponse({"ok": True, "message": "AI Production Studio V3 Backend Running"})


@app.get("/api/health")
async def health_check():
    return {"ok": True, "status": "online", "active_jobs": len(JOBS)}


@app.post("/api/detect-models")
async def api_detect_models(request: Request):
    """Paid ⇄ Free টগল, আসল মডেল লিস্ট এবং ব্র্যান্ড অনুযায়ী Top-3 Free ও Top-3 Paid ছক দেয়"""
    body = await request.json()
    api_key = (body.get("apiKey") or "").strip()
    provider = (body.get("provider") or "auto").strip().lower()
    agent_id = (body.get("agentId") or "director").strip().lower()
    mode = (body.get("mode") or "paid").strip().lower()
    cycle_index = int(body.get("cycleIndex") or 0)
    custom_url = (body.get("customUrl") or "").strip()

    if not api_key:
        return JSONResponse({"ok": False, "error": "API Key দেওয়া হয়নি।"}, status_code=400)

    if provider in ("", "auto"):
        provider = guess_provider_from_key(api_key)

    async with httpx.AsyncClient() as client:
        res = await fetch_provider_models(client, provider, api_key, custom_url)

    models = res.get("models", [])
    best_model = pick_best_model(models, agent_id, provider, mode=mode, cycle_index=cycle_index)
    brand_top = classify_brand_models(models, provider)
    meta = PROVIDER_META.get(provider, PROVIDER_META["custom"])

    if not res.get("ok"):
        return {
            "ok": False,
            "provider": provider,
            "error": res.get("error", "API Key যাচাই ব্যর্থ হয়েছে।"),
            "models": models,
            "best_model": best_model,
            "top_free": brand_top["top_free"],
            "top_paid": brand_top["top_paid"],
            "caps": meta["caps"],
            "tier": meta["tier"],
            "mode": mode,
        }

    return {
        "ok": True,
        "provider": provider,
        "models": models,
        "model_count": len(models),
        "best_model": best_model,
        "top_free": brand_top["top_free"],
        "top_paid": brand_top["top_paid"],
        "caps": meta["caps"],
        "tier": meta["tier"],
        "mode": mode,
    }


@app.post("/api/team-health")
async def api_team_health(request: Request):
    """এক ক্লিকে ৫ জন এজেন্টের সব API Key পরীক্ষা করে লাইভ সবুজ/লাল রিপোর্ট দেয়"""
    body = await request.json()
    agents = body.get("agents") or {}
    report: Dict[str, Any] = {}

    async def check_one(agent_id: str, cfg: Dict[str, Any]):
        slots = cfg.get("keys", [])
        if not slots or not any((s.get("apiKey") or "").strip() for s in slots):
            return agent_id, {"ok": False, "status": "empty", "detail": "কোনো API Key নেই"}
        async with httpx.AsyncClient() as client:
            slot_results = []
            for idx, s in enumerate(slots):
                k = (s.get("apiKey") or "").strip()
                if not k:
                    continue
                prov = s.get("provider") or guess_provider_from_key(k)
                r = await fetch_provider_models(client, prov, k, cfg.get("customUrl", ""))
                slot_results.append({"slot": idx, "provider": prov, "ok": r.get("ok", False), "error": r.get("error", "")})
            active_slots = [x for x in slot_results if x["ok"]]
            if active_slots:
                promoted = active_slots[0]["slot"] > 0
                return agent_id, {
                    "ok": True,
                    "status": "ready",
                    "active_slot": active_slots[0]["slot"],
                    "promoted_primary": promoted,
                    "detail": f"{len(active_slots)}/{len(slot_results)} Key সচল",
                }
            return agent_id, {"ok": False, "status": "error", "detail": slot_results[0]["error"] if slot_results else "ত্রুটি"}

    tasks = [check_one(aid, agents.get(aid, {})) for aid in ["director", "image", "video", "audio", "editing"]]
    for aid, res in await asyncio.gather(*tasks):
        report[aid] = res

    ready_count = sum(1 for v in report.values() if v.get("ok"))
    return {"ok": True, "ready_count": ready_count, "total": 5, "report": report}


@app.post("/api/chat")
async def api_chat(request: Request):
    """Director AI চ্যাট, YouTube লিংক স্ক্যান, Co-Director Option A/B এবং পয়েন্ট-আকারে ডায়াগনস্টিক"""
    body = await request.json()
    message = (body.get("message") or "").strip()
    agent_id = (body.get("agentId") or "director").strip().lower()
    agents = body.get("agents") or {}
    history = body.get("history") or []
    co_director = bool(body.get("coDirector", False))
    co_work = bool(body.get("coWork", False))
    direct_mode = bool(body.get("directMode", False))
    is_diagnostic = bool(body.get("isDiagnostic", False))

    if not message:
        return JSONResponse({"ok": False, "error": "মেসেজ ফাঁকা।"}, status_code=400)

    agent_cfg = agents.get(agent_id) or agents.get("director") or {}
    sys_prompt = SYSTEM_SKILLS.get(agent_id, SYSTEM_SKILLS["director"])

    async with httpx.AsyncClient() as client:
        yt_info = await extract_youtube_info(client, message)
        enriched_prompt = message
        if yt_info:
            enriched_prompt += f"\n\n[Scanned YouTube Video: Title='{yt_info['title']}', Channel='{yt_info['author']}', URL='{yt_info['url']}']"

        if is_diagnostic:
            enriched_prompt = (
                f"স্টুডিওতে নিচের সমস্যাটি হয়েছে:\n{enriched_prompt}\n\n"
                "দয়া করে ১, ২, ৩ পয়েন্ট আকারে স্পষ্টভাবে ব্যাখ্যা করো কী সমস্যা হয়েছে এবং ইউজারকে জিজ্ঞেস করো কোন সমাধানটি চালু করবে (যেমন পাশের এজেন্ট থেকে Key শেয়ার করা বা ফ্রি মডেলে সুইচ করা)।"
            )

        # Co-Director ডুয়াল প্ল্যানিং (Option A vs Option B)
        if co_director and agent_id == "director" and len(agent_cfg.get("keys", [])) >= 2 and not is_diagnostic:
            plan_a_prompt = f"User Request: {enriched_prompt}\nGive Plan A (Creative, Emotional & Visual-First 2D Animation approach) in 4 short Bengali bullet points."
            plan_b_prompt = f"User Request: {enriched_prompt}\nGive Plan B (Fast-paced, Viral YouTube Shorts & High-Suspense approach) in 4 short Bengali bullet points."
            k0 = agent_cfg["keys"][0]
            k1 = agent_cfg["keys"][1]
            res_a, res_b = await asyncio.gather(
                call_llm_single_key(client, k0.get("provider", "google"), k0.get("model", ""), k0.get("apiKey", ""), plan_a_prompt, sys_prompt, history),
                call_llm_single_key(client, k1.get("provider", "google"), k1.get("model", ""), k1.get("apiKey", ""), plan_b_prompt, sys_prompt, history),
            )
            if res_a.get("ok") and res_b.get("ok"):
                return {
                    "ok": True,
                    "reply": "Co-Director টিম দুটি আলাদা পরিকল্পনা তৈরি করেছে—নিচ থেকে তোমার পছন্দের অপশনটি বেছে নাও:",
                    "co_director_options": {
                        "optionA": {"title": "Option A · ক্রিয়েটিভ ও ইমোশনাল ভিজ্যুয়াল", "text": res_a["text"], "model": res_a.get("model", "")},
                        "optionB": {"title": "Option B · ফাস্ট-পেসড ও ভাইরাল সাসপেন্স", "text": res_b["text"], "model": res_b.get("model", "")},
                    },
                    "youtube": yt_info,
                    "active_workers_used": 2,
                }

        res = await call_agent_with_fallbacks(client, agent_cfg, enriched_prompt, sys_prompt, history, co_work=co_work)

    if not res.get("ok"):
        return {"ok": False, "error": res.get("error", "AI উত্তর দিতে পারেনি।"), "youtube": yt_info}

    # গল্পে চরিত্র/দৃশ্য আছে কি না দেখে স্যাম্পল অ্যাপ্রুভাল প্রস্তাব (যদি ডাইরেক্ট মোড না হয়)
    low_msg = message.lower()
    story_triggers = ["গল্প", "story", "ভিডিও বানা", "video", "character", "চরিত্র", "সিন", "scene", "ছায়া", "অ্যানিমেশন"]
    ask_sample_approval = (
        agent_id == "director"
        and not direct_mode
        and not is_diagnostic
        and len(message) > 28
        and any(t in low_msg for t in story_triggers)
    )

    return {
        "ok": True,
        "reply": res["text"],
        "provider": res.get("provider"),
        "model": res.get("model"),
        "used_slot_index": res.get("used_slot_index", 0),
        "promoted_primary": res.get("promoted_primary", False),
        "auto_recovered_free": res.get("auto_recovered_free", False),
        "active_workers_used": res.get("active_workers_used", 1),
        "extras": res.get("extras", []),
        "youtube": yt_info,
        "ask_sample_approval": ask_sample_approval,
    }


@app.post("/api/generate-samples")
async def api_generate_samples(request: Request):
    """গল্প থেকে একে একে Character Model Sheet ও Background Sample তৈরি করে অনুমোদনের জন্য দেখায়"""
    body = await request.json()
    story = (body.get("story") or "").strip()
    aspect = body.get("aspect") or "9:16"
    improve_note = (body.get("improveNote") or "").strip()
    agents = body.get("agents") or {}

    if not story:
        return JSONResponse({"ok": False, "error": "গল্প দেওয়া হয়নি।"}, status_code=400)

    director_cfg = agents.get("director") or {}
    image_cfg = agents.get("image") or director_cfg

    async with httpx.AsyncClient() as client:
        prompt = (
            f"Story: {story}\n"
            + (f"Improvement requested: {improve_note}\n" if improve_note else "")
            + 'Return ONLY JSON: {"characters": [{"name": "Character 1", "desc": "visual appearance in 2D cartoon style"}], "background": {"name": "Main Location", "desc": "lighting, colors, mood"}}'
        )
        plan = await call_agent_with_fallbacks(client, director_cfg, prompt, SYSTEM_SKILLS["image"])
        parsed = safe_extract_json(plan.get("raw_text") or plan.get("text") or "") if plan.get("ok") else None

        characters = (parsed or {}).get("characters") or [
            {"name": "প্রধান চরিত্র", "desc": f"2D cartoon protagonist for story: {story[:120]}"},
            {"name": "রহস্যময় ছায়া", "desc": "Dark mysterious glowing-eye 2D cartoon shadow figure"},
        ]
        bg_info = (parsed or {}).get("background") or {
            "name": "প্রধান ব্যাকগ্রাউন্ড",
            "desc": f"Atmospheric 2D cartoon background environment for: {story[:120]}",
        }

        samples = []
        for idx, ch in enumerate(characters[:2]):
            img = await generate_real_image(
                client,
                image_cfg,
                f"2D Character Model Sheet of {ch.get('name')}: {ch.get('desc')} {improve_note}",
                scene_title=f"Character: {ch.get('name')}",
                scene_num=idx + 1,
                aspect=aspect,
                is_character_sheet=True,
            )
            samples.append({
                "type": "character",
                "name": ch.get("name", f"Character {idx+1}"),
                "desc": clean_text(ch.get("desc", "")),
                "image_data": img["image_data"],
                "source": img["source"],
            })

        bg_img = await generate_real_image(
            client,
            image_cfg,
            f"2D Animation Background Concept ({aspect}): {bg_info.get('desc')} {improve_note}",
            scene_title=f"Background: {bg_info.get('name')}",
            scene_num=len(samples) + 1,
            aspect=aspect,
            is_character_sheet=False,
        )
        samples.append({
            "type": "background",
            "name": bg_info.get("name", "Background Sample"),
            "desc": clean_text(bg_info.get("desc", "")),
            "image_data": bg_img["image_data"],
            "source": bg_img["source"],
        })

    return {"ok": True, "samples": samples}


async def _run_production_job(job_id: str, payload: Dict[str, Any]):
    """ব্যাকগ্রাউন্ডে আসল সিন-বাই-সিন প্রোডাকশন (Director → Image → Video/Runway → Audio/ElevenLabs → Edit/YouTube Pack)"""
    story = (payload.get("story") or "").strip()
    aspect = payload.get("aspect") or "9:16"
    scene_count = max(2, min(6, int(payload.get("sceneCount") or 4)))
    agents = payload.get("agents") or {}
    co_work = bool(payload.get("coWork", False))
    allow_paid_video = bool(payload.get("allowPaidVideo", False))
    character_lock = (payload.get("characterLock") or "").strip()
    improve_note = (payload.get("improveNote") or "").strip()

    director_cfg = agents.get("director") or {}
    image_cfg = agents.get("image") or director_cfg
    video_cfg = agents.get("video") or {}
    audio_cfg = agents.get("audio") or {}
    editing_cfg = agents.get("editing") or director_cfg

    try:
        async with httpx.AsyncClient() as client:
            # ধাপ ১: Director AI সিন প্ল্যানিং (০% -> ২৫%)
            update_job_progress(
                job_id, 10, "Director AI গল্প ও দৃশ্য পরিকল্পনা করছে...",
                agent_id="director", agent_status="working",
                agent_thought="গল্প বিশ্লেষণ করে সিন-বাই-সিন শট, সংলাপ ও YouTube প্যাক সাজাচ্ছি...",
                active_workers=2 if co_work else 1,
                log_entry={"agent": "Director AI", "msg": "সিন-বাই-সিন প্রোডাকশন স্ক্রিপ্ট তৈরি শুরু হয়েছে।"},
            )

            plan_prompt = (
                f"Create a {scene_count}-scene 2D cartoon video production plan ({aspect}) for:\n{story}\n"
                + (f"Locked Characters/Style: {character_lock}\n" if character_lock else "")
                + (f"Improvement Note: {improve_note}\n" if improve_note else "")
                + 'Return STRICT JSON only:\n'
                '{"title": "Video Title", "scenes": [{"scene": 1, "title": "Short Scene Title", "visual_prompt": "Detailed 2D cartoon visual description", '
                '"narration": "Short crisp Bengali narration", "subtitle": "Clean subtitle line", "sfx": "short english sfx cue"}], '
                '"youtube": {"title": "Viral YouTube Title", "description": "Short engaging description", "tags": ["#shorts", "#bangla", "#animation"]}}'
            )

            dir_res = await call_agent_with_fallbacks(
                client, director_cfg, plan_prompt, SYSTEM_SKILLS["director"], co_work=co_work, job_id=job_id, agent_id="director"
            )
            parsed = safe_extract_json(dir_res.get("raw_text") or dir_res.get("text") or "") if dir_res.get("ok") else None

            if not parsed or not parsed.get("scenes"):
                # যদি কোনো LLM Key না থাকে বা JSON না দেয়, তবুও গল্প ভেঙে পরিষ্কার সিন তৈরি হবে
                parts = [p.strip() for p in re.split(r"[।\.\n]+", story) if p.strip()]
                while len(parts) < scene_count:
                    parts.append(story[:90])
                parsed = {
                    "title": parts[0][:48] or "AI Studio 2D Video",
                    "scenes": [
                        {
                            "scene": i + 1,
                            "title": f"দৃশ্য {i + 1}",
                            "visual_prompt": f"2D cartoon scene {i + 1}: {parts[i % len(parts)]}",
                            "narration": parts[i % len(parts)],
                            "subtitle": parts[i % len(parts)][:85],
                            "sfx": "subtle cinematic ambience",
                        }
                        for i in range(scene_count)
                    ],
                    "youtube": {
                        "title": f"{parts[0][:55]} | 2D Animation Short",
                        "description": f"{story[:180]}\n\nCreated with AI Production Studio.",
                        "tags": ["#shorts", "#animation", "#banglastory", "#aistudio"],
                    },
                }

            scenes = parsed["scenes"][:scene_count]
            update_job_progress(
                job_id, 28, f"{len(scenes)}টি দৃশ্যের স্ক্রিপ্ট তৈরি হয়েছে।",
                agent_id="director", agent_status="ready",
                agent_thought=f"{len(scenes)}টি দৃশ্য ও স্ক্রিপ্ট লক করা হয়েছে।",
                active_workers=0,
                                log_entry={"agent": "Director AI", "msg": f"{len(scenes)}টি দৃশ্য চূড়ান্ত করে Image AI-কে পাঠানো হয়েছে।"},
            )

            # ধাপ ২: Image AI প্রতিটি দৃশ্যের 2D ভিজ্যুয়াল তৈরি (২৮% -> ৬২%)
            update_job_progress(
                job_id, 34, "Image AI 2D দৃশ্যগুলো আঁকছে...",
                agent_id="image", agent_status="working",
                agent_thought="প্রতিটি দৃশ্যের চরিত্র ও ব্যাকগ্রাউন্ড রেন্ডার করছি...",
                active_workers=2 if co_work else 1,
            )

            rendered_scenes = []
            for idx, sc in enumerate(scenes):
                v_prompt = f"{sc.get('visual_prompt', '')} {character_lock} {improve_note}".strip()
                img_res = await generate_real_image(
                    client, image_cfg, v_prompt,
                    scene_title=clean_text(sc.get("title", f"Scene {idx+1}")),
                    scene_num=idx + 1, aspect=aspect,
                )
                rendered_scenes.append({
                    "scene": idx + 1,
                    "title": clean_text(sc.get("title", f"দৃশ্য {idx+1}")),
                    "visual_prompt": clean_text(v_prompt),
                    "narration": clean_text(sc.get("narration", "")),
                    "subtitle": clean_text(sc.get("subtitle", "")),
                    "sfx": clean_text(sc.get("sfx", "")),
                    "image_data": img_res["image_data"],
                    "image_source": img_res["source"],
                })
                pct = 34 + int(((idx + 1) / len(scenes)) * 28)
                update_job_progress(
                    job_id, pct, f"Scene {idx+1}/{len(scenes)} ভিজ্যুয়াল রেন্ডার হয়েছে...",
                    agent_id="image", agent_status="working",
                    agent_thought=f"Scene {idx+1}/{len(scenes)} সম্পন্ন ({img_res['source']})",
                    active_workers=2 if co_work else 1,
                )

            update_job_progress(
                job_id, 64, "সব দৃশ্যের 2D আর্ট তৈরি সম্পন্ন।",
                agent_id="image", agent_status="ready", active_workers=0,
                log_entry={"agent": "Image AI", "msg": f"{len(rendered_scenes)}টি দৃশ্যের ভিজ্যুয়াল তৈরি সম্পন্ন।"},
            )

            # ধাপ ৩: Video AI (Runway আসল ভিডিও রেন্ডার — কেবল অনুমতি ও Key থাকলে) (৬৪% -> ৭৮%)
            video_clip_url = None
            video_note = "2D অ্যানিমেটেড সিন রিল প্রস্তুত (ফ্রি মোড — Runway ক্রেডিট খরচ হয়নি)।"
            runway_slot = _find_provider_key(video_cfg, "runway")
            if runway_slot and allow_paid_video:
                update_job_progress(
                    job_id, 68, "Video AI (Runway) আসল ভিডিও ক্লিপ রেন্ডার করছে...",
                    agent_id="video", agent_status="working",
                    agent_thought="Runway gen4_turbo সার্ভারে আসল ভিডিও ক্লিপ তৈরি হচ্ছে...",
                    active_workers=1,
                    log_entry={"agent": "Video AI", "msg": "Runway আসল ভিডিও রেন্ডার শুরু হয়েছে..."},
                )
                first_prompt = rendered_scenes[0]["visual_prompt"] if rendered_scenes else story
                rw = await generate_runway_video(client, runway_slot["apiKey"], first_prompt, runway_slot["model"] or "gen4_turbo", aspect)
                if rw.get("ok"):
                    video_clip_url = rw["video_url"]
                    video_note = "Runway আসল MP4 ভিডিও ক্লিপ রেন্ডার সফল হয়েছে!"
                else:
                    video_note = f"Runway ব্যর্থ ({rw.get('error')}) — 2D অ্যানিমেটেড সিন রিলে fallback করা হয়েছে।"
            update_job_progress(
                job_id, 78, "ভিডিও লেয়ার প্রস্তুত।",
                agent_id="video", agent_status="ready", agent_thought=video_note, active_workers=0,
                log_entry={"agent": "Video AI", "msg": video_note},
            )

            # ধাপ ৪: Audio AI (ElevenLabs আসল বাংলা ভয়েসওভার ও SFX) (৭৮% -> ৯০%)
            audio_data = None
            sfx_data = None
            audio_note = "ভয়েসওভার স্ক্রিপ্ট প্রস্তুত (আসল MP3 অডিওর জন্য ElevenLabs Key যোগ করো)।"
            el_slot = _find_provider_key(audio_cfg, "elevenlabs")
            full_narration = " । ".join([s["narration"] for s in rendered_scenes if s.get("narration")])

            if el_slot and full_narration:
                update_job_progress(
                    job_id, 82, "Audio AI (ElevenLabs) বাংলা ভয়েসওভার তৈরি করছে...",
                    agent_id="audio", agent_status="working",
                    agent_thought="ElevenLabs Multilingual ইঞ্জিনে আসল ভয়েস রেন্ডার হচ্ছে...",
                    active_workers=1,
                )
                tts = await generate_elevenlabs_audio(client, el_slot["apiKey"], full_narration, el_slot["model"] or "eleven_multilingual_v2")
                if tts.get("ok"):
                    audio_data = tts["audio_data"]
                    audio_note = "ElevenLabs আসল MP3 ভয়েসওভার সফলভাবে তৈরি হয়েছে!"
                    first_sfx = next((s["sfx"] for s in rendered_scenes if s.get("sfx")), "")
                    if first_sfx:
                        sfx_res = await generate_elevenlabs_sfx(client, el_slot["apiKey"], first_sfx, 2.5)
                        if sfx_res.get("ok"):
                            sfx_data = sfx_res["audio_data"]
                else:
                    audio_note = f"ElevenLabs ব্যর্থ: {tts.get('error')}"

            update_job_progress(
                job_id, 90, "অডিও লেয়ার প্রস্তুত।",
                agent_id="audio", agent_status="ready", agent_thought=audio_note, active_workers=0,
                log_entry={"agent": "Audio AI", "msg": audio_note},
            )

            # ধাপ ৫: Edit AI (ফাইনাল কম্পাইলেশন ও YouTube রেডি প্যাক) (৯০% -> ১০০%)
            update_job_progress(
                job_id, 95, "Edit AI সাবটাইটেল ও YouTube প্যাক ফাইনাল করছে...",
                agent_id="editing", agent_status="working",
                agent_thought="সাবটাইটেল, টাইটেল, ডেসক্রিপশন, হ্যাশট্যাগ ও থাম্বনেল সাজাচ্ছি...",
                active_workers=1,
            )
            yt_pack = parsed.get("youtube") or {}
            clean_yt = {
                "title": clean_text(yt_pack.get("title") or parsed.get("title") or "AI Studio Video"),
                "description": clean_text(yt_pack.get("description") or story[:200]),
                "tags": yt_pack.get("tags") or ["#shorts", "#animation", "#bangla"],
                "thumbnail": rendered_scenes[0]["image_data"] if rendered_scenes else "",
            }

            JOBS[job_id]["status"] = "completed"
            JOBS[job_id]["ready_signal"] = True
            JOBS[job_id]["result"] = {
                "title": clean_text(parsed.get("title") or "AI Studio Production"),
                "aspect": aspect,
                "scenes": rendered_scenes,
                "video_clip_url": video_clip_url,
                "video_note": video_note,
                "audio_data": audio_data,
                "sfx_data": sfx_data,
                "audio_note": audio_note,
                "narration_script": full_narration,
                "youtube_pack": clean_yt,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            update_job_progress(
                job_id, 100, "সম্পন্ন! আউটপুট প্রস্তুত।",
                agent_id="editing", agent_status="ready",
                agent_thought="ফাইনাল 2D সিন রিল, অডিও ও YouTube প্যাক Output বক্সে পাঠানো হয়েছে।",
                active_workers=0,
                log_entry={"agent": "Edit AI", "msg": "প্রোডাকশন ১০০% সম্পন্ন! Output বক্সে ফাইল রেডি।"},
            )
    except Exception as e:
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = str(e)
        update_job_progress(job_id, JOBS[job_id].get("progress", 0), f"ত্রুটি: {str(e)}")


@app.post("/api/produce")
async def api_produce(request: Request):
    """নতুন লাইভ প্রোডাকশন জব চালু করে এবং সাথে সাথে job_id দেয় (প্রোগ্রেস বার পোলিংয়ের জন্য)"""
    body = await request.json()
    story = (body.get("story") or "").strip()
    if not story:
        return JSONResponse({"ok": False, "error": "প্রোডাকশনের জন্য গল্প বা প্রম্পট দাও।"}, status_code=400)

    cleanup_old_jobs()
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {
        "job_id": job_id,
        "status": "running",
        "progress": 5,
        "stage": "স্টুডিও টিম সক্রিয় হচ্ছে...",
        "ready_signal": False,
        "agent_states": {
            aid: {"status": "idle", "thought": "অপেক্ষায় আছে...", "active_workers": 0}
            for aid in ["director", "image", "video", "audio", "editing"]
        },
        "team_logs": [{"agent": "Studio", "msg": "প্রোডাকশন জব শুরু হয়েছে।", "time": time.strftime("%H:%M:%S")}],
        "result": None,
        "error": None,
        "updated_at": time.time(),
    }
    asyncio.create_task(_run_production_job(job_id, body))
    return {"ok": True, "job_id": job_id}


@app.get("/api/job/{job_id}")
async def api_get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return JSONResponse({"ok": False, "error": "জব পাওয়া যায়নি।"}, status_code=404)
    return {"ok": True, "job": job}


@app.post("/api/dub")
async def api_dub(request: Request):
    """অন-ডিমান্ড বাংলা/হিন্দি ভিডিও ডাবিং (স্ক্রিপ্ট অনুবাদ + ElevenLabs আসল ভয়েসওভার)"""
    body = await request.json()
    source_text = (body.get("text") or "").strip()
    target_lang = (body.get("targetLang") or "bn").strip().lower()
    agents = body.get("agents") or {}

    if not source_text:
        return JSONResponse({"ok": False, "error": "ডাবিং করার জন্য সংলাপ বা স্ক্রিপ্ট দাও।"}, status_code=400)

    lang_name = "Natural Bengali (বাংলা)" if target_lang == "bn" else ("Natural Hindi (हिन्दी)" if target_lang == "hi" else "Natural English")
    director_cfg = agents.get("director") or {}
    audio_cfg = agents.get("audio") or {}

    async with httpx.AsyncClient() as client:
        tr_prompt = f"Translate and adapt this dialogue into {lang_name} for natural expressive video dubbing. Return ONLY the clean translated dialogue without markdown:\n{source_text}"
        tr_res = await call_agent_with_fallbacks(client, director_cfg, tr_prompt, SYSTEM_SKILLS["audio"])
        dubbed_script = tr_res["text"] if tr_res.get("ok") else clean_text(source_text)

        el_slot = _find_provider_key(audio_cfg, "elevenlabs")
        if el_slot:
            tts = await generate_elevenlabs_audio(client, el_slot["apiKey"], dubbed_script, el_slot["model"] or "eleven_multilingual_v2")
            if tts.get("ok"):
                return {
                    "ok": True,
                    "dubbed_script": dubbed_script,
                    "audio_data": tts["audio_data"],
                    "note": f"{lang_name} আসল ডাবিং অডিও (.mp3) তৈরি হয়েছে! ব্যাকগ্রাউন্ড সাউন্ড মিক্স করার জন্য প্রস্তুত।",
                }
            return {
                "ok": True,
                "dubbed_script": dubbed_script,
                "audio_data": None,
                "note": f"স্ক্রিপ্ট অনুবাদ হয়েছে, কিন্তু ElevenLabs ত্রুটি: {tts.get('error')}",
            }

    return {
        "ok": True,
        "dubbed_script": dubbed_script,
        "audio_data": None,
        "note": f"{lang_name} ডাবিং স্ক্রিপ্ট প্রস্তুত। আসল ভয়েস (.mp3) বানাতে Audio এজেন্টে একটি ElevenLabs Key যোগ করো।",
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
    
