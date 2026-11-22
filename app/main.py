import os
import uuid
import base64
import asyncio
from typing import Any, Dict, List, Optional
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="AI Video Studio Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

JOBS: Dict[str, Dict[str, Any]] = {}
MAX_JOBS = 100

# Role-based preferred model keywords for smart auto-selection
ROLE_PREFS = {
    "director": [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "deepseek-r1",
        "claude-3.5",
        "gpt-4o",
        "llama-3.3-70b",
        "openrouter/free",
    ],
    "image": [
        "flux",
        "imagen",
        "gpt-image",
        "recraft",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "openrouter/free",
    ],
    "video": [
        "gen4",
        "gen3",
        "veo",
        "kling",
        "minimax",
        "llama-3.3-70b",
        "gemini-2.5-flash",
        "openrouter/free",
    ],
    "audio": [
        "eleven_multilingual_v2",
        "eleven_turbo_v2_5",
        "gemini-2.5-flash",
        "openrouter/free",
    ],
    "editing": [
        "llama-3.3-70b",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gpt-4o-mini",
        "openrouter/free",
    ],
}


def cleanup_old_jobs() -> None:
    if len(JOBS) > MAX_JOBS:
        oldest_keys = list(JOBS.keys())[: len(JOBS) - MAX_JOBS]
        for k in oldest_keys:
            JOBS.pop(k, None)


def guess_provider_from_key(api_key: str, fallback: str = "google") -> str:
    k = (api_key or "").strip()
    if not k:
        return fallback or "google"
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


def pick_best_model(models: List[str], agent_id: str, provider: str) -> str:
    defaults = {
        "google": "gemini-2.5-flash",
        "openrouter": "openrouter/free",
        "groq": "llama-3.3-70b-versatile",
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-5-sonnet-latest",
        "deepseek": "deepseek-chat",
        "mistral": "mistral-small-latest",
        "elevenlabs": "eleven_multilingual_v2",
        "runway": "gen3a_turbo",
    }
    if not models:
        return defaults.get(provider, "openrouter/free")

    prefs = ROLE_PREFS.get(agent_id, ROLE_PREFS["director"])
    lower_map = [(m, m.lower()) for m in models]

    for pref in prefs:
        for orig, low in lower_map:
            if pref in low:
                return orig

    if provider == "openrouter":
        for orig, low in lower_map:
            if ":free" in low or "free" in low:
                return orig

    return models[0]


def inject_continuity(system_prompt: str, project_memory: str) -> str:
    mem = (project_memory or "").strip()
    if not mem:
        return system_prompt or ""
    continuity_block = (
        "\n\n=== STRICT CHARACTER BIBLE & PROJECT CONTINUITY (MUST FOLLOW) ===\n"
        f"{mem}\n"
        "=== CONTINUITY RULE ===\n"
        "You are continuing an ongoing multi-part video project. "
        "Keep EVERY character's face, hair, age, outfit, art style (2D/3D), color tone, voice style, "
        "and story continuity 100% consistent with the Character Bible above. "
        "Do NOT redesign or change established characters unless the user explicitly asks."
    )
    return (system_prompt or "").strip() + continuity_block


def normalize_anthropic_messages(history: List[Dict[str, str]], prompt: str) -> List[Dict[str, str]]:
    raw = []
    for h in history[-12:]:
        content = (h.get("content") or "").strip()
        if not content:
            continue
        role = "user" if h.get("role") == "user" else "assistant"
        raw.append({"role": role, "content": content})
    raw.append({"role": "user", "content": prompt})

    # Anthropic requires starting with 'user' and alternating roles
    cleaned: List[Dict[str, str]] = []
    for msg in raw:
        if not cleaned and msg["role"] != "user":
            continue
        if cleaned and cleaned[-1]["role"] == msg["role"]:
            cleaned[-1]["content"] += "\n\n" + msg["content"]
        else:
            cleaned.append(msg)
    return cleaned or [{"role": "user", "content": prompt}]


async def fetch_provider_models(
    client: httpx.AsyncClient, provider: str, api_key: str, custom_url: str = ""
) -> Dict[str, Any]:
    try:
        if provider == "google":
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            r = await client.get(url, timeout=12)
            if r.status_code != 200:
                return {"ok": False, "error": f"Google API ({r.status_code}): {r.text[:250]}", "models": []}
            data = r.json()
            models = [
                m["name"].replace("models/", "")
                for m in data.get("models", [])
                if isinstance(m, dict)
                and "generateContent" in m.get("supportedGenerationMethods", [])
                and m.get("name")
            ]
            return {"ok": True, "models": models}

        if provider == "elevenlabs":
            r = await client.get(
                "https://api.elevenlabs.io/v1/models",
                headers={"xi-api-key": api_key},
                timeout=12,
            )
            if r.status_code != 200:
                return {"ok": False, "error": f"ElevenLabs ({r.status_code}): {r.text[:250]}", "models": []}
            data = r.json()
            models = [m.get("model_id") for m in data if isinstance(m, dict) and m.get("model_id")]
            return {"ok": True, "models": models}

        if provider == "anthropic":
            r = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                timeout=12,
            )
            if r.status_code != 200:
                return {"ok": False, "error": f"Anthropic ({r.status_code}): {r.text[:250]}", "models": []}
            data = r.json()
            models = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
            return {"ok": True, "models": models}

        if provider == "runway":
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
        r = await client.get(url, headers=headers, timeout=12)
        if r.status_code != 200:
            return {"ok": False, "error": f"{provider.upper()} ({r.status_code}): {r.text[:250]}", "models": []}

        data = r.json()
        raw_list = data.get("data", []) if isinstance(data, dict) else []
        models = [m["id"] for m in raw_list if isinstance(m, dict) and m.get("id")]
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
    model = (model or "").strip() or pick_best_model([], "director", provider)

    try:
        if provider == "elevenlabs":
            return {
                "ok": True,
                "text": "🎙️ ElevenLabs Audio Engine সচল আছে। সরাসরি ভয়েস বা সাউন্ড ইফেক্ট বানাতে নিচের Audio Control Box ব্যবহার করো।",
            }

        if provider == "runway":
            return {
                "ok": True,
                "text": f"🎥 Runway ({model}) প্রস্তুত আছে। সিন প্রম্পট: {prompt[:180]}",
            }

        if provider == "google":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            contents = []
            for h in history[-12:]:
                txt = (h.get("content") or "").strip()
                if not txt:
                    continue
                role = "user" if h.get("role") == "user" else "model"
                contents.append({"role": role, "parts": [{"text": txt}]})
            contents.append({"role": "user", "parts": [{"text": prompt}]})
            payload: Dict[str, Any] = {"contents": contents}
            if system_prompt:
                payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

            r = await client.post(url, json=payload, timeout=40)
            if r.status_code != 200:
                return {"ok": False, "error": f"Google ({r.status_code}): {r.text[:300]}"}
            data = r.json()
            candidates = data.get("candidates") or []
            if not candidates:
                return {"ok": False, "error": "Google থেকে কোনো উত্তর পাওয়া যায়নি (Safety/Empty)।"}
            parts = candidates[0].get("content", {}).get("parts") or []
            text = parts[0].get("text", "") if parts else ""
            if not text:
                return {"ok": False, "error": "Google ফাঁকা উত্তর দিয়েছে।"}
            return {"ok": True, "text": text}

        if provider == "anthropic":
            url = "https://api.anthropic.com/v1/messages"
            msgs = normalize_anthropic_messages(history, prompt)
            payload = {
                "model": model,
                "max_tokens": 1400,
                "system": system_prompt,
                "messages": msgs,
            }
            r = await client.post(
                url,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=40,
            )
            if r.status_code != 200:
                return {"ok": False, "error": f"Anthropic ({r.status_code}): {r.text[:300]}"}
            content_list = r.json().get("content") or []
            text = content_list[0].get("text", "") if content_list else ""
            if not text:
                return {"ok": False, "error": "Anthropic ফাঁকা উত্তর দিয়েছে।"}
            return {"ok": True, "text": text}

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
        for h in history[-12:]:
            txt = (h.get("content") or "").strip()
            if txt:
                role = "user" if h.get("role") == "user" else "assistant"
                messages.append({"role": role, "content": txt})
        messages.append({"role": "user", "content": prompt})

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://ai-video-studio.onrender.com"
            headers["X-Title"] = "AI Video Studio"

        r = await client.post(url, headers=headers, json={"model": model, "messages": messages}, timeout=40)
        if r.status_code != 200:
            return {"ok": False, "error": f"{provider.upper()} ({r.status_code}): {r.text[:300]}"}
        choices = r.json().get("choices") or []
        text = choices[0].get("message", {}).get("content", "") if choices else ""
        if not text:
            return {"ok": False, "error": f"{provider.upper()} ফাঁকা উত্তর দিয়েছে।"}
        return {"ok": True, "text": text}

    except Exception as e:
        return {"ok": False, "error": str(e)}


async def call_agent_with_fallbacks(
    client: httpx.AsyncClient,
    config: Dict[str, Any],
    prompt: str,
    system_prompt: str = "",
    history: Optional[List[Dict[str, str]]] = None,
    co_work: bool = False,
) -> Dict[str, Any]:
    keys_cfg = config.get("keys", [])
    custom_url = config.get("customUrl", "")

    candidates = []
    for slot in keys_cfg:
        prov = slot.get("provider", "google")
        mod = slot.get("model", "")
        main_k = (slot.get("apiKey") or "").strip()
        sub_k = (slot.get("subKey") or "").strip()
        if main_k:
            candidates.append((prov, mod, main_k))
        if sub_k:
            candidates.append((prov, mod, sub_k))

    if not candidates:
        return {"ok": False, "error": "কোনো API Key দেওয়া নেই।"}

    if co_work and len(candidates) > 1:
        tasks = [
            call_llm_single_key(client, p, m, k, prompt, system_prompt, history, custom_url)
            for (p, m, k) in candidates[:3]
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok_res = [r for r in results if isinstance(r, dict) and r.get("ok")]
        if not ok_res:
            first_err = results[0].get("error", "Failed") if isinstance(results[0], dict) else str(results[0])
            return {"ok": False, "error": first_err}
        extras = [{"worker": i + 2, "text": r["text"]} for i, r in enumerate(ok_res[1:])]
        return {"ok": True, "text": ok_res[0]["text"], "extras": extras}

    last_err = "Unknown Error"
    for prov, mod, k in candidates:
        res = await call_llm_single_key(client, prov, mod, k, prompt, system_prompt, history, custom_url)
        if res.get("ok"):
            return res
        last_err = res.get("error", "Failed")
    return {"ok": False, "error": last_err}

@app.get("/")
async def serve_index():
    index_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "index.html")
    return FileResponse(index_path)
    

@app.post("/api/auto-detect-key")
async def api_auto_detect_key(request: Request):
    try:
        body = await request.json()
        api_key = (body.get("apiKey") or "").strip()
        user_prov = body.get("provider") or ""
        user_model = (body.get("model") or "").strip()
        custom_url = (body.get("customUrl") or "").strip()
        agent_id = body.get("agentId") or "director"

        if not api_key:
            return JSONResponse({"ok": False, "error": "API Key ফাঁকা।"})

        detected_prov = guess_provider_from_key(api_key, user_prov or "openrouter")

        async with httpx.AsyncClient() as client:
            res = await fetch_provider_models(client, detected_prov, api_key, custom_url)

            if not res.get("ok"):
                probe_list = (
                    ["deepseek", "openrouter", "mistral", "openai"]
                    if api_key.startswith("sk-")
                    else ["mistral", "openrouter", "google"]
                )
                for alt in probe_list:
                    if alt != detected_prov:
                        alt_res = await fetch_provider_models(client, alt, api_key, custom_url)
                        if alt_res.get("ok"):
                            detected_prov = alt
                            res = alt_res
                            break

            models = res.get("models", [])
            auto_model = pick_best_model(models, agent_id, detected_prov)
            chosen_model = user_model if (user_model and (not models or user_model in models)) else auto_model

            return JSONResponse({
                "ok": res.get("ok", False),
                "provider": detected_prov,
                "model": chosen_model,
                "auto_model": auto_model,
                "models": models,
                "model_count": len(models),
                "error": res.get("error", ""),
            })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/api/list-models")
async def api_list_models(request: Request):
    try:
        body = await request.json()
        api_key = (body.get("apiKey") or "").strip()
        provider = body.get("provider") or guess_provider_from_key(api_key)
        custom_url = (body.get("customUrl") or "").strip()
        agent_id = body.get("agentId") or "director"

        async with httpx.AsyncClient() as client:
            res = await fetch_provider_models(client, provider, api_key, custom_url)
            models = res.get("models", [])
            auto_model = pick_best_model(models, agent_id, provider)
            return JSONResponse({
                "ok": res.get("ok", False),
                "provider": provider,
                "models": models,
                "model_count": len(models),
                "auto_model": auto_model,
                "error": res.get("error", ""),
            })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/api/extract-continuity")
async def api_extract_continuity(request: Request):
    """Generates or updates the Character Bible & Story Continuity sheet for Part 2+."""
    try:
        body = await request.json()
        config = body.get("config", {})
        existing_memory = (body.get("existing_memory") or "").strip()
        latest_context = (body.get("latest_context") or "").strip()

        if not latest_context:
            return JSONResponse({"ok": False, "error": "লক করার মতো কোনো কনটেন্ট বা চ্যাট পাওয়া যায়নি।"})

        sys_prompt = (
            "You are a Continuity Supervisor for an AI Video Studio. "
            "Extract and maintain a concise, crystal-clear 'Character Bible & Story Continuity Sheet' "
            "in Bangla + English technical terms so that Part 2, Part 3, etc. keep 100% identical characters, "
            "outfits, art style (2D/3D), lighting, voice tone, and exact plot continuation. "
            "Format with short bullet points: 1) Characters (Exact Face, Hair, Dress, Age), "
            "2) Visual & Art Style, 3) Voice & Audio Style, 4) Story So Far & Where Next Part Starts."
        )
        prompt = (
            f"Previous Character Bible (keep and update if needed):\n{existing_memory or 'None'}\n\n"
            f"Latest Part / Chat / Output:\n{latest_context[:4000]}\n\n"
            "Write the updated Character Bible & Continuity Lock Sheet now:"
        )

                async with httpx.AsyncClient() as client:
            res = await call_agent_with_fallbacks(client, config, prompt, sys_prompt, [], False)
            if not res.get("ok"):
                return JSONResponse({"ok": False, "error": res.get("error", "Continuity তৈরি করা যায়নি")})
            return JSONResponse({"ok": True, "memory": res["text"]})
                    
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


async def run_job_task(job_id: str, payload: Dict[str, Any]) -> None:
    try:
        job_type = payload.get("type", "single")
        project_memory = payload.get("project_memory", "")

        async with httpx.AsyncClient() as client:
            if job_type == "single":
                full_sys = inject_continuity(payload.get("system_prompt", ""), project_memory)
                res = await call_agent_with_fallbacks(
                    client,
                    payload.get("config", {}),
                    payload.get("prompt", ""),
                    full_sys,
                    payload.get("history", []),
                    payload.get("co_work", False),
                )
                if JOBS.get(job_id, {}).get("status") == "cancelled":
                    return
                mem_note = " (Character Bible লক করা আছে 🔒)" if (project_memory or "").strip() else ""
                team_logs = [
                    {
                        "from": "User",
                        "to": "Director AI",
                        "msg": (payload.get("prompt", "") or "")[:120],
                        "status": "Received ✅",
                    },
                    {
                        "from": "Director AI",
                        "to": "Studio Team",
                        "msg": (
                            f"গল্প ও দৃশ্যপট বিশ্লেষণ করে টিমের জন্য পরিকল্পনা তৈরি করা হয়েছে{mem_note}।"
                            if res.get("ok")
                            else f"এরর: {res.get('error', '')[:80]}"
                        ),
                        "status": "Aligned ✅" if res.get("ok") else "Error ❌",
                    },
                ]
                res["team_logs"] = team_logs
                JOBS[job_id]["status"] = "done" if res.get("ok") else "error"
                JOBS[job_id]["result"] = res

            elif job_type == "multi":
                tasks_in = payload.get("tasks", [])
                team_logs = []

                async def run_one(t: Dict[str, Any]) -> Dict[str, Any]:
                    agent_sys = inject_continuity(t.get("system_prompt", ""), project_memory)
                    r = await call_agent_with_fallbacks(
                        client,
                        t.get("config", {}),
                        t.get("prompt", ""),
                        agent_sys,
                        [],
                        t.get("co_work", False),
                    )
                    r["agent_id"] = t.get("agent_id")
                    r["agent_name"] = t.get("agent_name")
                    team_logs.append({
                        "from": "Director AI",
                        "to": t.get("agent_name"),
                        "msg": f"ক্যারেক্টার ও সিন নির্দেশনা পাঠানো হয়েছে: {(t.get('prompt', '') or '')[:90]}...",
                        "status": "Aligned ✅" if r.get("ok") else "Needs Fix ⚠️",
                    })
                    if r.get("ok"):
                        team_logs.append({
                            "from": t.get("agent_name"),
                            "to": "Director AI",
                            "msg": (r.get("text", "") or "")[:140] + "...",
                            "status": "Ready ✅",
                        })
                    return r

                results = await asyncio.gather(*[run_one(t) for t in tasks_in], return_exceptions=True)
                clean_results = [
                    r if isinstance(r, dict) else {"ok": False, "error": str(r), "agent_name": "Agent"}
                    for r in results
                ]
                if JOBS.get(job_id, {}).get("status") == "cancelled":
                    return
                JOBS[job_id]["status"] = "done"
                JOBS[job_id]["result"] = {"ok": True, "results": clean_results, "team_logs": team_logs}
    except Exception as e:
        if job_id in JOBS and JOBS[job_id].get("status") != "cancelled":
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["result"] = {"ok": False, "error": f"Server Job Error: {str(e)}"}


@app.post("/api/start-job")
async def api_start_job(request: Request):
    try:
        cleanup_old_jobs()
        payload = await request.json()
        job_id = str(uuid.uuid4())[:10]
        JOBS[job_id] = {"status": "running", "result": None}
        asyncio.create_task(run_job_task(job_id, payload))
        return JSONResponse({"ok": True, "job_id": job_id})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.get("/api/job/{job_id}")
async def api_get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return JSONResponse({"ok": False, "status": "not_found"})
    return JSONResponse({"ok": True, "status": job["status"], "result": job["result"]})


@app.post("/api/cancel-job/{job_id}")
async def api_cancel_job(job_id: str):
    if job_id in JOBS:
        JOBS[job_id]["status"] = "cancelled"
    return JSONResponse({"ok": True})


# --- ElevenLabs Audio Studio Control Box Endpoints ---
@app.post("/api/elevenlabs/voices")
async def el_voices(request: Request):
    try:
        body = await request.json()
        api_key = (body.get("apiKey") or "").strip()
        if not api_key:
            return JSONResponse({"ok": False, "error": "ElevenLabs API Key নেই।"})
        async with httpx.AsyncClient() as client:
            r = await client.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": api_key}, timeout=15)
            if r.status_code != 200:
                return JSONResponse({"ok": False, "error": r.text[:250]})
            voices = [
                {"voice_id": v["voice_id"], "name": v["name"], "category": v.get("category", "")}
                for v in r.json().get("voices", [])
                if isinstance(v, dict) and v.get("voice_id")
            ]
            return JSONResponse({"ok": True, "voices": voices})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/api/elevenlabs/history")
async def el_history(request: Request):
    try:
        body = await request.json()
        api_key = (body.get("apiKey") or "").strip()
        if not api_key:
            return JSONResponse({"ok": False, "error": "ElevenLabs API Key নেই।"})
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.elevenlabs.io/v1/history?page_size=10",
                headers={"xi-api-key": api_key},
                timeout=15,
            )
            if r.status_code != 200:
                return JSONResponse({"ok": False, "error": r.text[:250]})
            items = [
                {"id": h["history_item_id"], "voice": h.get("voice_name", ""), "text": (h.get("text") or "")[:80]}
                for h in r.json().get("history", [])
                if isinstance(h, dict) and h.get("history_item_id")
            ]
            return JSONResponse({"ok": True, "history": items})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/api/elevenlabs/tts")
async def el_tts(request: Request):
    try:
        body = await request.json()
        api_key = (body.get("apiKey") or "").strip()
        voice_id = (body.get("voiceId") or "21m00Tcm4TlvDq8ikWAM").strip()
        text = (body.get("text") or "").strip()
        model_id = (body.get("model") or "eleven_multilingual_v2").strip()
        if not api_key or not text:
            return JSONResponse({"ok": False, "error": "API Key এবং টেক্সট দুটোই দিতে হবে।"})
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                json={"text": text, "model_id": model_id},
                timeout=35,
            )
            if r.status_code != 200:
                return JSONResponse({"ok": False, "error": r.text[:250]})
            b64 = base64.b64encode(r.content).decode("utf-8")
            return JSONResponse({"ok": True, "audio_base64": f"data:audio/mpeg;base64,{b64}"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/api/elevenlabs/sfx")
async def el_sfx(request: Request):
    try:
        body = await request.json()
        api_key = (body.get("apiKey") or "").strip()
        text = (body.get("text") or "").strip()
        if not api_key or not text:
            return JSONResponse({"ok": False, "error": "API Key এবং সাউন্ড ইফেক্টের বর্ণনা দুটোই দিতে হবে।"})
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.elevenlabs.io/v1/sound-generation",
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                json={"text": text},
                timeout=35,
            )
            if r.status_code != 200:
                return JSONResponse({"ok": False, "error": r.text[:250]})
            b64 = base64.b64encode(r.content).decode("utf-8")
            return JSONResponse({"ok": True, "audio_base64": f"data:audio/mpeg;base64,{b64}"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})
        
