# ==============================================================================
# AI Video Production Studio - Zero-Hallucination Data Models (Part B3)
# Strict Pydantic v2 Schemas: 5 Agents, Primary/Secondary Slots, 3-State Spec
# Inspector, Beat-Sync Map, Dual-Mode Dubbing, Workflow Logs & Project State
# ==============================================================================

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

AgentId = Literal["director", "image", "video", "audio", "editing"]
PowerLevel = Literal["Max", "High", "Medium", "Low"]
SlotStatus = Literal["inactive", "active", "ready", "working", "error"]
SpecLifecycle = Literal["locked", "populated", "approved"]
DubbingMode = Literal["none", "custom_script", "auto_translate"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------------------
# 1. API KEY SLOTS & 5-AGENT STATE
# ------------------------------------------------------------------------------
class AgentSlot(BaseModel):
    slot_id: str
    role: Literal["primary", "secondary", "backup"] = "primary"
    provider_id: str
    provider_name: str
    api_key: str
    base_url: Optional[str] = None
    model_id: str
    is_free_tier: bool = False
    status: SlotStatus = "active"
    capabilities: List[str] = Field(default_factory=list)
    last_error_en: Optional[str] = None
    last_error_bn: Optional[str] = None
    heal_attempts: int = 0
    verified_at: Optional[str] = None


class AgentState(BaseModel):
    agent_id: AgentId
    power_level: PowerLevel = "High"
    status: SlotStatus = "inactive"
    slots: List[AgentSlot] = Field(default_factory=list)
    active_capabilities: List[str] = Field(default_factory=list)
    parallel_dual_active: bool = False
    needs_self_switch: bool = False
    borrowed_from_agent: Optional[AgentId] = None


# ------------------------------------------------------------------------------
# 2. AUDIO BEAT-SYNC & RESOURCE STYLE-DNA
# ------------------------------------------------------------------------------
class BeatEnergyMap(BaseModel):
    bpm: float = 120.0
    duration_sec: float = 0.0
    beat_timestamps: List[float] = Field(default_factory=list)
    bass_drop_timestamps: List[float] = Field(default_factory=list)
    treble_peak_timestamps: List[float] = Field(default_factory=list)
    energy_curve: List[Dict[str, float]] = Field(default_factory=list)
    mood_summary: str = "dynamic"


class ResourceItem(BaseModel):
    resource_id: str
    kind: Literal["image", "video", "audio", "youtube"]
    name: str
    path_or_url: str
    mime_type: Optional[str] = None
    duration_sec: Optional[float] = None
    style_dna: Optional[Dict[str, Any]] = None
    beat_map: Optional[BeatEnergyMap] = None
    added_at: str = Field(default_factory=utc_now_iso)


# ------------------------------------------------------------------------------
# 3. 3-STATE LEFT-CORNER SPEC INSPECTOR (LOCKED -> POPULATED -> APPROVED)
# ------------------------------------------------------------------------------
class VideoSpec(BaseModel):
    lifecycle: SpecLifecycle = "locked"
    title: str = ""
    project_mode: Literal[
        "text_to_video",
        "image_to_video",
        "photo_edit",
        "music_beat_video",
        "music_video_edit",
        "video_dubbing",
    ] = "text_to_video"
    aspect_ratio: Literal["16:9", "9:16", "1:1", "4:5"] = "16:9"
    resolution: Literal["720p", "1080p", "4K"] = "1080p"
    fps: Literal[24, 30, 60] = 30
    visual_style: str = "2D High-Quality Anime Cinema"
    language: str = "Bengali"
    voice_profile: str = "bn-IN-BashkarNeural"
    dubbing_mode: DubbingMode = "none"
    dubbing_target_lang: Optional[str] = None
    custom_dub_script: Optional[str] = None
    enable_subtitles: bool = True
    enable_beat_sync: bool = False
    bgm_mood: str = "cinematic"
    scene_count: int = 4
    target_duration_sec: int = 20
    story_outline: str = ""
    custom_notes: str = ""


class ScenePlan(BaseModel):
    scene_number: int
    visual_prompt: str
    negative_prompt: str = (
        "stick figure, svg cartoon, flat geometric shapes, blurry, watermark, distorted"
    )
    narration_text: str = ""
    subtitle_text: str = ""
    duration_sec: float = 5.0
    camera_motion: Literal[
        "ken_burns_in",
        "ken_burns_out",
        "pan_left",
        "pan_right",
        "zoom_punch",
        "shake_impact",
        "static",
    ] = "ken_burns_in"
    transition: Literal["fade", "cut_beat", "flash", "dissolve", "wipe"] = "fade"
    beat_trigger_sec: Optional[float] = None
    image_path: Optional[str] = None
    video_clip_path: Optional[str] = None
    audio_clip_path: Optional[str] = None


# ------------------------------------------------------------------------------
# 4. WORKFLOW LOGS, CHAT & COMPLETE PROJECT STATE
# ------------------------------------------------------------------------------
class ChatMessage(BaseModel):
    msg_id: str
    sender: Literal["user", "director", "system", "image", "video", "audio", "editing"]
    text: str
    tone: Literal["normal", "success", "error", "warning", "info"] = "normal"
    timestamp: str = Field(default_factory=utc_now_iso)


class WorkflowEvent(BaseModel):
    event_id: str
    timestamp: str = Field(default_factory=utc_now_iso)
    agent_id: str = "director"
    event_type: Literal[
        "log", "board_meeting", "mindmap", "cross_switch",
        "self_heal", "progress", "celebration", "error"
    ] = "log"
    message_en: str
    message_bn: str = ""
    progress_pct: Optional[int] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class ProjectState(BaseModel):
    project_id: str
    name: str = "Untitled Studio Project"
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    status: Literal[
        "idle", "planning", "awaiting_approval", "producing", "ready", "error"
    ] = "idle"
    progress_pct: int = 0
    prompt: str = ""
    resources: List[ResourceItem] = Field(default_factory=list)
    spec: VideoSpec = Field(default_factory=VideoSpec)
    scenes: List[ScenePlan] = Field(default_factory=list)
    chat_history: List[ChatMessage] = Field(default_factory=list)
    workflow_logs: List[WorkflowEvent] = Field(default_factory=list)
    output_video_url: Optional[str] = None
    output_image_url: Optional[str] = None
    seo_metadata: Dict[str, Any] = Field(default_factory=dict)


# ------------------------------------------------------------------------------
# 5. API REQUEST PAYLOADS
# ------------------------------------------------------------------------------
class DetectKeyRequest(BaseModel):
    api_key: str
    custom_base_url: Optional[str] = None
    preferred_provider: Optional[str] = None


class ApplyKeyRequest(BaseModel):
    provider_id: str
    api_key: str
    base_url: Optional[str] = None
    target_agents: List[AgentId] = Field(default_factory=list)
    selected_models: Dict[str, str] = Field(default_factory=dict)
    is_free_tier: bool = False


class TestAgentRequest(BaseModel):
    agent_id: AgentId
    slot_id: Optional[str] = None


class SelfHealRequest(BaseModel):
    agent_id: AgentId
    slot_id: Optional[str] = None


class SelfSwitchRequest(BaseModel):
    agent_id: AgentId


class PromptRequest(BaseModel):
    project_id: Optional[str] = None
    prompt: str
    youtube_url: Optional[str] = None


class ApproveSpecRequest(BaseModel):
    project_id: str
    spec: VideoSpec


class DirectAgentChatRequest(BaseModel):
    project_id: Optional[str] = None
    agent_id: AgentId
    message: str


class SaveProjectRequest(BaseModel):
    project_id: str
    name: str
  
