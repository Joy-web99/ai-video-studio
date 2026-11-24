"""
Pydantic schemas - strict validation across all boundaries.
This ensures the system can never accidentally output a fake image instead of a real video.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


Capability = Literal["TXT", "PLAN", "IMG", "VID", "AUD", "EDT"]
PowerTier = Literal["Max", "High", "Medium", "Low"]
SlotStatus = Literal["empty", "unverified", "ready", "active", "error", "cooling"]
CircuitState = Literal["CLOSED", "OPEN", "HALF-OPEN"]
JobStatus = Literal["queued", "running", "cancelling", "cancelled", "succeeded", "failed"]
SpecLifecycle = Literal["draft", "populated", "approved", "rendering", "done"]
AssetKind = Literal["image", "video", "audio", "subtitle", "extra"]


class KeySlot(BaseModel):
    slot_id: Literal["primary", "secondary", "backup"] = "primary"
    provider_id: Optional[str] = None
    provider_name: Optional[str] = None
    model_id: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    status: SlotStatus = "empty"
    led: Literal["green", "blue", "yellow", "red", "white", "off"] = "off"
    circuit: CircuitState = "CLOSED"
    failure_count: int = 0
    cooldown_until: Optional[float] = None
    power_tier: PowerTier = "High"
    is_free_tier: bool = False
    last_error: Optional[str] = None
    last_checked_at: Optional[str] = None


class AgentState(BaseModel):
    agent_id: str
    slots: List[KeySlot] = Field(default_factory=list)
    borrow_until: Optional[float] = None
    borrow_from: Optional[str] = None


class ResourceItem(BaseModel):
    resource_id: str
    kind: Literal["image", "video", "audio", "youtube", "file"]
    name: str
    path_or_url: str
    mime_type: Optional[str] = None
    duration_sec: Optional[float] = None
    style_dna: Optional[Dict[str, Any]] = None


class VideoSpec(BaseModel):
    lifecycle: SpecLifecycle = "draft"
    title: str = "Untitled Project"
    project_mode: Literal[
        "text_to_video", "image_to_video", "photo_edit",
        "music_beat_video", "video_dubbing",
    ] = "text_to_video"
    aspect_ratio: Literal["16:9", "9:16", "1:1", "4:5"] = "16:9"
    resolution: Literal["720p", "1080p", "4K"] = "1080p"
    fps: Literal[24, 30, 60] = 30
    language: str = "Bengali"
    voice_profile: str = "bn-IN-BashkarNeural"
    visual_style: str = "Cinematic 2D Anime, high detail"
    story_outline: str = ""
    enable_subtitles: bool = True
    enable_beat_sync: bool = False
    scene_count: int = 4
    target_duration_sec: int = 20
    bgm_mood: str = "cinematic"


class ScenePlan(BaseModel):
    scene_number: int
    visual_prompt: str
    narration_text: str = ""
    subtitle_text: str = ""
    duration_sec: float = 4.0
    camera_motion: Literal[
        "ken_burns_in", "ken_burns_out", "pan_left",
        "pan_right", "zoom_punch", "shake_impact", "static",
    ] = "ken_burns_in"
    transition: Literal["fade", "cut_beat", "flash", "dissolve", "wipe"] = "fade"
    beat_trigger_sec: Optional[float] = None


class Asset(BaseModel):
    """The most critical model. 
    If verified is False, the UI will NEVER show this in Main Output."""
    asset_id: str
    kind: AssetKind
    filename: str
    public_url: str
    bytes: int
    verified: bool = False
    duration_sec: Optional[float] = None
    codec: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)


class ChatMessage(BaseModel):
    role: Literal["user", "director", "system", "checkpoint", "error-guide"]
    text: str
    tone: Literal["info", "success", "warn", "error", "neutral"] = "neutral"
    at: str = Field(default_factory=utc_now_iso)


class PipelineState(BaseModel):
    preflight: str = "pending"
    timelineSync: str = "pending"
    fontShaping: str = "pending"
    sampleRender: str = "pending"
    decodeTest: str = "pending"
    atomicPublish: str = "pending"


class ProjectState(BaseModel):
    project_id: str
    name: str = "Main Studio"
    status: str = "idle"
    spec: VideoSpec = Field(default_factory=VideoSpec)
    scenes: List[ScenePlan] = Field(default_factory=list)
    resources: List[ResourceItem] = Field(default_factory=list)
    chat: List[ChatMessage] = Field(default_factory=list)
    assets: List[Asset] = Field(default_factory=list)
    pipeline: PipelineState = Field(default_factory=PipelineState)
    progress: int = 0
    active_job_id: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


# ---------------- API Request schemas ----------------

class DetectKeyRequest(BaseModel):
    api_key: str
    custom_base_url: Optional[str] = None
    preferred_provider: Optional[str] = None
    agent_id: Optional[str] = None


class ApplyKeyRequest(BaseModel):
    provider_id: str
    api_key: str
    target_agents: List[str]
    selected_models: Dict[str, str] = Field(default_factory=dict)
    base_url: Optional[str] = None
    is_free_tier: bool = False


class TestAgentRequest(BaseModel):
    agent_id: str
    slot_id: str = "primary"


class SelfHealRequest(BaseModel):
    agent_id: str
    slot_id: str = "primary"


class SelfSwitchRequest(BaseModel):
    agent_id: str


class PromptRequest(BaseModel):
    prompt: str
    project_id: Optional[str] = None
    youtube_url: Optional[str] = None


class ApproveSpecRequest(BaseModel):
    project_id: str
    spec: VideoSpec


class DirectAgentChatRequest(BaseModel):
    agent_id: str
    message: str
    project_id: Optional[str] = None


class SaveProjectRequest(BaseModel):
    project_id: str
    name: str
