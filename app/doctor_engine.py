# ==============================================================================
# AI Video Production Studio - System Doctor & Pre-Flight Guard (Part E1)
# Covers: Pre-Flight Readiness Check, Structured Error/Disturbance Diagnostics
#         (English + Bangla) & Deep Doctor Bar Report
# ==============================================================================

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from app.config import (
    AGENT_DEFINITIONS,
    AGENT_ORDER,
    OUTPUTS_DIR,
    PROJECTS_DIR,
    TEMP_DIR,
    UPLOADS_DIR,
    get_provider_by_id,
)
from app.models import AgentSlot, AgentState, ProjectState, utc_now_iso
from app.provider_engine import probe_single_provider, translate_error_to_bangla


def build_disturbance_card(
    agent_id: str,
    slot: Optional[AgentSlot],
    error_en: str,
    context_hint: str = "",
) -> Dict[str, Any]:
    """
    Create a WhatsApp-style disturbance card payload for the Workflow bottom bar:
      1. Affected agent name
      2. Model name & provider name
      3. Original technical/server error in English
      4. Clear summary & guidance in Bangla
    """
    meta = AGENT_DEFINITIONS.get(agent_id, {})
    agent_label = meta.get("name", str(agent_id).title())
    model_name = slot.model_id if slot and slot.model_id else "unassigned-model"
    provider_name = slot.provider_name if slot and slot.provider_name else "unassigned-provider"
    clean_en = (error_en or "Unknown execution disturbance").strip()
    clean_bn = translate_error_to_bangla(clean_en)

    if context_hint:
        clean_bn = f"{clean_bn} ({context_hint})"

    return {
        "agent_id": agent_id,
        "agent_label": agent_label,
        "model_name": model_name,
        "provider_name": provider_name,
        "error_en": clean_en,
        "summary_bn": clean_bn,
        "timestamp": utc_now_iso(),
    }


def run_preflight_guard(
    project: ProjectState,
    agents: Dict[str, AgentState],
) -> Dict[str, Any]:
    """
    Verify workspace paths, required tools (FFmpeg), and agent readiness before
    starting heavy video, dubbing, or audio production so mid-run stalls are minimized.
    """
    issues: List[Dict[str, str]] = []
    warnings: List[str] = []

    ffmpeg_ok = bool(shutil.which("ffmpeg"))
    ffprobe_ok = bool(shutil.which("ffprobe"))
    if not ffmpeg_ok:
        issues.append({
            "agent_id": "editing",
            "error_en": "FFmpeg binary not found in system PATH.",
            "summary_bn": "সিস্টেমে FFmpeg পাওয়া যায়নি—ভিডিও রেন্ডার বা এডিট করা সম্ভব নয়।",
        })
    if not ffprobe_ok:
        warnings.append("FFprobe অনুপস্থিত; বিকল্প পদ্ধতিতে মিডিয়ার সময় মাপা হবে।")

    for d in (OUTPUTS_DIR, UPLOADS_DIR, TEMP_DIR, PROJECTS_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            issues.append({
                "agent_id": "editing",
                "error_en": f"Directory not writable ({d}): {exc}",
                "summary_bn": f"ফোল্ডারে লেখার অনুমতি নেই ({d.name})।",
            })

    mode = project.spec.project_mode
    if mode == "video_dubbing":
        has_vid = any(r.kind == "video" and Path(r.path_or_url).exists() for r in project.resources)
        if not has_vid:
            issues.append({
                "agent_id": "video",
                "error_en": "No uploaded source video found for Video Dubbing mode.",
                "summary_bn": "ভিডিও ডাবিংয়ের জন্য কোনো সোর্স ভিডিও ফাইল যুক্ত করা হয়নি।",
            })

    active_agents = [
        aid for aid in AGENT_ORDER
        if agents.get(aid) and any(s.status in ("active", "ready", "working") for s in agents[aid].slots)
    ]
    if not active_agents:
        warnings.append("কোনো এজেন্টে সরাসরি সক্রিয় API Key নেই—অন্য এজেন্টের শেয়ার বা ফ্রি ব্যাকআপ যাচাই করা হবে।")

    return {
        "ok": len(issues) == 0,
        "ffmpeg_available": ffmpeg_ok,
        "ffprobe_available": ffprobe_ok,
        "active_agents": active_agents,
        "issues": issues,
        "warnings": warnings,
        "checked_at": utc_now_iso(),
    }
  async def _ask_doctor_ai_bangla(
    doctor_api_key: str,
    doctor_provider_id: Optional[str],
    diagnostic_payload: Dict[str, Any],
) -> Optional[str]:
    """Optional deep AI analysis using a dedicated Doctor API key when provided."""
    key = (doctor_api_key or "").strip()
    if not key:
        return None

    prov = get_provider_by_id(doctor_provider_id or "openrouter")
    base_url = (prov.get("base_url") if prov else "https://openrouter.ai/api/v1").rstrip("/")
    model_id = "openrouter/free" if (prov and prov.get("id") == "openrouter") else "gpt-4o-mini"

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if "openrouter" in base_url:
        headers["HTTP-Referer"] = "https://ai-video-studio.local"
        headers["X-Title"] = "AI Video Production Studio Doctor"

    prompt_text = (
        "You are the System Doctor for an AI Video Production Studio. "
        "Analyze this diagnostic report and provide a concise, practical checklist in clear Bangla "
        "(with essential English technical terms like API Key, Model, FFmpeg, Primary/Secondary) "
        "on how to fix any issues:\n"
        f"{diagnostic_payload}"
    )

    body = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": "Reply concisely in natural Bangla with helpful English tech terms."},
            {"role": "user", "content": prompt_text},
        ],
        "max_tokens": 500,
    }

    try:
        async with httpx.AsyncClient(timeout=18.0) as client:
            resp = await client.post(f"{base_url}/chat/completions", headers=headers, json=body)
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices") or []
                if choices and isinstance(choices[0], dict):
                    msg = choices[0].get("message") or {}
                    content = (msg.get("content") or "").strip()
                    if content:
                        return content
    except Exception:
        return None
    return None


async def run_full_doctor_check(
    project: ProjectState,
    agents: Dict[str, AgentState],
    doctor_api_key: Optional[str] = None,
    doctor_provider_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run a complete diagnostic scan across FFmpeg, workspace directories, and all 5 agents'
    Primary/Secondary/Backup slots, returning both raw checks and a Bangla checklist.
    """
    preflight = run_preflight_guard(project, agents)
    agent_reports: List[Dict[str, Any]] = []
    checklist_bn: List[str] = []

    if preflight["ffmpeg_available"]:
        checklist_bn.append("✅ FFmpeg প্রস্তুত আছে—ভিডিও ও অডিও রেন্ডারিং কাজ করবে।")
    else:
        checklist_bn.append("❌ FFmpeg পাওয়া যায়নি—সার্ভারে FFmpeg ইনস্টল করতে হবে।")

    for aid in AGENT_ORDER:
        st = agents.get(aid)
        label = AGENT_DEFINITIONS.get(aid, {}).get("name", aid.title())
        slots = st.slots if st else []
        ready_count = sum(1 for s in slots if s.status in ("active", "ready", "working"))
        err_slots = [s for s in slots if s.status == "error" or s.last_error]

        slot_details: List[Dict[str, Any]] = []
        for idx, s in enumerate(slots):
            probe = await probe_single_provider(s.provider_id, s.api_key, s.model_id, s.base_url)
            slot_details.append({
                "slot_id": s.slot_id,
                "role": "Primary" if idx == 0 else ("Secondary" if idx == 1 else f"Backup #{idx}"),
                "provider_id": s.provider_id,
                "provider_name": s.provider_name,
                "model_id": s.model_id,
                "status": s.status,
                "probe_ok": bool(probe.get("ok")),
                "probe_message": probe.get("message", ""),
            })

        agent_reports.append({
            "agent_id": aid,
            "agent_label": label,
            "total_slots": len(slots),
            "healthy_slots": ready_count,
            "error_count": len(err_slots),
            "slots": slot_details,
        })

        if not slots:
            checklist_bn.append(
                f"⚠️ {label}: কোনো API Key বসানো নেই—অন্য এজেন্টের শেয়ার বা নতুন Key যুক্ত করুন।"
            )
        elif err_slots:
            first_err = err_slots[0].last_error or "Connection or quota issue"
            bn_reason = translate_error_to_bangla(first_err)
            checklist_bn.append(
                f"🔴 {label}: সমস্যা পাওয়া গেছে ({bn_reason})—Self-Heal বা Secondary Switch ব্যবহার করুন।"
            )
        else:
            checklist_bn.append(
                f"🟢 {label}: {len(slots)}টি স্লট যুক্ত আছে এবং কাজের জন্য সুস্থ/প্রস্তুত।"
            )

    summary_payload = {
        "preflight": preflight,
        "agents": agent_reports,
    }
    ai_advice_bn = await _ask_doctor_ai_bangla(
        doctor_api_key or "",
        doctor_provider_id,
        summary_payload,
    )

    return {
        "ok": preflight["ok"],
        "preflight": preflight,
        "agents": agent_reports,
        "checklist_bn": checklist_bn,
        "ai_advice_bn": ai_advice_bn,
        "checked_at": utc_now_iso(),
  }
  
