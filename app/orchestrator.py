# ==============================================================================
# AI Video Production Studio - 5-Agent Orchestrator & Live Pipeline (Part D1)
# Covers: Primary/Secondary Slots, Undo, Self-Healing, Self-Switching,
#         Cross-Agent Key Borrowing (White Light), Live SSE & Full Production
# ==============================================================================

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.audio_dsp_engine import analyze_audio_beats, generate_narration_audio
from app.config import (
    AGENT_DEFINITIONS,
    AGENT_ORDER,
    OUTPUTS_DIR,
    PROJECTS_DIR,
    STUDIO_STATE_FILE,
    ensure_workspace_dirs,
    get_provider_by_id,
)
from app.director_engine import (
    build_director_plan,
    detect_voice_for_language,
    direct_agent_chat_reply,
    learn_youtube_style_dna,
    re_brief_after_approval,
    translate_dubbing_script,
)
from app.media_engine import (
    edit_photo_enhance,
    generate_real_image,
    generate_real_video_clip,
    verify_real_image,
)
from app.models import (
    AgentId,
    AgentSlot,
    AgentState,
    ChatMessage,
    ProjectState,
    ResourceItem,
    VideoSpec,
    WorkflowEvent,
    utc_now_iso,
)
from app.provider_engine import probe_single_provider, translate_error_to_bangla
from app.video_assembler import assemble_dubbed_video, assemble_final_video

VALID_EVENT_TYPES = {
    "log", "board_meeting", "mindmap", "cross_switch",
    "self_heal", "progress", "celebration", "error",
}
VALID_SENDERS = {"user", "director", "system", "image", "video", "audio", "editing"}
VALID_TONES = {"normal", "success", "error", "warning", "info"}


def _atomic_write_text(target: Path, content: str) -> None:
    """Crash-safe atomic file write so concurrent async saves never corrupt JSON."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(f"{target.suffix}.{uuid.uuid4().hex[:6]}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, target)


def _sanitize_project_id(raw_id: Optional[str]) -> str:
    """Ensure project_id is always a safe filename without path traversal."""
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", (raw_id or "").strip())
    return cleaned[:48] if cleaned else f"proj_{uuid.uuid4().hex[:8]}"


class StudioOrchestrator:
    """Central stateful engine coordinating all 5 agents, slots, projects & SSE streams."""

    def __init__(self) -> None:
        ensure_workspace_dirs()
        self.agents: Dict[str, AgentState] = {
            aid: AgentState(agent_id=aid) for aid in AGENT_ORDER
        }
        self.undo_stack: List[Dict[str, Any]] = []
        self.projects: Dict[str, ProjectState] = {}
        self.active_project_id: Optional[str] = None
        self.subscribers: List[asyncio.Queue] = []
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self._load_studio_state()
        self._load_saved_projects()

    # --------------------------------------------------------------------------
    # 1. PERSISTENT STATE & PROJECT STORAGE
    # --------------------------------------------------------------------------
    def _load_studio_state(self) -> None:
        """Restore saved 5-agent slots & power levels from disk."""
        if not STUDIO_STATE_FILE.exists():
            return
        try:
            raw = json.loads(STUDIO_STATE_FILE.read_text(encoding="utf-8"))
            agents_raw = raw.get("agents", {})
            for aid in AGENT_ORDER:
                if aid in agents_raw:
                    self.agents[aid] = AgentState.model_validate(agents_raw[aid])
        except Exception:
            pass

    def _save_studio_state(self) -> None:
        """Persist current 5-agent slots atomically to disk."""
        ensure_workspace_dirs()
        payload = {
            "updated_at": utc_now_iso(),
            "agents": {aid: st.model_dump() for aid, st in self.agents.items()},
        }
        _atomic_write_text(
            STUDIO_STATE_FILE,
            json.dumps(payload, indent=2, ensure_ascii=False),
        )

    def _load_saved_projects(self) -> None:
        """Load saved studio projects from workspace/projects."""
        if not PROJECTS_DIR.exists():
            return
        for fp in sorted(PROJECTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                proj = ProjectState.model_validate_json(fp.read_text(encoding="utf-8"))
                self.projects[proj.project_id] = proj
            except Exception:
                continue
        if self.projects and not self.active_project_id:
            self.active_project_id = next(iter(self.projects.keys()))

    def persist_project(self, project: ProjectState) -> None:
        """Save project JSON atomically so work survives mobile backgrounding & reloads."""
        ensure_workspace_dirs()
        project.project_id = _sanitize_project_id(project.project_id)
        project.updated_at = utc_now_iso()
        self.projects[project.project_id] = project
        fp = PROJECTS_DIR / f"{project.project_id}.json"
        _atomic_write_text(fp, project.model_dump_json(indent=2))

    def get_or_create_project(self, project_id: Optional[str] = None) -> ProjectState:
        """Return existing project or initialize a fresh studio project."""
        if project_id:
            safe_id = _sanitize_project_id(project_id)
            if safe_id in self.projects:
                self.active_project_id = safe_id
                return self.projects[safe_id]
        if not project_id and self.active_project_id and self.active_project_id in self.projects:
            return self.projects[self.active_project_id]
        pid = _sanitize_project_id(project_id)
        proj = ProjectState(project_id=pid)
        self.active_project_id = pid
        self.persist_project(proj)
        return proj

    def register_background_task(self, project_id: str, coro: Any) -> asyncio.Task:
        """Keep strong reference to background production tasks so asyncio never drops them."""
        task = asyncio.create_task(coro)
        self.running_tasks[project_id] = task
        task.add_done_callback(lambda _t: self.running_tasks.pop(project_id, None))
        return task

    # --------------------------------------------------------------------------
    # 2. LIVE SSE STREAMING, WORKFLOW LOGS & CHAT BROADCAST
    # --------------------------------------------------------------------------
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=120)
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self.subscribers:
            self.subscribers.remove(q)

    def broadcast(self, event_name: str, data: Dict[str, Any]) -> None:
        """Push real-time updates to all connected UI clients without blocking."""
        payload = {"event": event_name, "data": data}
        for q in list(self.subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except Exception:
                    pass

    def emit_workflow(
        self,
        project: Optional[ProjectState],
        agent_id: str,
        message_en: str,
        message_bn: str = "",
        event_type: str = "log",
        progress_pct: Optional[int] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> WorkflowEvent:
        safe_type = event_type if event_type in VALID_EVENT_TYPES else "log"
        ev = WorkflowEvent(
            event_id=f"ev_{uuid.uuid4().hex[:8]}",
            agent_id=str(agent_id or "director"),
            event_type=safe_type,
            message_en=message_en,
            message_bn=message_bn,
            progress_pct=progress_pct,
            meta=meta or {},
        )
        if project:
            project.workflow_logs.append(ev)
            if len(project.workflow_logs) > 200:
                project.workflow_logs = project.workflow_logs[-200:]
            if progress_pct is not None:
                project.progress_pct = max(0, min(100, int(progress_pct)))
            self.persist_project(project)
        self.broadcast("workflow", ev.model_dump())
        return ev

    def add_chat(
        self,
        project: ProjectState,
        sender: str,
        text: str,
        tone: str = "normal",
    ) -> ChatMessage:
        safe_sender = sender if sender in VALID_SENDERS else "system"
        safe_tone = tone if tone in VALID_TONES else "normal"
        msg = ChatMessage(
            msg_id=f"msg_{uuid.uuid4().hex[:8]}",
            sender=safe_sender,
            text=text,
            tone=safe_tone,
        )
        project.chat_history.append(msg)
        if len(project.chat_history) > 150:
            project.chat_history = project.chat_history[-150:]
        self.persist_project(project)
        self.broadcast("chat", {"project_id": project.project_id, "message": msg.model_dump()})
        return msg

    def get_studio_snapshot(self) -> Dict[str, Any]:
        """Return full sanitized studio state (masking raw API keys) for UI sync."""
        safe_agents: Dict[str, Any] = {}
        for aid, st in self.agents.items():
            d = st.model_dump()
            for sl in d.get("slots", []):
                k = sl.get("api_key", "")
                sl["api_key_masked"] = f"{k[:4]}...{k[-4:]}" if len(k) > 12 else "****"
                sl.pop("api_key", None)
            safe_agents[aid] = d
        return {
            "agents": safe_agents,
            "can_undo": len(self.undo_stack) > 0,
            "active_project_id": self.active_project_id,
      }
          # --------------------------------------------------------------------------
    # 3. 5-AGENT SLOT MANAGEMENT, UNDO, READY TEST, SELF-HEAL & SELF-SWITCH
    # --------------------------------------------------------------------------
    def _push_undo(self) -> None:
        """Snapshot current 5-agent configuration before mutating so Undo works instantly."""
        snap = {aid: st.model_dump() for aid, st in self.agents.items()}
        self.undo_stack.append(snap)
        if len(self.undo_stack) > 15:
            self.undo_stack = self.undo_stack[-15:]

    def _recompute_agent_flags(self, agent: AgentState) -> None:
        """Sync LED status, capabilities, and dual-model parallel flag from slots."""
        caps: List[str] = []
        healthy_slots = [s for s in agent.slots if s.status in ("active", "ready", "working")]
        for sl in agent.slots:
            for c in sl.capabilities:
                if c not in caps:
                    caps.append(c)
        agent.active_capabilities = caps
        agent.parallel_dual_active = len(healthy_slots) >= 2

        if not agent.slots:
            agent.status = "inactive"
            agent.needs_self_switch = False
        elif any(s.status == "working" for s in agent.slots):
            agent.status = "working"
        elif any(s.status == "ready" for s in agent.slots):
            agent.status = "ready"
            agent.needs_self_switch = False
        elif any(s.status == "active" for s in agent.slots):
            agent.status = "active"
            agent.needs_self_switch = False
        else:
            agent.status = "error"
            agent.needs_self_switch = True

    def apply_api_key(
        self,
        provider_id: str,
        api_key: str,
        target_agents: List[AgentId],
        selected_models: Dict[str, str],
        base_url: Optional[str] = None,
        is_free_tier: bool = False,
    ) -> Dict[str, Any]:
        """Assign an API key to one or more agents as Primary, Secondary, or Backup."""
        self._push_undo()
        provider = get_provider_by_id(provider_id) or {
            "id": provider_id,
            "name": provider_id.replace("_", " ").title(),
            "base_url": base_url or "https://api.openai.com/v1",
            "capabilities": ["reasoning", "script", "editing"],
            "default_models": {},
        }
        agents_to_update = target_agents or ["director"]

        for aid in agents_to_update:
            if aid not in self.agents:
                continue
            agent = self.agents[aid]
            model_id = (
                selected_models.get(aid)
                or (provider.get("default_models") or {}).get(aid)
                or (provider.get("top_free") or [{}])[0].get("id")
                or (provider.get("top_paid") or [{}])[0].get("id")
                or "default"
            )
            role = "primary" if len(agent.slots) == 0 else ("secondary" if len(agent.slots) == 1 else "backup")
            slot = AgentSlot(
                slot_id=f"slot_{uuid.uuid4().hex[:8]}",
                role=role,
                provider_id=provider["id"],
                provider_name=provider.get("name", provider_id),
                api_key=api_key.strip(),
                base_url=base_url or provider.get("base_url"),
                model_id=model_id,
                is_free_tier=is_free_tier,
                status="active",
                capabilities=list(provider.get("capabilities") or []),
                verified_at=utc_now_iso(),
            )
            agent.slots.append(slot)
            agent.borrowed_from_agent = None
            self._recompute_agent_flags(agent)

        self._save_studio_state()
        snap = self.get_studio_snapshot()
        self.broadcast("studio_state", snap)
        return snap

    def remove_slot(self, agent_id: AgentId, slot_id: str) -> Dict[str, Any]:
        """Remove a specific API slot and promote remaining slots cleanly."""
        self._push_undo()
        agent = self.agents[agent_id]
        agent.slots = [s for s in agent.slots if s.slot_id != slot_id]
        for idx, sl in enumerate(agent.slots):
            sl.role = "primary" if idx == 0 else ("secondary" if idx == 1 else "backup")
        self._recompute_agent_flags(agent)
        self._save_studio_state()
        snap = self.get_studio_snapshot()
        self.broadcast("studio_state", snap)
        return snap

    def undo_last_change(self) -> Dict[str, Any]:
        """Restore the previous 5-agent configuration from the Undo stack."""
        if self.undo_stack:
            prev = self.undo_stack.pop()
            for aid in AGENT_ORDER:
                if aid in prev:
                    self.agents[aid] = AgentState.model_validate(prev[aid])
            self._save_studio_state()
        snap = self.get_studio_snapshot()
        self.broadcast("studio_state", snap)
        return snap

    def set_agent_power(self, agent_id: AgentId, power_level: str) -> Dict[str, Any]:
        """Update agent power tier (Max / High / Medium / Low)."""
        if agent_id in self.agents and power_level in ("Max", "High", "Medium", "Low"):
            self.agents[agent_id].power_level = power_level  # type: ignore[assignment]
            self._save_studio_state()
        snap = self.get_studio_snapshot()
        self.broadcast("studio_state", snap)
        return snap

    async def test_agent_slot(self, agent_id: AgentId, slot_id: Optional[str] = None) -> Dict[str, Any]:
        """Live-probe an agent's API key and update LED status (ready vs error + Bangla note)."""
        agent = self.agents[agent_id]
        slot = next((s for s in agent.slots if s.slot_id == slot_id), None) if slot_id else (agent.slots[0] if agent.slots else None)
        if not slot:
            return {"ok": False, "error_en": "No API slot configured.", "error_bn": "এই এজেন্টে কোনো API Key বসানো নেই।"}

        provider = get_provider_by_id(slot.provider_id) or {
            "id": slot.provider_id,
            "base_url": slot.base_url or "https://api.openai.com/v1",
            "auth_type": "bearer",
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0), follow_redirects=True) as client:
            ok, _models, err = await probe_single_provider(client, provider, slot.api_key)

        if ok:
            slot.status = "ready"
            slot.last_error_en = None
            slot.last_error_bn = None
            slot.verified_at = utc_now_iso()
        else:
            slot.status = "error"
            slot.last_error_en = err
            slot.last_error_bn = translate_error_to_bangla(err)

        self._recompute_agent_flags(agent)
        self._save_studio_state()
        snap = self.get_studio_snapshot()
        self.broadcast("studio_state", snap)
        return {
            "ok": ok,
            "agent_id": agent_id,
            "slot_id": slot.slot_id,
            "error_en": slot.last_error_en,
            "error_bn": slot.last_error_bn,
            "studio": snap,
        }

    async def self_heal_agent(self, agent_id: AgentId, slot_id: Optional[str] = None) -> Dict[str, Any]:
        """Attempt automatic recovery by switching to a verified fallback model on the same provider."""
        agent = self.agents[agent_id]
        slot = next((s for s in agent.slots if s.slot_id == slot_id), None) if slot_id else (agent.slots[0] if agent.slots else None)
        if not slot:
            return {"healed": False, "message_bn": "হিলিং করার জন্য কোনো স্লট পাওয়া যায়নি।"}

        slot.heal_attempts += 1
        provider = get_provider_by_id(slot.provider_id) or {}
        candidates = [m["id"] for m in (provider.get("top_free") or []) + (provider.get("top_paid") or []) if m.get("id")]
        for alt_model in candidates:
            if alt_model != slot.model_id:
                slot.model_id = alt_model
                break

        res = await self.test_agent_slot(agent_id, slot.slot_id)
        if res["ok"]:
            self.emit_workflow(
                None, agent_id,
                f"Self-Healed {agent_id.upper()} using model '{slot.model_id}'.",
                f"{agent_id.upper()} এজেন্ট নিজে থেকেই '{slot.model_id}' মডেলে ঠিক হয়ে গেছে।",
                event_type="self_heal",
            )
            return {"healed": True, "model_id": slot.model_id, "studio": res["studio"]}
        return {
            "healed": False,
            "message_en": res.get("error_en"),
            "message_bn": res.get("error_bn"),
            "studio": res["studio"],
        }

    def self_switch_agent(self, agent_id: AgentId, project: Optional[ProjectState] = None) -> Dict[str, Any]:
        """Promote Secondary/Backup slot to Primary, or borrow a compatible key from another agent (White Light)."""
        agent = self.agents[agent_id]
        # 1) Try promoting a healthy Secondary/Backup slot on the same agent
        for idx, sl in enumerate(agent.slots):
            if idx > 0 and sl.status in ("active", "ready"):
                agent.slots.insert(0, agent.slots.pop(idx))
                for i, item in enumerate(agent.slots):
                    item.role = "primary" if i == 0 else ("secondary" if i == 1 else "backup")
                self._recompute_agent_flags(agent)
                self._save_studio_state()
                snap = self.get_studio_snapshot()
                self.broadcast("studio_state", snap)
                self.emit_workflow(
                    project, agent_id,
                    f"Self-Switched {agent_id.upper()} to Secondary slot ({sl.provider_name}).",
                    f"{agent_id.upper()} এজেন্ট তার Secondary Key ({sl.provider_name})-এ সুইচ করেছে।",
                    event_type="cross_switch",
                )
                return {"switched": True, "mode": "secondary_promoted", "studio": snap}

        # 2) Cross-Agent Key Borrowing (White Light Travel)
        donor_aid, donor_slot = self._find_cross_agent_donor(agent_id)
        if donor_aid and donor_slot:
            agent.borrowed_from_agent = donor_aid  # type: ignore[assignment]
            agent.needs_self_switch = False
            self._save_studio_state()
            snap = self.get_studio_snapshot()
            self.broadcast("studio_state", snap)
            self.emit_workflow(
                project, agent_id,
                f"Cross-Agent White-Light Transfer: {donor_aid.upper()} lent {donor_slot.provider_name} to {agent_id.upper()}.",
                f"সাদা আলোর সংযোগ: {donor_aid.upper()} এজেন্ট তার {donor_slot.provider_name} Key-টি {agent_id.upper()}-কে ধার দিয়েছে।",
                event_type="cross_switch",
                meta={"from_agent": donor_aid, "to_agent": agent_id},
            )
            return {"switched": True, "mode": "cross_agent_borrowed", "from_agent": donor_aid, "studio": snap}

        return {
            "switched": False,
            "message_bn": "অন্য কোনো এজেন্টেও উপযুক্ত সচল Key পাওয়া যায়নি। Settings থেকে নতুন Key দিন।",
            "studio": self.get_studio_snapshot(),
        }

    def _find_cross_agent_donor(self, target_agent: AgentId) -> Tuple[Optional[str], Optional[AgentSlot]]:
        """Find another agent with a healthy slot whose provider supports target_agent."""
        for aid in AGENT_ORDER:
            if aid == target_agent:
                continue
            for sl in self.agents[aid].slots:
                if sl.status not in ("active", "ready", "working"):
                    continue
                prov = get_provider_by_id(sl.provider_id) or {}
                supported = prov.get("supports_agents") or []
                if target_agent in supported or (target_agent in ("director", "editing") and "reasoning" in sl.capabilities):
                    return aid, sl
        return None, None

    def resolve_slots(
        self,
        agent_id: AgentId,
        project: Optional[ProjectState] = None,
    ) -> Tuple[Optional[AgentSlot], Optional[AgentSlot]]:
        """Return (primary_slot, optional_secondary_slot) with automatic Cross-Agent borrowing."""
        agent = self.agents[agent_id]
        healthy = [s for s in agent.slots if s.status in ("active", "ready", "working")]
        if healthy:
            return healthy[0], (healthy[1] if len(healthy) > 1 else None)

        donor_aid, donor_slot = self._find_cross_agent_donor(agent_id)
        if donor_aid and donor_slot:
            agent.borrowed_from_agent = donor_aid  # type: ignore[assignment]
            self.emit_workflow(
                project, agent_id,
                f"White-Light Key Share: {donor_aid.upper()} -> {agent_id.upper()} ({donor_slot.provider_name})",
                f"সাদা আলোর শেয়ার: {donor_aid.upper()} থেকে {agent_id.upper()} এজেন্টে Key ধার নেওয়া হয়েছে।",
                event_type="cross_switch",
                meta={"from_agent": donor_aid, "to_agent": agent_id},
            )
            return donor_slot, None
        return None, None
          # --------------------------------------------------------------------------
    # 4. RESOURCE INGESTION (IMAGE / VIDEO / AUDIO BEAT-DSP / YOUTUBE STYLE-DNA)
    # --------------------------------------------------------------------------
    async def add_resource(
        self,
        project_id: Optional[str],
        kind: str,
        name: str,
        path_or_url: str,
        mime_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Attach an uploaded file or YouTube link and run Style-DNA / Beat-Sync DSP."""
        project = self.get_or_create_project(project_id)
        item = ResourceItem(
            resource_id=f"res_{uuid.uuid4().hex[:8]}",
            kind=kind,  # type: ignore[arg-type]
            name=name,
            path_or_url=path_or_url,
            mime_type=mime_type,
        )

        if kind == "audio" and Path(path_or_url).exists():
            self.emit_workflow(
                project, "audio",
                f"Analyzing audio beat & bass-drop frequency map: {name}",
                f"অডিওর BPM, বেস-ড্রপ ও বিট-সিঙ্ক ফ্রিকোয়েন্সি বিশ্লেষণ চলছে: {name}",
            )
            beat_map = await analyze_audio_beats(Path(path_or_url))
            item.beat_map = beat_map
            item.duration_sec = beat_map.duration_sec
        elif kind == "youtube":
            self.emit_workflow(
                project, "director",
                f"Learning cinematic Style-DNA from YouTube reference...",
                "YouTube রেফারেন্স ভিডিও থেকে সিনেম্যাটিক স্টাইল-DNA শেখা হচ্ছে...",
            )
            dir_slot, _ = self.resolve_slots("director", project)
            item.style_dna = await learn_youtube_style_dna(path_or_url, dir_slot)

        project.resources.append(item)
        self.persist_project(project)
        self.broadcast("project_update", project.model_dump())
        return {"project": project.model_dump(), "resource": item.model_dump()}

    # --------------------------------------------------------------------------
    # 5. DIRECTOR PLANNING (PROMPT -> POPULATED SPEC INSPECTOR + BOARD MEETING)
    # --------------------------------------------------------------------------
    async def start_director_planning(
        self,
        prompt: str,
        project_id: Optional[str] = None,
        youtube_url: Optional[str] = None,
    ) -> ProjectState:
        """Analyze prompt + resources and populate the Left-Corner Spec Inspector."""
        project = self.get_or_create_project(project_id)
        project.prompt = prompt.strip()
        project.status = "planning"
        project.progress_pct = 10
        self.add_chat(project, "user", prompt.strip())

        if youtube_url and youtube_url.strip():
            await self.add_resource(project.project_id, "youtube", "YouTube Reference", youtube_url.strip())

        dir_primary, dir_secondary = self.resolve_slots("director", project)
        self.emit_workflow(
            project, "director",
            "Director AI is hosting Board Meeting & drafting Video Spec...",
            "Director AI বোর্ড মিটিং করে ভিডিওর ফরম্যাট ও স্ক্রিপ্ট সাজাচ্ছে...",
            event_type="board_meeting",
            progress_pct=20,
        )

        beat_map = next((r.beat_map for r in reversed(project.resources) if r.beat_map), None)
        plan = await build_director_plan(
            prompt=project.prompt,
            resources=project.resources,
            director_slot=dir_primary,
            secondary_slot=dir_secondary,
            beat_map=beat_map,
        )

        project.spec = plan["spec"]
        project.scenes = plan["scenes"]
        project.seo_metadata = plan["seo_metadata"]
        project.name = project.spec.title or project.name
        project.status = "awaiting_approval"
        project.progress_pct = 25
        self.persist_project(project)

        for note in plan.get("board_notes", []):
            self.emit_workflow(project, "director", note, "", event_type="board_meeting")

        self.add_chat(
            project, "director",
            f"প্ল্যান তৈরি হয়েছে: '{project.spec.title}' ({project.spec.aspect_ratio}, {project.spec.resolution}, "
            f"{len(project.scenes)}টি দৃশ্য)। বাঁ দিকের Spec Inspector যাচাই করে Approve চাপলেই প্রোডাকশন শুরু হবে!",
            tone="info",
        )
        self.broadcast("project_update", project.model_dump())
        return project

    # --------------------------------------------------------------------------
    # 6. SPEC APPROVAL & BACKGROUND MULTI-AGENT PRODUCTION PIPELINE
    # --------------------------------------------------------------------------
    async def approve_and_produce(self, project_id: str, approved_spec: VideoSpec) -> ProjectState:
        """Lock user-approved spec, run Re-Briefing, and launch background production."""
        project = self.get_or_create_project(project_id)
        project.spec = approved_spec
        project.spec.lifecycle = "approved"
        project.status = "producing"
        project.progress_pct = 30
        self.persist_project(project)
        self.broadcast("project_update", project.model_dump())

        self.register_background_task(project.project_id, self._run_production_pipeline(project.project_id))
        return project

    async def _run_production_pipeline(self, project_id: str) -> None:
        """Full autonomous 5-agent background production (survives mobile backgrounding)."""
        project = self.get_or_create_project(project_id)
        spec = project.spec
        try:
            dir_slot, _ = self.resolve_slots("director", project)
            beat_map = next((r.beat_map for r in reversed(project.resources) if r.beat_map), None)

            self.emit_workflow(
                project, "director",
                "Spec Approved! Re-Briefing all 5 specialist agents...",
                "স্পেক অনুমোদিত! ৫টি এজেন্টকে চূড়ান্ত নির্দেশনা (Re-Briefing) দেওয়া হচ্ছে...",
                event_type="board_meeting",
                progress_pct=35,
            )
            project.scenes = await re_brief_after_approval(project.prompt, spec, dir_slot, beat_map)
            self.persist_project(project)

            # MODE A: PHOTO EDIT / THUMBNAIL MODE
            if spec.project_mode == "photo_edit":
                img_res = next((r for r in reversed(project.resources) if r.kind == "image" and Path(r.path_or_url).exists()), None)
                if img_res:
                    src_img = Path(img_res.path_or_url)
                else:
                    img_slot, _ = self.resolve_slots("image", project)
                    if not img_slot:
                        raise RuntimeError("No Image Agent API Key available to generate base image.")
                    src_img = await generate_real_image(img_slot, project.scenes[0].visual_prompt, spec.aspect_ratio, spec.resolution)
                edited = edit_photo_enhance(src_img, project.prompt, spec.aspect_ratio, spec.resolution)
                project.output_image_url = f"/outputs/{edited.name}"
                project.status = "ready"
                project.progress_pct = 100
                self.persist_project(project)
                self.emit_workflow(project, "image", "Photo editing completed!", "ছবি এডিটিং সম্পন্ন হয়েছে!", event_type="celebration", progress_pct=100)
                self.broadcast("project_update", project.model_dump())
                return

            # MODE B: VIDEO DUBBING MODE
            if spec.project_mode == "video_dubbing":
                vid_res = next((r for r in reversed(project.resources) if r.kind == "video" and Path(r.path_or_url).exists()), None)
                if not vid_res:
                    raise RuntimeError("Please upload a source video file for Video Dubbing mode.")
                target_lang = spec.dubbing_target_lang or spec.language
                raw_script = spec.custom_dub_script or project.prompt
                dub_script = await translate_dubbing_script(raw_script, target_lang, dir_slot)
                aud_slot, _ = self.resolve_slots("audio", project)
                voice = detect_voice_for_language(target_lang)
                nar = await generate_narration_audio(dub_script, voice, aud_slot)
                if not nar.get("path"):
                    raise RuntimeError("Could not synthesize dubbed audio track.")
                final_mp4 = await assemble_dubbed_video(Path(vid_res.path_or_url), nar["path"], spec, project.project_id, dub_script)
                project.output_video_url = f"/outputs/{final_mp4.name}"
                project.status = "ready"
                project.progress_pct = 100
                self.persist_project(project)
                self.emit_workflow(project, "editing", "Video dubbing completed!", "ভিডিও ডাবিং সফলভাবে সম্পন্ন হয়েছে!", event_type="celebration", progress_pct=100)
                self.broadcast("project_update", project.model_dump())
                return

            # MODE C: FULL CINEMATIC VIDEO PRODUCTION (T2V / I2V / BEAT-SYNC)
            img_slot, _ = self.resolve_slots("image", project)
            vid_slot, _ = self.resolve_slots("video", project)
            aud_slot, _ = self.resolve_slots("audio", project)
            uploaded_imgs = [Path(r.path_or_url) for r in project.resources if r.kind == "image" and Path(r.path_or_url).exists()]
            uploaded_vids = [Path(r.path_or_url) for r in project.resources if r.kind == "video" and Path(r.path_or_url).exists()]
            bgm_res = next((Path(r.path_or_url) for r in reversed(project.resources) if r.kind == "audio" and Path(r.path_or_url).exists()), None)

            total_scenes = len(project.scenes)
            for idx, sc in enumerate(project.scenes):
                pct = 40 + int(((idx + 1) / max(1, total_scenes)) * 40)
                self.emit_workflow(
                    project, "image",
                    f"Producing Scene {sc.scene_number}/{total_scenes} visual & voice...",
                    f"দৃশ্য {sc.scene_number}/{total_scenes}-এর ভিজ্যুয়াল ও ভয়েস তৈরি হচ্ছে...",
                    event_type="progress",
                    progress_pct=pct,
                )

                # 1) Visual generation (Uploaded media -> Real AI Image -> Optional AI Video)
                if idx < len(uploaded_vids):
                    sc.video_clip_path = str(uploaded_vids[idx])
                elif idx < len(uploaded_imgs):
                    ok_img, _ = verify_real_image(uploaded_imgs[idx])
                    if ok_img:
                        sc.image_path = str(uploaded_imgs[idx])
                if not sc.video_clip_path and not sc.image_path:
                    if img_slot:
                        gen_img = await generate_real_image(img_slot, sc.visual_prompt, spec.aspect_ratio, spec.resolution, sc.negative_prompt)
                        sc.image_path = str(gen_img)
                    elif vid_slot:
                        gen_vid = await generate_real_video_clip(vid_slot, sc.visual_prompt, None, spec.aspect_ratio, int(sc.duration_sec))
                        sc.video_clip_path = str(gen_vid)
                    else:
                        raise RuntimeError("No Image or Video API Key configured. Please add an API Key in Settings.")

                # 2) Narration Audio
                if sc.narration_text.strip():
                    nar = await generate_narration_audio(sc.narration_text, spec.voice_profile, aud_slot)
                    if nar.get("path"):
                        sc.audio_clip_path = str(nar["path"])
                        sc.duration_sec = max(sc.duration_sec, round(float(nar["duration_sec"]) + 0.35, 2))
                self.persist_project(project)

            # 3) Final FFmpeg Cinema Assembly
            self.emit_workflow(
                project, "editing",
                "Editing Agent assembling final H.264 cinema .mp4 with subtitles & BGM...",
                "Editing এজেন্ট সাবটাইটেল ও মিউজিকসহ ফাইনাল .mp4 ভিডিও রেন্ডার করছে...",
                event_type="progress",
                progress_pct=90,
            )
            final_mp4 = await assemble_final_video(project.scenes, spec, project.project_id, bgm_path=bgm_res)
            project.output_video_url = f"/outputs/{final_mp4.name}"
            project.status = "ready"
            project.progress_pct = 100
            self.persist_project(project)

            self.emit_workflow(
                project, "editing",
                f"Production Complete! Video ready: {final_mp4.name}",
                "অভিনন্দন! আপনার স্টুডিও ভিডিও তৈরি সম্পন্ন হয়েছে—এখন প্লে ও ডাউনলোড করতে পারবেন।",
                event_type="celebration",
                progress_pct=100,
                meta={"output_video_url": project.output_video_url},
            )
            self.add_chat(project, "director", "ভিডিও তৈরি সম্পন্ন হয়েছে! নিচের প্লেয়ারে দেখুন ও ডাউনলোড করুন।", tone="success")
            self.broadcast("project_update", project.model_dump())

        except Exception as exc:
            err_en = str(exc)
            err_bn = translate_error_to_bangla(err_en)
            project.status = "error"
            self.persist_project(project)
            self.emit_workflow(project, "director", f"Production Error: {err_en}", f"ত্রুটি: {err_bn}", event_type="error")
            self.add_chat(project, "system", f"সমস্যা হয়েছে: {err_bn}\n({err_en[:180]})", tone="error")
            self.broadcast("project_update", project.model_dump())

    # --------------------------------------------------------------------------
    # 7. DIRECT 5-AGENT CHAT & PROJECT SAVE / LIST
    # --------------------------------------------------------------------------
    async def handle_direct_agent_chat(self, agent_id: AgentId, message: str, project_id: Optional[str] = None) -> Dict[str, Any]:
        """Chat directly with any of the 5 agents inside the Workflow Box."""
        project = self.get_or_create_project(project_id)
        slot, _ = self.resolve_slots(agent_id, project)
        ctx = f"Project: {project.name} | Mode: {project.spec.project_mode} | Status: {project.status}"
        reply = await direct_agent_chat_reply(agent_id, message, ctx, slot)
        self.add_chat(project, "user", f"@{agent_id}: {message}")
        msg = self.add_chat(project, agent_id, reply)
        return {"reply": reply, "message": msg.model_dump()}

    def list_projects(self) -> List[Dict[str, Any]]:
        """Return lightweight list of saved projects for the Load Project menu."""
        items = sorted(self.projects.values(), key=lambda p: p.updated_at, reverse=True)
        return [
            {
                "project_id": p.project_id,
                "name": p.name,
                "status": p.status,
                "updated_at": p.updated_at,
                "output_video_url": p.output_video_url,
            }
            for p in items
        ]

    def save_project_as(self, project_id: str, name: str) -> Dict[str, Any]:
        """Rename and persist a studio project cleanly."""
        project = self.get_or_create_project(project_id)
        project.name = name.strip() or project.name
        self.persist_project(project)
        return project.model_dump()


# Global Singleton Orchestrator
orchestrator = StudioOrchestrator()
          
