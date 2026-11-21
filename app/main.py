from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path
import urllib.request
import urllib.error
import json
import asyncio

app = FastAPI()


def _http_post_json(url: str, payload: dict, headers: dict, timeout: int = 45):
    data = json.dumps(payload).encode("utf-8")
    req_headers = {
        "Content-Type": "application/json",
        "User-Agent": "AI-Video-Studio/1.0"
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


async def call_single_key(provider: str, model: str, custom_url: str, api_key: str, prompt: str, system_prompt: str = "", history: list = None):
    provider = (provider or "google").lower().strip()
    model = (model or "").strip()
    custom_url = (custom_url or "").strip()
    history = history or []

    if provider == "google":
        use_model = model or "gemini-2.5-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{use_model}:generateContent?key={api_key}"
        contents = []
        for m in history[-10:]:
            role = "model" if m.get("role") == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": str(m.get("content", ""))}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})
        payload = {"contents": contents}
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
        status, raw = await asyncio.to_thread(_http_post_json, url, payload, {})
        if status == 200:
            data = json.loads(raw)
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return {"ok": True, "text": text}
        return {"ok": False, "error": f"Google Error {status}: {raw[:200]}"}

    else:
        if provider == "openrouter":
            url = "https://openrouter.ai/api/v1/chat/completions"
            use_model = model or "google/gemini-2.0-flash-exp:free"
        elif provider == "openai":
            url = "https://api.openai.com/v1/chat/completions"
            use_model = model or "gpt-4o-mini"
        else:
            url = custom_url or "https://openrouter.ai/api/v1/chat/completions"
            use_model = model or "gpt-4o-mini"

        headers = {"Authorization": f"Bearer {api_key}"}
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for m in history[-10:]:
            role = "assistant" if m.get("role") == "assistant" else "user"
            messages.append({"role": role, "content": str(m.get("content", ""))})
        messages.append({"role": "user", "content": prompt})

        payload = {"model": use_model, "messages": messages}
        status, raw = await asyncio.to_thread(_http_post_json, url, payload, headers)
        if status == 200:
            data = json.loads(raw)
            text = data["choices"][0]["message"]["content"]
            return {"ok": True, "text": text}
        return {"ok": False, "error": f"API Error {status}: {raw[:200]}"}


async def call_ai_provider(config: dict, prompt: str, system_prompt: str = "", history: list = None, co_work: bool = False):
    provider = config.get("provider", "google")
    model = config.get("model", "")
    custom_url = config.get("customUrl", "")
    keys = [k.strip() for k in [config.get("key1", ""), config.get("key2", ""), config.get("key3", "")] if k and k.strip()]

    if not keys:
        return {"ok": False, "error": "কোনো API Key দেওয়া হয়নি।"}

    if co_work and len(keys) > 1:
        tasks = [
            call_single_key(provider, model, custom_url, k, f"[Co-Work Worker #{i+1}]\n{prompt}", system_prompt, history)
            for i, k in enumerate(keys)
        ]
        results = await asyncio.gather(*tasks)
        successful = [r for r in results if r.get("ok")]
        if successful:
            return {
                "ok": True,
                "text": successful[0]["text"],
                "extras": [r["text"] for r in successful[1:]],
                "co_worked": len(successful),
                "used_key": 1
            }
        return {"ok": False, "error": results[0].get("error", "Co-Work এরর হয়েছে।")}

    last_error = "Unknown error"
    for idx, k in enumerate(keys):
        res = await call_single_key(provider, model, custom_url, k, prompt, system_prompt, history)
        if res.get("ok"):
            res["used_key"] = idx + 1
            return res
        last_error = res.get("error", "Error")

    return {"ok": False, "error": last_error}


@app.get("/", response_class=HTMLResponse)
def home():
    html_file = Path("index.html")
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    return "<h1>AI Video Studio Backend Ready</h1>"


@app.post("/api/test-key")
async def test_key(request: Request):
    body = await request.json()
    config = body.get("config", {})
    res = await call_ai_provider(config, "Reply with only: OK", "You are a connection tester.")
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
            "error": res.get("error", "")
        }

    results = await asyncio.gather(*[_run_one(t) for t in tasks_cfg])
    return JSONResponse({"ok": True, "results": results})
                                    
