"""
AI Video Production Studio - FastAPI Application & Live Routes.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import AGENTS, AGENT_ORDER, OUTPUTS_DIR, STATIC_DIR, UPLOADS_DIR, PROVIDERS
from app.models import (
    ApplyKeyRequest, ApproveSpecRequest, DetectKeyRequest, PromptRequest,
    SaveProjectRequest, TestAgentRequest, SelfSwitchRequest, ProjectState, Asset
)
from app.key_orchestrator import orchestrator
from app.providers import probe_single_provider
from app.intent_guard import classify_intent
from app.director import build_director_plan, direct_agent_chat_reply, learn_youtube_style_dna
from app.doctor import run_full_doctor_check
from app.ffmpeg_engine import probe_media, create_cinematic_clip, assemble_final_video
from app.video_engine import generate_video_clip
from app.audio_engine import generate_narration_audio, analyze_audio_beats_sync
from app.security import sanitize_orchestrator_state, sanitize_filename

app = FastAPI(title="AI Video Production Studio", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

ACTIVE_PROJECTS: Dict[str, ProjectState] = {}
SSE_QUEUES: Dict[str, asyncio.Queue] = {}
RUNNING_TASKS: Dict[str, asyncio.Task] = {}

def get_project(pid: str) -> ProjectState:
    if pid not in ACTIVE_PROJECTS:
        ACTIVE_PROJECTS[pid] = ProjectState(project_id=pid)
    return ACTIVE_PROJECTS[pid]

def broadcast(project_id: str, event_type: str, data: dict):
    if project_id in SSE_QUEUES:
        try:
            SSE_QUEUES[project_id].put_nowait({"event": event_type, "data": data})
        except Exception:
            pass

@app.get("/")
async def serve_ui():
    index_file = STATIC_DIR / "index.html"
    return FileResponse(str(index_file))

@app.get("/api/health")
async def health_check():
    return {"status": "ok"}

@app.get("/api/bootstrap")
async def get_bootstrap_state(project_id: str = "default"):
    project = get_project(project_id)
    raw_orch = {k: v.model_dump() for k, v in orchestrator.agents.items()}
    return {
        "agents": AGENTS, "agent_order": AGENT_ORDER, "providers": PROVIDERS,
        "project": project.model_dump(), "orchestrator": sanitize_orchestrator_state(raw_orch)
    }

class DetectKeyRequestExt(DetectKeyRequest):
    mode: Optional[str] = "free" # free or paid

@app.post("/api/keys/detect")
async def detect_key(req: DetectKeyRequestExt):
    from app.config import detect_provider_by_key
    pid = req.preferred_provider or detect_provider_by_key(req.api_key)
    if not pid:
        return {"ok": False, "error": "Unknown key format."}
    
    res = await probe_single_provider(pid, req.api_key)
    models = res.get("models", [])
    
    # Free / Paid Filtering Logic
    if req.mode == "free":
        free_models = [m for m in models if "free" in m.lower()]
        if free_models: models = free_models
    elif req.mode == "paid":
        paid_models = [m for m in models if "free" not in m.lower()]
        if paid_models: models = paid_models
        
    return {"ok": res.get("ok", False), "provider": pid, "models": models, "error": res.get("error", "")}

@app.post("/api/keys/apply")
async def apply_key(req: ApplyKeyRequest):
    for agent in req.target_agents:
        # If model is "auto", select the first available from the list
        model = req.selected_models.get(agent, "auto")
        orchestrator.apply_key(agent, "primary", req.provider_id, model, req.api_key, req.base_url)
    raw_orch = {k: v.model_dump() for k, v in orchestrator.agents.items()}
    return {"ok": True, "orchestrator": sanitize_orchestrator_state(raw_orch)}

@app.post("/api/agents/test")
async def test_agent(req: TestAgentRequest):
    res = await orchestrator.test_slot(req.agent_id, req.slot_id)
    raw_orch = {k: v.model_dump() for k, v in orchestrator.agents.items()}
    return {"ok": res.get("ok", False), "result": res, "orchestrator": sanitize_orchestrator_state(raw_orch)}

@app.post("/api/doctor/check")
async def doctor_check():
    return await run_full_doctor_check()

@app.post("/api/director/plan")
async def director_plan(req: PromptRequest):
    proj = get_project(req.project_id or "default")
    
    if classify_intent(req.prompt, bool(req.youtube_url)) == "chat":
        slot = orchestrator.get_active_slot("director", "TXT")
        reply = "হ্যালো! আমি আপনার AI Director। কী বানাতে চান বলুন।"
        if slot:
            try: reply = await direct_agent_chat_reply("director", req.prompt, slot)
            except: pass
        return {"mode": "chat", "reply": reply}

    youtube_dna = None
    if req.youtube_url:
        broadcast(proj.project_id, "log", {"msg": "Analyzing YouTube style..."})
        director_slot = orchestrator.get_active_slot("director", "TXT")
        try:
            youtube_dna = await learn_youtube_style_dna(req.youtube_url, director_slot)
            broadcast(proj.project_id, "log", {"msg": f"Style Learned: {youtube_dna.get('visual_style')}"})
        except: pass

    slot = orchestrator.get_active_slot("director", "TXT")
    plan = await build_director_plan(req.prompt, proj.resources, slot)
    
    proj.spec = plan["spec"]
    proj.scenes = plan["scenes"]
    proj.status = "awaiting_approval"
    
    return {"mode": "plan", "project": proj.model_dump()}

@app.post("/api/director/approve")
async def approve_and_produce(req: ApproveSpecRequest):
    proj = get_project(req.project_id)
    proj.spec = req.spec
    proj.status = "rendering"
    proj.progress = 0
    task = asyncio.create_task(run_production_pipeline(proj.project_id))
    RUNNING_TASKS[proj.project_id] = task
    return {"ok": True, "project": proj.model_dump()}

@app.post("/api/projects/{project_id}/stop")
async def stop_production(project_id: str):
    proj = get_project(project_id)
    task = RUNNING_TASKS.get(project_id)
    if task and not task.done():
        task.cancel()
    proj.status = "cancelled"
    proj.spec.lifecycle = "populated"
    return {"ok": True, "project": proj.model_dump()}

@app.get("/api/stream")
async def stream(request: Request, project_id: str = "default"):
    queue = asyncio.Queue()
    SSE_QUEUES[project_id] = queue
    async def event_generator():
        try:
            while True:
                if await request.is_disconnected(): break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=10.0)
                    yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'])}\n\n"
                except asyncio.TimeoutError: yield ": keepalive\n\n"
        finally: SSE_QUEUES.pop(project_id, None)
    return StreamingResponse(event_generator(), media_type="text/event-stream")

async def run_production_pipeline(project_id: str):
    proj = get_project(project_id)
    temp_clips = []
    try:
        broadcast(project_id, "log", {"msg": "Gate 1: Preflight checks started..."})
        video_slot = orchestrator.get_active_slot("video", "VID")
        audio_slot = orchestrator.get_active_slot("audio", "AUD")
        proj.progress = 10
        broadcast(project_id, "progress", {"progress": proj.progress})

        total_scenes = len(proj.scenes)
        for i, scene in enumerate(proj.scenes):
            broadcast(project_id, "log", {"msg": f"Processing Scene {i+1}/{total_scenes}..."})
            clip_path = None
            if video_slot:
                vid_res = await generate_video_clip(scene.visual_prompt, video_slot)
                if vid_res.get("ok"): clip_path = vid_res["video_path"]
            
            if not clip_path:
                broadcast(project_id, "log", {"msg": f"Scene {i+1}: Fallback to Cinematic Image."})
                img_path = UPLOADS_DIR / f"placeholder_{i}.jpg"
                import subprocess
                subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=blue:s=1920x1080:d=1", "-vf", f"drawtext=text='Scene {i+1}':fontcolor=white:fontsize=72", "-frames:v", "1", str(img_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                clip_path = UPLOADS_DIR / f"clip_{i}.mp4"
                create_cinematic_clip(img_path, clip_path, scene.duration_sec, proj.spec.aspect_ratio)
            
            if clip_path and clip_path.exists(): temp_clips.append(clip_path)
            proj.progress += int(40 / total_scenes)
            broadcast(project_id, "progress", {"progress": proj.progress})

        audio_path = None
        if proj.scenes and proj.scenes[0].narration_text:
            broadcast(project_id, "log", {"msg": "Generating Voiceover..."})
            audio_path = UPLOADS_DIR / "narration.mp3"
            try: await generate_narration_audio(proj.scenes[0].narration_text, proj.spec.voice_profile, audio_slot, audio_path)
            except: pass

        proj.progress = 80
        broadcast(project_id, "progress", {"progress": proj.progress})
        output_name = f"video_{project_id[:6]}_{uuid.uuid4().hex[:4]}"
        final_res = await assemble_final_video(temp_clips, audio_path, None, output_name, proj.spec.aspect_ratio)

        if final_res.get("ok"):
            proj.progress = 100
            proj.status = "done"
            asset = Asset(asset_id=str(uuid.uuid4()), kind="video", filename=f"{output_name}.mp4", public_url=final_res["public_url"], bytes=final_res["size_bytes"], verified=True, duration_sec=final_res["duration"])
            proj.assets.append(asset)
            broadcast(project_id, "complete", {"project": proj.model_dump()})
        else:
            proj.status = "error"
            broadcast(project_id, "error", {"msg": final_res.get("error")})
    except asyncio.CancelledError:
        broadcast(project_id, "log", {"msg": "Cancelled by user."})
    except Exception as e:
        proj.status = "error"
        broadcast(project_id, "error", {"msg": str(e)})
    finally:
        for c in temp_clips:
            if c.exists(): c.unlink(missing_ok=True)
