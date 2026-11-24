# ==============================================================================
# AI Video Production Studio - Universal Provider & Auto-Detect Engine (Part C1)
# Covers: 3-Tier Deep Auto-Detect, Persistent Custom Base URL Auto-Learn,
#         Live Model Discovery, Free/Paid Classification & Async Multi-LLM Calls
# ==============================================================================

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from app.config import (
    get_all_providers,
    get_provider_by_id,
    save_custom_provider,
)
from app.models import AgentSlot

DEFAULT_TIMEOUT = httpx.Timeout(25.0, connect=10.0)


# ------------------------------------------------------------------------------
# 1. ERROR TRANSLATOR (ENGLISH TECHNICAL ERROR -> SIMPLE BANGLA SUMMARY)
# ------------------------------------------------------------------------------
def translate_error_to_bangla(error_text: str) -> str:
    """Convert raw API HTTP/Auth errors into clear, friendly Bangla summaries."""
    low = (error_text or "").lower()
    if any(k in low for k in ("401", "invalid api key", "unauthorized", "api_key_invalid", "incorrect api key")):
        return "API Key-টি সঠিক নয় বা মেয়াদ শেষ হয়ে গেছে। নতুন বা সঠিক Key বসিয়ে আবার চেষ্টা করুন।"
    if any(k in low for k in ("402", "insufficient", "quota", "credit", "billing", "balance")):
        return "এই API Key-এর ফ্রি লিমিট বা ব্যালেন্স শেষ হয়ে গেছে। ফ্রি মডেল বেছে নিন অথবা Secondary Key-তে সুইচ করুন।"
    if any(k in low for k in ("429", "rate limit", "too many requests", "resource_exhausted")):
        return "অতিরিক্ত রিকোয়েস্টের কারণে সাময়িক লিমিট পূর্ণ হয়েছে। কয়েক সেকেন্ড পর চেষ্টা করুন বা Self-Switch চাপুন।"
    if any(k in low for k in ("404", "model not found", "does not exist", "not_found")):
        return "নির্বাচিত মডেলটি এই কোম্পানিতে পাওয়া যায়নি। Self-Healing চাপলে অন্য সচল মডেল সেট হয়ে যাবে।"
    if any(k in low for k in ("403", "permission", "forbidden", "access denied")):
        return "এই Key-তে নির্বাচিত মডেলটি ব্যবহারের অনুমতি নেই। Key পারমিশন বা মডেল পরিবর্তন করুন।"
    if any(k in low for k in ("timeout", "timed out", "connect", "dns", "network")):
        return "সার্ভারের সাথে সংযোগ স্থাপন করা যাচ্ছে না। ইন্টারনেট বা Base URL যাচাই করুন।"
    return "API সংযোগে একটি অপ্রত্যাশিত ত্রুটি হয়েছে। Self-Healing বা Self-Switching চেষ্টা করুন।"


# ------------------------------------------------------------------------------
# 2. AUTH HEADER & MODEL TIER HELPERS
# ------------------------------------------------------------------------------
def build_auth_headers(provider: Dict[str, Any], api_key: str) -> Dict[str, str]:
    """Construct provider-specific authentication headers."""
    auth_type = provider.get("auth_type", "bearer")
    headers: Dict[str, str] = {"Accept": "application/json"}
    if auth_type == "bearer":
        headers["Authorization"] = f"Bearer {api_key}"
    elif auth_type == "fal_key":
        headers["Authorization"] = f"Key {api_key}"
    elif auth_type == "xi-api-key":
        headers["xi-api-key"] = api_key
    elif auth_type == "x-api-key":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    if provider.get("id") == "openrouter":
        headers["HTTP-Referer"] = "https://ai-video-studio.local"
        headers["X-Title"] = "AI Video Production Studio"
    return headers


def classify_model_free(provider_id: str, model_id: str, raw_item: Optional[Dict[str, Any]] = None) -> bool:
    """Detect whether a model is free-tier or paid."""
    low = model_id.lower()
    if ":free" in low or "-free" in low or "schnell-free" in low:
        return True
    if raw_item and isinstance(raw_item, dict):
        pricing = raw_item.get("pricing")
        if isinstance(pricing, dict):
            try:
                p_prompt = float(pricing.get("prompt", 1))
                p_comp = float(pricing.get("completion", 1))
                if p_prompt == 0.0 and p_comp == 0.0:
                    return True
            except (TypeError, ValueError):
                pass
    if provider_id in ("google_gemini", "groq", "cerebras", "sambanova", "huggingface"):
        if any(k in low for k in ("flash", "8b", "70b", "schnell", "whisper", "qwen", "llama")):
            return True
    return False


# ------------------------------------------------------------------------------
# 3. LIVE PROVIDER PROBE & MODEL DISCOVERY
# ------------------------------------------------------------------------------
async def probe_single_provider(
    client: httpx.AsyncClient,
    provider: Dict[str, Any],
    api_key: str,
) -> Tuple[bool, List[Dict[str, Any]], str]:
    """
    Verify an API key against a single provider and fetch its live models.
    Returns: (is_valid, models_list, error_message)
    """
    pid = provider["id"]
    endpoint = provider.get("models_endpoint") or f"{provider['base_url'].rstrip('/')}/models"
    headers = build_auth_headers(provider, api_key)
    params = {"key": api_key} if provider.get("auth_type") == "query_key" else None

    try:
        resp = await client.get(endpoint, headers=headers, params=params)
        if resp.status_code in (401, 403):
            return False, [], f"HTTP {resp.status_code}: Unauthorized ({resp.text[:160]})"
        if resp.status_code >= 400:
            # Fal.ai & some providers may restrict /models list; treat non-auth errors carefully
            if pid == "fal_ai" and resp.status_code in (404, 405):
                return True, _fallback_models_from_registry(provider), ""
            return False, [], f"HTTP {resp.status_code}: {resp.text[:180]}"

        data = resp.json() if resp.content else {}
        models = _parse_models_response(pid, provider, data)
        if not models:
            models = _fallback_models_from_registry(provider)
        return True, models, ""
    except Exception as exc:
        return False, [], str(exc)


def _fallback_models_from_registry(provider: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build structured model list from registry defaults when /models is sparse."""
    seen = set()
    items: List[Dict[str, Any]] = []
    for entry in provider.get("top_free", []):
        mid = entry["id"]
        if mid not in seen:
            seen.add(mid)
            items.append({"id": mid, "is_free": True, "note": entry.get("note", "Free / Low-Cost")})
    for entry in provider.get("top_paid", []):
        mid = entry["id"]
        if mid not in seen:
            seen.add(mid)
            items.append({"id": mid, "is_free": False, "note": entry.get("note", "Pro Tier")})
    return items


def _parse_models_response(
    provider_id: str,
    provider: Dict[str, Any],
    data: Any,
) -> List[Dict[str, Any]]:
    """Normalize live /models responses across Gemini, OpenAI, OpenRouter, ElevenLabs, etc."""
    raw_list: List[Any] = []
    if isinstance(data, dict):
        if isinstance(data.get("data"), list):
            raw_list = data["data"]
        elif isinstance(data.get("models"), list):
            raw_list = data["models"]
    elif isinstance(data, list):
        raw_list = data

    parsed: List[Dict[str, Any]] = []
    for item in raw_list[:120]:
        if not isinstance(item, dict):
            continue
        mid = item.get("id") or item.get("model_id") or item.get("name") or ""
        if mid.startswith("models/"):
            mid = mid.split("models/", 1)[1]
        if not mid:
            continue
        is_free = classify_model_free(provider_id, mid, item)
        parsed.append({
            "id": mid,
            "is_free": is_free,
            "note": "FREE" if is_free else "PAID",
        })
    return parsed or _fallback_models_from_registry(provider)
          # ------------------------------------------------------------------------------
# 4. 3-TIER DEEP AUTO-DETECT + AUTO-LEARN CUSTOM BASE URL
# ------------------------------------------------------------------------------
def _match_prefix_candidates(api_key: str) -> List[Dict[str, Any]]:
    """Tier 1: Match key prefix against built-in and auto-learned providers."""
    providers = get_all_providers()
    exact_matches: List[Dict[str, Any]] = []
    ambiguous_sk: List[Dict[str, Any]] = []

    for p in providers.values():
        prefixes = p.get("key_prefixes") or []
        for pref in prefixes:
            if pref and api_key.startswith(pref):
                if pref in ("sk-", "key_"):
                    ambiguous_sk.append(p)
                else:
                    exact_matches.append(p)
                break

    if exact_matches:
        # Sort longest prefix first (e.g., sk-or-v1- before sk-)
        exact_matches.sort(
            key=lambda item: max((len(x) for x in item.get("key_prefixes", []) if api_key.startswith(x)), default=0),
            reverse=True,
        )
        return exact_matches
    if ambiguous_sk:
        return ambiguous_sk
    # Tier 3: Probe all OpenAI-compatible providers in parallel
    return list(providers.values())


async def auto_detect_api_key(
    api_key: str,
    custom_base_url: Optional[str] = None,
    preferred_provider: Optional[str] = None,
) -> Dict[str, Any]:
    """
    3-Tier Deep Auto-Detect:
      1. Custom Base URL (if provided) -> verifies & permanently saves via Auto-Learn.
      2. Prefix / Auto-Learned Registry match.
      3. Parallel live probe across candidate providers to confirm validity & models.
    """
    clean_key = (api_key or "").strip()
    if not clean_key:
        return {"detected": False, "error_en": "Empty API Key", "error_bn": "API Key ফাঁকা রয়েছে।"}

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
        # Case A: User supplied a Custom Base URL for an unknown/deep provider
        if custom_base_url and custom_base_url.strip():
            raw_url = custom_base_url.strip().rstrip("/")
            parsed = urlparse(raw_url)
            host = parsed.netloc or "custom-ai"
            clean_host = re.sub(r"[^a-zA-Z0-9]+", "_", host).strip("_").lower()
            provider_id = f"custom_{clean_host}"
            prefix_guess = clean_key[:6] if len(clean_key) >= 6 else ""

            custom_cfg: Dict[str, Any] = {
                "id": provider_id,
                "name": f"Custom ({host})",
                "brand_short": host.split(".")[0].capitalize(),
                "base_url": raw_url,
                "models_endpoint": f"{raw_url}/models",
                "auth_type": "bearer",
                "key_prefixes": [prefix_guess] if prefix_guess else [],
                "capabilities": ["reasoning", "script", "coding", "image_gen", "editing"],
                "supports_agents": ["director", "image", "editing"],
                "default_models": {},
                "top_paid": [],
                "top_free": [],
            }
            ok, models, err = await probe_single_provider(client, custom_cfg, clean_key)
            if ok:
                if models:
                    custom_cfg["default_models"] = {
                        "director": models[0]["id"],
                        "editing": models[0]["id"],
                    }
                    custom_cfg["top_free"] = [
                        {"id": m["id"], "note": "Auto-Detected Free"} for m in models if m.get("is_free")
                    ][:3]
                    custom_cfg["top_paid"] = [
                        {"id": m["id"], "note": "Auto-Detected Model"} for m in models if not m.get("is_free")
                    ][:3]
                save_custom_provider(provider_id, custom_cfg)
                return {
                    "detected": True,
                    "learned_custom": True,
                    "provider": custom_cfg,
                    "models": models,
                    "recommended_agents": custom_cfg["supports_agents"],
                }
            return {
                "detected": False,
                "error_en": err or "Could not verify Custom Base URL.",
                "error_bn": translate_error_to_bangla(err),
            }

        # Case B: Preferred provider explicitly chosen in dropdown
        candidates: List[Dict[str, Any]] = []
        if preferred_provider:
            p = get_provider_by_id(preferred_provider)
            if p:
                candidates.append(p)
        for c in _match_prefix_candidates(clean_key):
            if c["id"] not in {x["id"] for x in candidates}:
                candidates.append(c)

        # Probe top candidates in parallel (batches of 6)
        last_err = ""
        for i in range(0, len(candidates), 6):
            batch = candidates[i : i + 6]
            results = await asyncio.gather(
                *(probe_single_provider(client, p, clean_key) for p in batch),
                return_exceptions=True,
            )
            for prov, res in zip(batch, results):
                if isinstance(res, Exception):
                    last_err = str(res)
                    continue
                ok, models, err = res
                if ok:
                    return {
                        "detected": True,
                        "learned_custom": False,
                        "provider": prov,
                        "models": models,
                        "recommended_agents": prov.get("supports_agents", ["director"]),
                    }
                if err:
                    last_err = err

        return {
            "detected": False,
            "needs_custom_url": True,
            "error_en": last_err or "Provider could not be auto-detected.",
            "error_bn": "এই Key-টির কোম্পানি স্বয়ংক্রিয়ভাবে শনাক্ত হয়নি। নতুন কোম্পানি হলে নিচের Custom Base URL ঘরে তার https:// ঠিকানা দিন।",
        }


# ------------------------------------------------------------------------------
# 5. UNIVERSAL ASYNC CHAT / COMPLETION CALLER (ALL PROVIDERS)
# ------------------------------------------------------------------------------
async def call_llm_slot(
    slot: AgentSlot,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 2048,
) -> str:
    """Execute a real text/JSON generation call across Gemini, Claude, OpenAI-compat, or HF."""
    provider = get_provider_by_id(slot.provider_id) or {
        "id": slot.provider_id,
        "base_url": slot.base_url or "https://api.openai.com/v1",
        "auth_type": "bearer",
    }
    base_url = (slot.base_url or provider.get("base_url") or "").rstrip("/")
    model_id = slot.model_id
    api_key = slot.api_key

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=12.0)) as client:
        # 1) Native Google Gemini API
        if provider["id"] == "google_gemini":
            url = f"{base_url}/models/{model_id}:generateContent"
            payload = {
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
            }
            resp = await client.post(url, params={"key": api_key}, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]

        # 2) Native Anthropic Claude API
        if provider["id"] == "anthropic":
            url = f"{base_url}/messages"
            headers = build_auth_headers(provider, api_key)
            headers["Content-Type"] = "application/json"
            payload = {
                "model": model_id,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            }
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["content"][0]["text"]

        # 3) OpenAI-Compatible Endpoints (OpenRouter, Groq, OpenAI, DeepSeek, NVIDIA, Custom, etc.)
        chat_url = f"{base_url}/chat/completions"
        headers = build_auth_headers(provider, api_key)
        headers["Content-Type"] = "application/json"
        payload = {
            "model": model_id,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        resp = await client.post(chat_url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
      
