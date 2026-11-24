"""
System Doctor: Pre-flight checks, error diagnostics, and Bangla reporting.
Ensures FFmpeg is installed, directories are writable, and agent keys are healthy.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List

from app.config import (
    AGENTS, AGENT_ORDER, OUTPUTS_DIR, PROJECTS_DIR, TEMP_DIR, UPLOADS_DIR
)
from app.key_orchestrator import orchestrator
from app.providers import translate_error_to_bangla
from app.models import utc_now_iso


# ------------------------------------------------------------------------------
# 1. PRE-FLIGHT GUARD (Run before starting any heavy render)
# ------------------------------------------------------------------------------
def run_preflight_guard() -> Dict[str, Any]:
    """
    Verify workspace paths, required tools (FFmpeg), and agent readiness before
    starting heavy video, dubbing, or audio production.
    """
    issues: List[Dict[str, str]] = []
    warnings: List[str] = []

    # 1. Check FFmpeg / FFprobe
    ffmpeg_ok = bool(shutil.which("ffmpeg"))
    ffprobe_ok = bool(shutil.which("ffprobe"))
    
    if not ffmpeg_ok:
        issues.append({
            "agent_id": "editing",
            "error_en": "FFmpeg binary not found in system PATH.",
            "summary_bn": "সিস্টেমে FFmpeg পাওয়া যায়নি—ভিডিও রেন্ডার বা এডিট করা সম্ভব নয়।"
        })
    if not ffprobe_ok:
        warnings.append("FFprobe অনুপস্থিত; মিডিয়ার গুণমান যাচাই করা কঠিন হতে পারে।")

    # 2. Check Directory Permissions
    for d in (OUTPUTS_DIR, UPLOADS_DIR, TEMP_DIR, PROJECTS_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
            test_file = d / ".write_test"
            test_file.write_text("ok")
            test_file.unlink()
        except Exception as exc:
            issues.append({
                "agent_id": "editing",
                "error_en": f"Directory not writable ({d}): {exc}",
                "summary_bn": f"ফোল্ডারে লেখার অনুমতি নেই ({d.name})। সার্ভার রিস্টার্ট করুন।"
            })

    return {
        "ok": len(issues) == 0,
        "ffmpeg_available": ffmpeg_ok,
        "ffprobe_available": ffprobe_ok,
        "issues": issues,
        "warnings": warnings,
        "checked_at": utc_now_iso()
    }


# ------------------------------------------------------------------------------
# 2. FULL DOCTOR CHECK (Run when user clicks "Check" in Doctor Bar)
# ------------------------------------------------------------------------------
async def run_full_doctor_check() -> Dict[str, Any]:
    """
    Scans all 5 agents, checks slot statuses, and produces a Bangla checklist.
    """
    preflight = run_preflight_guard()
    agent_reports: List[Dict[str, Any]] = []
    checklist_bn: List[str] = []

    # Preflight checklist
    if preflight["ffmpeg_available"]:
        checklist_bn.append("✅ FFmpeg প্রস্তুত আছে—ভিডিও ও অডিও রেন্ডারিং কাজ করবে।")
    else:
        checklist_bn.append("❌ FFmpeg পাওয়া যায়নি—সার্ভারে FFmpeg ইনস্টল করতে হবে।")

    # Agent checklist
    for aid in AGENT_ORDER:
        agent_state = orchestrator.get_agent_state(aid)
        label = AGENTS.get(aid, {}).get("name", aid.title())
        
        healthy_slots = 0
        error_slots = 0
        empty_slots = 0
        slot_details = []

        for idx, slot in enumerate(agent_state.slots):
            role = "Primary" if idx == 0 else ("Secondary" if idx == 1 else "Backup")
            
            if not slot.api_key:
                empty_slots += 1
                status_text = "Empty"
            elif slot.status == "error" or slot.circuit == "OPEN":
                error_slots += 1
                status_text = "Error"
            else:
                healthy_slots += 1
                status_text = "Ready"

            slot_details.append({
                "role": role,
                "provider_id": slot.provider_id,
                "model_id": slot.model_id,
                "status": status_text,
                "error": slot.last_error
            })

        agent_reports.append({
            "agent_id": aid,
            "agent_label": label,
            "healthy_slots": healthy_slots,
            "error_slots": error_slots,
            "empty_slots": empty_slots,
            "slots": slot_details
        })

        # Generate Bangla summary per agent
        if healthy_slots > 0 and error_slots == 0:
            checklist_bn.append(f"🟢 {label}: এজেন্ট প্রস্তুত এবং কাজ করার জন্য সুস্থ আছে।")
        elif error_slots > 0:
            # Find the first error to explain
            first_err_slot = next((s for s in slot_details if s["status"] == "Error"), None)
            err_msg = first_err_slot["error"] if first_err_slot else "Connection Issue"
            bn_reason = translate_error_to_bangla(err_msg)
            checklist_bn.append(f"🔴 {label}: সমস্যা পাওয়া গেছে ({bn_reason})—Self-Heal বা Secondary Switch ব্যবহার করুন।")
        elif empty_slots == 3:
            checklist_bn.append(f"⚠️ {label}: কোনো API Key বসানো নেই—নতুন Key যুক্ত করুন।")

    return {
        "ok": preflight["ok"] and all(r["error_slots"] == 0 for r in agent_reports),
        "preflight": preflight,
        "agents": agent_reports,
        "checklist_bn": checklist_bn,
        "checked_at": utc_now_iso()
  }
