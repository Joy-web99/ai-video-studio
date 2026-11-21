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

# Background jobs store (keeps running even if phone is minimized)
JOBS = {}

PROVIDER_DEFAULTS = {
    "google": {
        "model": "gemini-3.8-flash"
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "model": "google/gemini-2.0-flash-exp:free"
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


def _http_post_json(url: str, payload: dict, headers: dict, timeout: int = 90):
    data = json.dumps(payload).encode("utf-8")
    req_headers = {
        "Content-Type": "application/json",
        "User-Agent": "AI-Video-Studio/3.0"
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

    # 1. Google Gemini API
    if provider == "google":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{use_model}:generateContent?key={api_key}"
        contents = []
        for m in history[-12:]:
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
                return {"ok": True, "text": text, "model": use_model}
            except Exception as e:
                return {"ok": False, "error": f"Google Parse Error: {str(e)} | Raw: {raw[:400]}"}
        return {"ok": False, "error": f"Google Error {status}: {raw[:700]}"}

    # 2. Anthropic Claude API
    if provider == "anthropic":
        url = custom_url or defaults["url"]
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
        messages = []
        for m in history[-12:]:
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
                return {"ok": True, "text": text, "model": use_model}
            except Exception as e:
                return {"ok": False, "error": f"Anthropic Parse Error: {str(e)} | Raw: {raw[:400]}"}
        return {"ok": False, "error": f"Anthropic Error {status}: {raw[:700]}"}

    # 3. OpenAI-Compatible APIs (OpenRouter, OpenAI, Groq, DeepSeek, Mistral, Custom)
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
    for m in history[-12:]:
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
            return {"ok": True, "text": text, "model": use_model}
        except Exception as e:
            return {"ok": False, "error": f"{provider.upper()} Parse Error: {str(e)} | Raw: {raw[:400]}"}
    return {"ok": False, "error": f"{provider.upper()} Error {status}: {raw[:700]}"}


async def call_ai_provider(config: dict, prompt: str, system_prompt: str = "", history: list = None, co_work: bool = False):
    provider = config.get("provider", "google")
    model = config.get("model", "")
    custom_url = config.get("customUrl", "")
    raw_keys = [
        (1, (config.get("key1") or "").strip()),
        (2, (config.get("key2") or "").strip()),
        (3, (config.get("key3") or "").strip())
    ]
    active_keys = [(idx, k) for idx, k in raw_keys if k]

    if not active_keys:
        return {"ok": False, "error": "কোনো API Key দেওয়া হয়নি।"}

    # Co-Work Mode: Run all provided keys in parallel
    if co_work and len(active_keys) > 1:
        tasks = [
            call_single_key(
                provider, model, custom_url, k,
                f"[Co-Work Worker #{idx}]\n{prompt}",
                system_prompt, history
            )
            for idx, k in active_keys
        ]
        results = await asyncio.gather(*tasks)
        successful = [(active_keys[i][0], r) for i, r in enumerate(results) if r.get("ok")]
        if successful:
            primary_idx, primary_res = successful[0]
            extras = [
                {"worker": idx, "text": r["text"]}
                for idx, r in successful[1:]
            ]
            return {
                "ok": True,
                "text": primary_res["text"],
                "extras": extras,
                "co_worked": len(successful),
                "used_key": primary_idx
            }
        errors = [f"Key #{active_keys[i][0]}: {r.get('error', 'Error')}" for i, r in enumerate(results)]
        return {"ok": False, "error": " | ".join(errors)}

    # Normal / Backup Switching Mode: Try Key 1 -> Key 2 -> Key 3
    error_log = []
    for idx, k in active_keys:
        res = await call_single_key(provider, model, custom_url, k, prompt, system_prompt, history)
        if res.get("ok"):
            res["used_key"] = idx
            return res
        error_log.append(f"Key #{idx}: {res.get('error', 'Error')}")

    return {"ok": False, "error": "\n".join(error_log)}


def _cleanup_old_jobs():
    now = time.time()
    expired = [jid for jid, j in JOBS.items() if now - j.get("created_at", now) > 3600]
    for jid in expired:
        JOBS.pop(jid, None)


@app.get("/", response_class=HTMLResponse)
def home():
    html_file = Path("index.html")
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    return "<h1>AI Video Studio Backend Ready</h1>"


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


@app.post("/api/test-key")
async def test_key(request: Request):
    body = await request.json()
    config = body.get("config", {})
    res = await call_ai_provider(config, "Reply with only: OK", "You are a connection tester.", [], False)
    return JSONResponse(res)


@app.post("/api/run-agent")
async def run_agent(request: Request):
    body = await request.json()
    config = body.get("config", {})
    prompt = body.get("prompt", "")
    system_prompt = body.get("system_prompt", "")
    history = body.get("history", [])
    co_work = bool(body.get("co_work", False))
    res = await call_ai_provider(config, prompt, system_prompt, history, co_work)
    return JSONResponse(res)


@app.post("/api/run-multi")
async def run_multi(request: Request):
    body = await request.json()
    tasks_cfg = body.get("tasks", [])

    async def _run_one(item):
        res = await call_ai_provider(
            item.get("config", {}),
            item.get("prompt", ""),
            item.get("system_prompt", ""),
            [],
            bool(item.get("co_work", False))
        )
        return {
            "agent_id": item.get("agent_id", ""),
            "agent_name": item.get("agent_name", ""),
            "ok": res.get("ok", False),
            "text": res.get("text", ""),
            "extras": res.get("extras", []),
            "used_key": res.get("used_key", 0),
            "error": res.get("error", "")
        }

    results = await asyncio.gather(*[_run_one(t) for t in tasks_cfg])
    return JSONResponse({"ok": True, "results": results})


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
                JOBS[job_id]["result"] = {"ok": True, "results": res}
            else:
                res = await call_ai_provider(
                    body.get("config", {}),
                    body.get("prompt", ""),
                    body.get("system_prompt", ""),
                    body.get("history", []),
                    bool(body.get("co_work", False))
                )
                JOBS[job_id]["result"] = res
            JOBS[job_id]["status"] = "done"
        except Exception as e:
            JOBS[job_id]["result"] = {"ok": False, "error": str(e)}
            JOBS[job_id]["status"] = "error"

    asyncio.create_task(_worker())
    return JSONResponse({"ok": True, "job_id": job_id})


@app.get("/api/job/{job_id}")
async def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return JSONResponse({"ok": False, "status": "not_found", "error": "Job পাওয়া যায়নি।"})
    return JSONResponse({"ok": True, "status": job["status"], "result": job["result"]})
                                 
