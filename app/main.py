from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path
import urllib.request
import urllib.error
import json
import asyncio
import uuid
import time

app = FastAPI()

JOBS = {}
JOB_TASKS = {}

PROVIDER_DEFAULTS = {
    "google": {
        "model": "gemini-2.5-flash"
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "model": "openrouter/free"
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o-mini"
    },
    "anthropic": {
        "url": "https://api.anthropic.com/v1/messages",
        "model": "claude-3-5-sonnet-latest"
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama-3.3-70b-versatile"
    },
    "deepseek": {
        "url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-chat"
    },
    "mistral": {
        "url": "https://api.mistral.ai/v1/chat/completions",
        "model": "mistral-small-latest"
    },
    "custom": {
        "url": "",
        "model": "gpt-4o-mini"
    }
}


def detect_provider_from_key(api_key: str) -> str:
    k = (api_key or "").strip()
    if k.startswith("AIza"):
        return "google"
    if k.startswith("sk-or-"):
        return "openrouter"
    if k.startswith("sk-ant-"):
        return "anthropic"
    if k.startswith("gsk_"):
        return "groq"
    if k.startswith("sk-proj-") or k.startswith("sk-"):
        return "openai"
    return ""


def _http_get_json(url: str, headers: dict, timeout: int = 20):
    req_headers = {"User-Agent": "AI-Video-Studio/6.0"}
    req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return e.code, err_body
    except Exception as e:
        return 0, str(e)


def _http_post_json(url: str, payload: dict, headers: dict, timeout: int = 90):
    data = json.dumps(payload).encode("utf-8")
    req_headers = {
        "Content-Type": "application/json",
        "User-Agent": "AI-Video-Studio/6.0"
    }
    req_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return e.code, err_body
    except Exception as e:
        return 0, str(e)


async def fetch_live_models(provider: str, api_key: str, custom_url: str = ""):
    provider = (provider or "google").lower().strip()
    api_key = (api_key or "").strip()
    default_model = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["custom"]).get("model", "")
    models = []

    if provider == "google":
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        status, raw = await asyncio.to_thread(_http_get_json, url, {}, 20)
        if status == 200:
            try:
                data = json.loads(raw)
                for m in data.get("models", []):
                    if "generateContent" in m.get("supportedGenerationMethods", []):
                        name = m.get("name", "").replace("models/", "")
                        if name:
                            models.append(name)
            except Exception:
                pass
        best = default_model
        for pref in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.5-pro", "gemini-1.5-flash"]:
            if pref in models:
                best = pref
                break
        if models and best not in models:
            best = models[0]
        if not models:
            models = [best] if best else ["gemini-2.5-flash"]
        return best, models

    if provider == "openrouter":
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        status, raw = await asyncio.to_thread(_http_get_json, "https://openrouter.ai/api/v1/models", headers, 20)
        free_models = []
        paid_models = []
        if status == 200:
            try:
                data = json.loads(raw)
                for m in data.get("data", []):
                    mid = m.get("id", "")
                    if not mid:
                        continue
                    if ":free" in mid:
                        free_models.append(mid)
                    else:
                        paid_models.append(mid)
            except Exception:
                pass
        models = ["openrouter/free"] + free_models + paid_models[:180]
        return "openrouter/free", models

    if provider == "groq":
        status, raw = await asyncio.to_thread(
            _http_get_json,
            "https://api.groq.com/openai/v1/models",
            {"Authorization": f"Bearer {api_key}"},
            20
        )
        if status == 200:
            try:
                data = json.loads(raw)
                models = [m.get("id", "") for m in data.get("data", []) if m.get("id") and "whisper" not in m.get("id", "")]
            except Exception:
                pass
        best = default_model
        for pref in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]:
            if pref in models:
                best = pref
                break
        if models and best not in models:
            best = models[0]
        if not models:
            models = [best]
        return best, models

    if provider == "openai":
        status, raw = await asyncio.to_thread(
            _http_get_json,
            "https://api.openai.com/v1/models",
            {"Authorization": f"Bearer {api_key}"},
            20
        )
        if status == 200:
            try:
                data = json.loads(raw)
                all_ids = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
                models = sorted([x for x in all_ids if x.startswith(("gpt-", "o1", "o3", "o4", "chatgpt"))])
            except Exception:
                pass
        best = default_model
        for pref in ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"]:
            if pref in models:
                best = pref
                break
        if models and best not in models:
            best = models[0]
        if not models:
            models = ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"]
        return best, models

    if provider == "anthropic":
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        status, raw = await asyncio.to_thread(_http_get_json, "https://api.anthropic.com/v1/models", headers, 20)
        if status == 200:
            try:
                data = json.loads(raw)
                models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
            except Exception:
                pass
        if not models:
            models = ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest", "claude-3-7-sonnet-latest"]
        best = default_model if default_model in models else models[0]
        return best, models

    if provider == "deepseek":
        status, raw = await asyncio.to_thread(
            _http_get_json,
            "https://api.deepseek.com/models",
            {"Authorization": f"Bearer {api_key}"},
            20
        )
        if status == 200:
            try:
                data = json.loads(raw)
                models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
            except Exception:
                pass
        if not models:
            models = ["deepseek-chat", "deepseek-reasoner"]
        best = default_model if default_model in models else models[0]
        return best, models

    if provider == "mistral":
        status, raw = await asyncio.to_thread(
            _http_get_json,
            "https://api.mistral.ai/v1/models",
            {"Authorization": f"Bearer {api_key}"},
            20
        )
        if status == 200:
            try:
                data = json.loads(raw)
                models = sorted(list({m.get("id", "") for m in data.get("data", []) if m.get("id")}))
            except Exception:
                pass
        if not models:
            models = ["mistral-small-latest", "mistral-large-latest", "pixtral-12b-2409"]
        best = default_model if default_model in models else models[0]
        return best, models

    return default_model, [default_model] if default_model else []


async def call_single_key(
    provider: str,
    model: str,
    custom_url: str,
    api_key: str,
    prompt: str,
    system_prompt: str = "",
    history: list = None,
    timeout: int = 90
):
    provider = (provider or "google").lower().strip()
    model = (model or "").strip()
    custom_url = (custom_url or "").strip()
    api_key = (api_key or "").strip()
    history = history or []

    if not api_key:
        return {"ok": False, "error": "API Key দেওয়া হয়নি।"}

    defaults = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["custom"])
    use_model = model or defaults.get("model", "")

    if provider == "google":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{use_model}:generateContent?key={api_key}"
        contents = []
        for m in history[-14:]:
            role = "model" if m.get("role") == "assistant" else "user"
            txt = str(m.get("content", "")).strip()
            if txt:
                contents.append({"role": role, "parts": [{"text": txt}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})
        payload = {"contents": contents}
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        status, raw = await asyncio.to_thread(_http_post_json, url, payload, {}, timeout)
        if status == 200:
            try:
                data = json.loads(raw)
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return {"ok": True, "text": text, "model": use_model, "provider": provider}
            except Exception as e:
                return {"ok": False, "error": f"Google Parse Error: {str(e)} | Raw: {raw[:400]}"}
        return {"ok": False, "error": f"Google Error {status}: {raw[:700]}"}

    if provider == "anthropic":
        url = custom_url or defaults["url"]
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
        messages = []
        for m in history[-14:]:
            role = "assistant" if m.get("role") == "assistant" else "user"
            txt = str(m.get("content", "")).strip()
            if txt:
                messages.append({"role": role, "content": txt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": use_model,
            "max_tokens": 2048,
            "messages": messages
        }
        if system_prompt:
            payload["system"] = system_prompt

        status, raw = await asyncio.to_thread(_http_post_json, url, payload, headers, timeout)
        if status == 200:
            try:
                data = json.loads(raw)
                text = data["content"][0]["text"]
                return {"ok": True, "text": text, "model": use_model, "provider": provider}
            except Exception as e:
                return {"ok": False, "error": f"Anthropic Parse Error: {str(e)} | Raw: {raw[:400]}"}
        return {"ok": False, "error": f"Anthropic Error {status}: {raw[:700]}"}

    url = custom_url if (provider == "custom" or custom_url) else defaults.get("url", "")
    if not url:
        return {"ok": False, "error": "Custom Endpoint URL দেওয়া হয়নি।"}

    headers = {"Authorization": f"Bearer {api_key}"}
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://ai-video-studio.local"
        headers["X-Title"] = "AI Video Studio"

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for m in history[-14:]:
        role = "assistant" if m.get("role") == "assistant" else "user"
        txt = str(m.get("content", "")).strip()
        if txt:
            messages.append({"role": role, "content": txt})
    messages.append({"role": "user", "content": prompt})

    payload = {"model": use_model, "messages": messages}
    status, raw = await asyncio.to_thread(_http_post_json, url, payload, headers, timeout)
    if status == 200:
        try:
            data = json.loads(raw)
            text = data["choices"][0]["message"]["content"]
            return {"ok": True, "text": text, "model": use_model, "provider": provider}
        except Exception as e:
            return {"ok": False, "error": f"{provider.upper()} Parse Error: {str(e)} | Raw: {raw[:400]}"}
    return {"ok": False, "error": f"{provider.upper()} Error {status}: {raw[:700]}"}


def extract_key_entries(config: dict):
    custom_url = (config.get("customUrl") or "").strip()
    entries = []
    if isinstance(config.get("keys"), list) and len(config["keys"]) > 0:
        for idx, item in enumerate(config["keys"], start=1):
            api_key = (item.get("apiKey") or "").strip()
            if api_key:
                entries.append({
                    "idx": item.get("idx", idx),
                    "provider": item.get("provider") or config.get("provider") or "google",
                    "model": item.get("model") or "",
                    "customUrl": (item.get("customUrl") or custom_url).strip(),
                    "apiKey": api_key
                })
        return entries

    for idx in (1, 2, 3):
        api_key = (config.get(f"key{idx}") or "").strip()
        if api_key:
            entries.append({
                "idx": idx,
                "provider": config.get(f"provider{idx}") or config.get("provider") or "google",
                "model": config.get(f"model{idx}") or config.get("model") or "",
                "customUrl": custom_url,
                "apiKey": api_key
            })
    return entries


async def call_ai_provider(config: dict, prompt: str, system_prompt: str = "", history: list = None, co_work: bool = False):
    active_keys = extract_key_entries(config)
    if not active_keys:
        return {"ok": False, "error": "কোনো API Key দেওয়া হয়নি।"}

    if co_work and len(active_keys) > 1:
        tasks = [
            call_single_key(
                item["provider"], item["model"], item["customUrl"], item["apiKey"],
                f"[Co-Work Worker #{item['idx']}]\n{prompt}",
                system_prompt, history
            )
            for item in active_keys
        ]
        results = await asyncio.gather(*tasks)
        successful = [(active_keys[i]["idx"], r) for i, r in enumerate(results) if r.get("ok")]
        if successful:
            primary_idx, primary_res = successful[0]
            extras = [{"worker": idx, "text": r["text"]} for idx, r in successful[1:]]
            return {
                "ok": True,
                "text": primary_res["text"],
                "extras": extras,
                "co_worked": len(successful),
                "used_key": primary_idx
            }
        errors = [f"Key #{active_keys[i]['idx']}: {r.get('error', 'Error')}" for i, r in enumerate(results)]
        return {"ok": False, "error": "\n".join(errors)}

    error_log = []
    for item in active_keys:
        res = await call_single_key(
            item["provider"], item["model"], item["customUrl"], item["apiKey"],
            prompt, system_prompt, history
        )
        if res.get("ok"):
            res["used_key"] = item["idx"]
            return res
        error_log.append(f"Key #{item['idx']} ({item['provider']}): {res.get('error', 'Error')}")

    return {"ok": False, "error": "\n".join(error_log)}


def _cleanup_old_jobs():
    now = time.time()
    expired = [jid for jid, j in JOBS.items() if now - j.get("created_at", now) > 3600]
    for jid in expired:
        JOBS.pop(jid, None)
        JOB_TASKS.pop(jid, None)


@app.get("/", response_class=HTMLResponse)
def home():
    html_file = Path("index.html")
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    return "<h1>AI Video Studio Backend Ready</h1>"


@app.post("/api/list-models")
async def list_models(request: Request):
    body = await request.json()
    api_key = (body.get("apiKey") or "").strip()
    given_provider = (body.get("provider") or "").strip()
    custom_url = (body.get("customUrl") or "").strip()

    detected = detect_provider_from_key(api_key)
    provider = detected or given_provider or "google"
    if detected == "openai" and given_provider in ("deepseek", "mistral", "custom"):
        provider = given_provider

    best_model, models = await fetch_live_models(provider, api_key, custom_url)
    return JSONResponse({
        "ok": True,
        "provider": provider,
        "auto_model": best_model,
        "models": models
    })


@app.post("/api/auto-detect-key")
async def auto_detect_key(request: Request):
    body = await request.json()
    api_key = (body.get("apiKey") or "").strip()
    given_provider = (body.get("provider") or "").strip()
    given_model = (body.get("model") or "").strip()
    custom_url = (body.get("customUrl") or "").strip()

    if not api_key:
        return JSONResponse({"ok": False, "error": "API Key ফাঁকা রয়েছে।"})

    detected = detect_provider_from_key(api_key)
    provider = detected or given_provider or "google"
    if detected == "openai" and given_provider in ("deepseek", "mistral", "custom"):
        provider = given_provider

    best_model, models = await fetch_live_models(provider, api_key, custom_url)
    model = given_model or best_model

    res = await call_single_key(
        provider=provider,
        model=model,
        custom_url=custom_url,
        api_key=api_key,
        prompt="Reply with only: OK",
        system_prompt="You are a connection tester.",
        history=[],
        timeout=30
    )

    if res.get("ok"):
        return JSONResponse({
            "ok": True,
            "provider": provider,
            "model": model,
            "auto_model": best_model,
            "models": models
        })

    return JSONResponse({
        "ok": False,
        "provider": provider,
        "model": model,
        "auto_model": best_model,
        "models": models,
        "error": res.get("error", "Unknown Error")
    })


@app.post("/api/test-single-key")
async def test_single_key(request: Request):
    body = await request.json()
    res = await call_single_key(
        provider=body.get("provider", "google"),
        model=body.get("model", ""),
        custom_url=body.get("customUrl", ""),
        api_key=body.get("apiKey", ""),
        prompt="Reply with only: OK",
        system_prompt="You are a connection tester.",
        history=[],
        timeout=35
    )
    return JSONResponse(res)


@app.post("/api/start-job")
async def start_job(request: Request):
    _cleanup_old_jobs()
    body = await request.json()
    job_type = body.get("type", "single")
    job_id = str(uuid.uuid4())[:10]
    JOBS[job_id] = {
        "status": "running",
        "created_at": time.time(),
        "result": None
    }

    async def _worker():
        try:
            if job_type == "multi":
                tasks_cfg = body.get("tasks", [])
                async def _one(item):
                    r = await call_ai_provider(
                        item.get("config", {}),
                        item.get("prompt", ""),
                        item.get("system_prompt", ""),
                        [],
                                        bool(item.get("co_work", False))
                    )
                    return {
                        "agent_id": item.get("agent_id", ""),
                        "agent_name": item.get("agent_name", ""),
                        "ok": r.get("ok", False),
                        "text": r.get("text", ""),
                        "extras": r.get("extras", []),
                        "used_key": r.get("used_key", 0),
                        "error": r.get("error", "")
                    }
                res = await asyncio.gather(*[_one(t) for t in tasks_cfg])
                if JOBS.get(job_id, {}).get("status") != "cancelled":
                    JOBS[job_id]["result"] = {"ok": True, "results": res}
                    JOBS[job_id]["status"] = "done"
            else:
                res = await call_ai_provider(
                    body.get("config", {}),
                    body.get("prompt", ""),
                    body.get("system_prompt", ""),
                    body.get("history", []),
                    bool(body.get("co_work", False))
                )
                if JOBS.get(job_id, {}).get("status") != "cancelled":
                    JOBS[job_id]["result"] = res
                    JOBS[job_id]["status"] = "done"
        except asyncio.CancelledError:
            if job_id in JOBS:
                JOBS[job_id]["status"] = "cancelled"
        except Exception as e:
            if job_id in JOBS:
                JOBS[job_id]["result"] = {"ok": False, "error": str(e)}
                JOBS[job_id]["status"] = "error"
        finally:
            JOB_TASKS.pop(job_id, None)

    task = asyncio.create_task(_worker())
    JOB_TASKS[job_id] = task
    return JSONResponse({"ok": True, "job_id": job_id})


@app.post("/api/cancel-job/{job_id}")
async def cancel_job(job_id: str):
    if job_id in JOBS:
        JOBS[job_id]["status"] = "cancelled"
    task = JOB_TASKS.pop(job_id, None)
    if task and not task.done():
        task.cancel()
    return JSONResponse({"ok": True, "status": "cancelled"})


@app.get("/api/job/{job_id}")
async def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return JSONResponse({"ok": False, "status": "not_found", "error": "Job পাওয়া যায়নি।"})
    return JSONResponse({"ok": True, "status": job["status"], "result": job["result"]})
    
