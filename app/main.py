# ==============================================================================
# AI Video Production Studio - FastAPI Application & Live Routes (Part D2)
# Covers: Static UI Mounting, 3-Tier Key Auto-Detect, Slot Controls, Smart Chat
#         vs Production Intent Guard, File Uploads, Spec Approval & Live SSE
# ==============================================================================

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import (
    AGENT_DEFINITIONS,
    AGENT_ORDER,
    OUTPUTS_DIR,
    STATIC_DIR,
    UPLOADS_DIR,
    ensure_workspace_dirs,
    get_all_providers,
)
from app.director_engine import direct_agent_chat_reply
from app.models import (
    AgentId,
    ApplyKeyRequest,
    ApproveSpecRequest,
    DetectKeyRequest,
    DirectAgentChatRequest,
    PromptRequest,
    SaveProjectRequest,
    SelfHealRequest,
    SelfSwitchRequest,
    TestAgentRequest,
)
from app.orchestrator import orchestrator
from app.provider_engine import auto_detect_api_key

ensure_workspace_dirs()
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AI Video Production Studio", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static frontend assets and generated media outputs
app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ------------------------------------------------------------------------------
# 1. SMART INTENT GUARD (CASUAL GREETING VS VIDEO/MEDIA PRODUCTION)
# ------------------------------------------------------------------------------
CASUAL_PATTERNS = {
    "hi", "hello", "hey", "hii", "yo", "sup", "good morning", "good evening",
    "how are you", "who are you", "help", "test", "ok", "okay", "thanks", "thank you",
    "হাই", "হ্যালো", "কেমন আছো", "কেমন আছেন", "তুমি কে", "ধন্যবাদ", "ঠিক আছে", "হুম",
}

PRODUCTION_KEYWORDS = (
    "video", "image", "photo", "dub", "anime", "story", "reel", "short",
    "music", "beat", "sync", "edit", "thumbnail", "2d", "3d", "cartoon",
    "ভিডিও", "ছবি", "ডাবিং", "গল্প", "কার্টুন", "গান", "এডিট", "শর্ট", "থাম্বনেইল",
)


def _is_casual_chat(prompt: str, youtube_url: Optional[str] = None) -> bool:
    """Prevent accidental video generation on simple greetings like 'Hi' or 'হাই'."""
    if youtube_url and youtube_url.strip():
        return False
    clean = re.sub(r"[?!.,।]+$", "", (prompt or "").strip().lower()).strip()
    if not clean or clean in CASUAL_PATTERNS:
        return True
    words = clean.split()
    if len(words) <= 2 and not any(k in clean for k in PRODUCTION_KEYWORDS):
        return True
    return False


# ------------------------------------------------------------------------------
# 2. ROOT UI & INITIAL BOOTSTRAP ENDPOINT
# ------------------------------------------------------------------------------
@app.get("/")
async def serve_studio_ui() -> FileResponse:
    """Serve the sleek dark-cinema studio workspace."""
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend index.html not yet uploaded.")
    return FileResponse(str(index_file))


@app.get("/api/health")
async def health_check() -> Dict[str, Any]:
    return {"status": "ok", "studio": "AI Video Production Studio"}


@app.get("/api/bootstrap")
async def get_bootstrap_state(project_id: Optional[str] = None) -> Dict[str, Any]:
    """Return initial providers registry, 5-agent slots, and active project state."""
    project = orchestrator.get_or_create_project(project_id)
    return {
        "agents_meta": AGENT_DEFINITIONS,
        "agent_order": AGENT_ORDER,
        "providers": get_all_providers(),
        "studio": orchestrator.get_studio_snapshot(),
        "project": project.model_dump(),
        "saved_projects": orchestrator.list_projects(),
    }


# ------------------------------------------------------------------------------
# 3. API KEY 3-TIER AUTO-DETECT, SLOT ASSIGNMENT, UNDO, HEAL & SWITCH
# ------------------------------------------------------------------------------
@app.post("/api/keys/detect")
async def detect_key_endpoint(req: DetectKeyRequest) -> Dict[str, Any]:
    return await auto_detect_api_key(
        api_key=req.api_key,
        custom_base_url=req.custom_base_url,
        preferred_provider=req.preferred_provider,
    )


@app.post("/api/keys/apply")
async def apply_key_endpoint(req: ApplyKeyRequest) -> Dict[str, Any]:
    studio = orchestrator.apply_api_key(
        provider_id=req.provider_id,
        api_key=req.api_key,
        target_agents=req.target_agents,
        selected_models=req.selected_models,
        base_url=req.base_url,
        is_free_tier=req.is_free_tier,
    )
    return {"ok": True, "studio": studio}


@app.delete("/api/keys/{agent_id}/{slot_id}")
async def remove_slot_endpoint(agent_id: AgentId, slot_id: str) -> Dict[str, Any]:
    studio = orchestrator.remove_slot(agent_id, slot_id)
    return {"ok": True, "studio": studio}


@app.post("/api/keys/undo")
async def undo_keys_endpoint() -> Dict[str, Any]:
    studio = orchestrator.undo_last_change()
    return {"ok": True, "studio": studio}


@app.post("/api/agents/{agent_id}/power")
async def set_agent_power_endpoint(agent_id: AgentId, payload: Dict[str, str]) -> Dict[str, Any]:
    level = payload.get("power_level", "High")
    studio = orchestrator.set_agent_power(agent_id, level)
    return {"ok": True, "studio": studio}


@app.post("/api/agents/test")
async def test_agent_endpoint(req: TestAgentRequest) -> Dict[str, Any]:
    return await orchestrator.test_agent_slot(req.agent_id, req.slot_id)


@app.post("/api/agents/heal")
async def heal_agent_endpoint(req: SelfHealRequest) -> Dict[str, Any]:
    return await orchestrator.self_heal_agent(req.agent_id, req.slot_id)


@app.post("/api/agents/switch")
async def switch_agent_endpoint(req: SelfSwitchRequest) -> Dict[str, Any]:
    project = orchestrator.get_or_create_project()
    return orchestrator.self_switch_agent(req.agent_id, project)
  # ------------------------------------------------------------------------------
# 4. RESOURCE UPLOADS (IMAGE / VIDEO / AUDIO BEAT-DSP / YOUTUBE LINK)
# ------------------------------------------------------------------------------
@app.post("/api/resources/upload")
async def upload_resource_endpoint(
    file: UploadFile = File(...),
    project_id: Optional[str] = Form(None),
) -> Dict[str, Any]:
    """Save uploaded image, video, or music file and analyze Beat-Sync DSP if audio."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    orig_name = file.filename or "upload.bin"
    ext = Path(orig_name).suffix.lower()
    ctype = (file.content_type or "").lower()

    if ctype.startswith("image/") or ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        kind = "image"
        ext = ext or ".png"
    elif ctype.startswith("audio/") or ext in (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"):
        kind = "audio"
        ext = ext or ".mp3"
    elif ctype.startswith("video/") or ext in (".mp4", ".mov", ".webm", ".mkv", ".avi"):
        kind = "video"
        ext = ext or ".mp4"
    else:
        await file.close()
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {orig_name}")

    saved_name = f"{uuid.uuid4().hex[:10]}{ext}"
    dest_path = UPLOADS_DIR / saved_name
    try:
        content = await file.read()
    finally:
        await file.close()

    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    dest_path.write_bytes(content)

    res = await orchestrator.add_resource(
        project_id=project_id,
        kind=kind,
        name=orig_name,
        path_or_url=str(dest_path),
        mime_type=ctype,
    )
    res["public_url"] = f"/uploads/{saved_name}"
    return res


@app.post("/api/resources/youtube")
async def add_youtube_resource_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    url = str(payload.get("youtube_url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="YouTube URL is required.")
    return await orchestrator.add_resource(
        project_id=payload.get("project_id"),
        kind="youtube",
        name=url,
        path_or_url=url,
    )


# ------------------------------------------------------------------------------
# 5. DIRECTOR PROMPT, SPEC APPROVAL, STOP/CANCEL & DIRECT 5-AGENT CHAT
# ------------------------------------------------------------------------------
@app.post("/api/director/plan")
async def director_plan_endpoint(req: PromptRequest) -> Dict[str, Any]:
    """Handle user prompt: reply conversationally on greetings, or launch Director Spec plan."""
    project = orchestrator.get_or_create_project(req.project_id)

    if _is_casual_chat(req.prompt, req.youtube_url):
        orchestrator.add_chat(project, "user", req.prompt.strip())
        dir_slot, _ = orchestrator.resolve_slots("director", project)
        reply = (
            "হ্যালো! আমি আপনার AI Video Production Studio-র Director। "
            "উপরের Settings থেকে API Key যুক্ত করে আপনার ভিডিওর গল্প বা নির্দেশ লিখুন—আমি সাথে সাথে কাজ শুরু করে দেব!"
        )
        if dir_slot:
            try:
                reply = await direct_agent_chat_reply(
                    "director",
                    req.prompt.strip(),
                    "User greeted the studio. Reply warmly in their language and ask what video, photo edit, or dubbing they want to create.",
                    dir_slot,
                )
            except Exception:
                pass
        orchestrator.add_chat(project, "director", reply, tone="info")
        return {"mode": "chat", "project": project.model_dump()}

    updated_proj = await orchestrator.start_director_planning(
        prompt=req.prompt,
        project_id=project.project_id,
        youtube_url=req.youtube_url,
    )
    return {"mode": "plan", "project": updated_proj.model_dump()}


@app.post("/api/director/approve")
async def approve_spec_endpoint(req: ApproveSpecRequest) -> Dict[str, Any]:
    """Approve Left-Corner Spec Inspector and launch background multi-agent production."""
    updated_proj = await orchestrator.approve_and_produce(req.project_id, req.spec)
    return {"ok": True, "project": updated_proj.model_dump()}


@app.post("/api/projects/{project_id}/stop")
async def stop_production_endpoint(project_id: str) -> Dict[str, Any]:
    """Cancel active background generation and unlock prompt & Spec Inspector for editing."""
    project = orchestrator.get_or_create_project(project_id)
    task = orchestrator.running_tasks.get(project.project_id)
    if task and not task.done():
        task.cancel()

    if project.spec.lifecycle == "approved":
        project.spec.lifecycle = "populated"
    project.status = "awaiting_approval" if project.spec.lifecycle == "populated" else "idle"
    orchestrator.persist_project(project)

    orchestrator.emit_workflow(
        project, "director",
        "Production stopped by user. Workspace & Spec Inspector unlocked for editing.",
        "ব্যবহারকারীর নির্দেশে কাজ থামানো হয়েছে—এখন প্রম্পট বা স্পেক এডিট করতে পারবেন।",
        event_type="log",
        meta={"stopped": True},
    )
    orchestrator.broadcast("project_update", project.model_dump())
    return {"ok": True, "project": project.model_dump()}


@app.post("/api/agents/chat")
async def direct_agent_chat_endpoint(req: DirectAgentChatRequest) -> Dict[str, Any]:
    try:
        return await orchestrator.handle_direct_agent_chat(
            agent_id=req.agent_id,
            message=req.message,
            project_id=req.project_id,
        )
    except Exception as exc:
        return {
            "reply": f"[{req.agent_id.upper()} Agent] সংযোগে সমস্যা হয়েছে: {str(exc)[:140]}",
            "error": str(exc),
        }


# ------------------------------------------------------------------------------
# 6. PROJECT SAVE / LOAD / NEW & LIVE SSE EVENT STREAM
# ------------------------------------------------------------------------------
@app.get("/api/projects")
async def list_projects_endpoint() -> Dict[str, Any]:
    return {"projects": orchestrator.list_projects()}


@app.post("/api/projects/new")
async def new_project_endpoint() -> Dict[str, Any]:
    pid = f"proj_{uuid.uuid4().hex[:8]}"
    proj = orchestrator.get_or_create_project(pid)
    return {"project": proj.model_dump(), "saved_projects": orchestrator.list_projects()}


@app.post("/api/projects/save")
async def save_project_endpoint(req: SaveProjectRequest) -> Dict[str, Any]:
    proj_data = orchestrator.save_project_as(req.project_id, req.name)
    return {"ok": True, "project": proj_data, "saved_projects": orchestrator.list_projects()}


@app.get("/api/projects/{project_id}")
async def load_project_endpoint(project_id: str) -> Dict[str, Any]:
    proj = orchestrator.get_or_create_project(project_id)
    return {"project": proj.model_dump()}


@app.get("/api/stream")
async def studio_sse_stream(request: Request) -> StreamingResponse:
    """Real-time Server-Sent Events stream for live LEDs, White-Light transfers & progress."""
    queue = orchestrator.subscribe()

    async def event_generator():
        try:
            yield f"event: ping\ndata: {json.dumps({'ok': True})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    ev_name = msg.get("event", "message")
                    data_str = json.dumps(msg.get("data", {}), ensure_ascii=False)
                    yield f"event: {ev_name}\ndata: {data_str}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            orchestrator.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
  )
  
