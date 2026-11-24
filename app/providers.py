"""
Provider Engine: Handles API key detection, model fetching, and LLM/TTS API calls.
Designed for maximum resilience - never crashes the server on bad API keys.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import edge_tts

from app.config import PROVIDERS, AGENTS
from app.models import KeySlot, AgentSlot


# ------------------------------------------------------------------------------
# Helper: Translate common technical errors to Bangla
# ------------------------------------------------------------------------------
def translate_error_to_bangla(err_en: str) -> str:
    e = (err_en or "").lower()
    if "401" in e or "unauthorized" in e or "missing authentication" in e:
        return "এপিআই কী-টি ভুল অথবা মেয়াদোত্তীর্ণ। দয়া করে সঠিক কী দিন।"
    if "402" in e or "insufficient credits" in e or "quota" in e:
        return "আপনার অ্যাকাউন্টে পর্যাপ্ত ক্রেডিট বা কোটা নেই। দয়া করে ক্রেডিট রিচার্জ করুন।"
    if "429" in e or "rate limit" in e:
        return "অতিরিক্ত রিকোয়েস্টের কারণে সাময়িকভাবে ব্লক করা হয়েছে। কিছুক্ষণ পর আবার চেষ্টা করুন।"
    if "404" in e:
        return "মডেল বা সার্ভার পাওয়া যায়নি। মডেলের নাম পরিবর্তন করে দেখুন।"
    if "500" in e or "502" in e or "503" in e:
        return "প্রোভাইডারের সার্ভারে সমস্যা হচ্ছে। কিছুক্ষণ পর আবার চেষ্টা করুন।"
    if "timeout" in e or "connect" in e:
        return "সার্ভারের সাথে সংযোগ বিচ্ছিন্ন হয়েছে বা সময় শেষ হয়ে গেছে।"
    return "একটি অজানা সমস্যা হয়েছে। দয়া করে এপিআই কী এবং ইন্টারনেট চেক করুন।"


# ------------------------------------------------------------------------------
# 1. API Key Detection & Model Fetching
# ------------------------------------------------------------------------------
async def probe_single_provider(
    provider_id: str,
    api_key: str,
    custom_base_url: Optional[str] = None
) -> Dict[str, Any]:
    """Verify if an API key is valid and fetch available models."""
    if not api_key:
        return {"ok": False, "error": "API Key is empty", "models": []}

    prov = PROVIDERS.get(provider_id)
    if not prov and provider_id != "custom":
        return {"ok": False, "error": f"Unknown provider: {provider_id}", "models": []}

    models_endpoint = custom_base_url if custom_base_url else prov.get("models_endpoint")
    
    headers = {}
    if prov and prov.get("auth") == "query_key":
        url = f"{models_endpoint}?key={api_key}"
    else:
        if provider_id == "anthropic":
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        elif provider_id == "elevenlabs":
            headers = {"xi-api-key": api_key}
        else:
            headers = {"Authorization": f"Bearer {api_key}"}
        url = models_endpoint

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(url, headers=headers)
            
            if resp.status_code != 200:
                err_msg = f"{provider_id.upper()} ({resp.status_code}): {resp.text[:150]}"
                return {"ok": False, "error": err_msg, "models": []}
            
            data = resp.json()
            models = []
            
            # Parse models based on provider format
            if provider_id == "google":
                models = [
                    m["name"].replace("models/", "")
                    for m in data.get("models", [])
                    if "generateContent" in m.get("supportedGenerationMethods", [])
                ]
            elif provider_id == "anthropic":
                models = [m["id"] for m in data.get("data", [])]
            elif provider_id == "elevenlabs":
                models = [m["model_id"] for m in data if isinstance(m, dict)]
            else: # OpenAI, OpenRouter, Groq, DeepSeek, Custom
                models = [m["id"] for m in data.get("data", []) if isinstance(m, dict)]
                if provider_id == "openrouter" and "openrouter/free" not in models:
                    models.insert(0, "openrouter/free")

            return {"ok": True, "models": models, "error": ""}
            
    except Exception as e:
        return {"ok": False, "error": str(e), "models": []}


# ------------------------------------------------------------------------------
# 2. LLM API Call (OpenAI, Gemini, Claude, etc.)
# ------------------------------------------------------------------------------
async def call_llm_slot(
    slot: KeySlot,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 2000,
) -> str:
    """Call the LLM using the agent's assigned slot. Raises Exception on failure."""
    if not slot or not slot.api_key:
        raise ValueError("No API key assigned to this agent slot.")

    provider = slot.provider_id
    model = slot.model_id
    api_key = slot.api_key
    base_url = slot.base_url or PROVIDERS.get(provider, {}).get("base_url", "")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # --- GOOGLE GEMINI ---
            if provider == "google":
                url = f"{base_url}/models/{model}:generateContent?key={api_key}"
                payload = {
                    "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}
                }
                resp = await client.post(url, json=payload)
                if resp.status_code != 200:
                    raise RuntimeError(f"Google {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]

            # --- ANTHROPIC CLAUDE ---
            elif provider == "anthropic":
                url = f"{base_url}/messages"
                headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
                payload = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_prompt}],
                    "temperature": temperature
                }
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code != 200:
                    raise RuntimeError(f"Anthropic {resp.status_code}: {resp.text[:200]}")
                return resp.json()["content"][0]["text"]

            # --- OPENAI / OPENROUTER / GROQ / DEEPSEEK / CUSTOM ---
            else:
                url = f"{base_url.rstrip('/')}/chat/completions"
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                if provider == "openrouter":
                    headers["HTTP-Referer"] = "https://ai-video-studio.local"
                    headers["X-Title"] = "AI Studio"
                
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": user_prompt})

                payload = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens
                }
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code != 200:
                    raise RuntimeError(f"{provider.upper()} {resp.status_code}: {resp.text[:200]}")
                return resp.json()["choices"][0]["message"]["content"]

    except Exception as e:
        # Translate the error to Bangla before raising it up
        bn_msg = translate_error_to_bangla(str(e))
        raise RuntimeError(f"{bn_msg} (Details: {str(e)[:100]})")


# ------------------------------------------------------------------------------
# 3. Text-to-Speech (TTS) Generation
# ------------------------------------------------------------------------------
async def generate_narration_audio(
    text: str,
    voice_profile: str = "bn-IN-BashkarNeural",
    audio_slot: Optional[KeySlot] = None,
    out_path: Path = Path("narration.mp3"),
) -> Path:
    """Generate audio using ElevenLabs, OpenAI TTS, or Edge-TTS (fallback)."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Text is empty.")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Try Premium Providers if available
    if audio_slot and audio_slot.api_key:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                if audio_slot.provider_id == "elevenlabs":
                    url = f"https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM"
                    headers = {"xi-api-key": audio_slot.api_key, "Content-Type": "application/json"}
                    payload = {"text": text, "model_id": audio_slot.model_id or "eleven_multilingual_v2"}
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code == 200 and len(resp.content) > 500:
                        out_path.write_bytes(resp.content)
                        return out_path
                
                elif audio_slot.provider_id == "openai":
                    url = f"{audio_slot.base_url or 'https://api.openai.com/v1'}/audio/speech"
                    headers = {"Authorization": f"Bearer {audio_slot.api_key}", "Content-Type": "application/json"}
                    payload = {"model": "tts-1", "voice": "onyx", "input": text}
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code == 200 and len(resp.content) > 500:
                        out_path.write_bytes(resp.content)
                        return out_path
        except Exception:
            pass # Fallback to Edge-TTS

    # 2. Free Fallback: Edge-TTS (Requires no API Key)
    try:
        safe_voice = voice_profile if voice_profile else "bn-IN-BashkarNeural"
        communicate = edge_tts.Communicate(text, safe_voice)
        await communicate.save(str(out_path))
        if out_path.exists() and out_path.stat().st_size > 500:
            return out_path
    except Exception:
        # Final fallback: English voice
        communicate = edge_tts.Communicate(text, "en-US-GuyNeural")
        await communicate.save(str(out_path))
        return out_path

    return out_path
