"""
Security & Credential Hygiene: Masks API keys so they are never exposed 
to the frontend or browser network tabs.
"""
from __future__ import annotations

from typing import Any, Dict

def mask_api_key(key: str | None) -> str:
    """Masks an API key for safe display (e.g., 'sk-...a1b2')."""
    if not key:
        return ""
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"

def sanitize_agent_state(agent_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Takes the agent state dictionary and masks all API keys before 
    sending it to the frontend via the bootstrap API.
    """
    safe_state = agent_state.copy()
    if "slots" in safe_state and isinstance(safe_state["slots"], list):
        safe_slots = []
        for slot in safe_state["slots"]:
            safe_slot = slot.copy()
            if "api_key" in safe_slot:
                safe_slot["api_key"] = mask_api_key(safe_slot.get("api_key"))
            safe_slots.append(safe_slot)
        safe_state["slots"] = safe_slots
    return safe_state

def sanitize_orchestrator_state(orchestrator_agents: Dict[str, Any]) -> Dict[str, Any]:
    """Masks keys for all 5 agents."""
    return {
        agent_id: sanitize_agent_state(state)
        for agent_id, state in orchestrator_agents.items()
    }

def sanitize_filename(filename: str) -> str:
    """Prevents directory traversal attacks (e.g., ../../etc/passwd)."""
    import re
    # Keep only alphanumeric, dots, underscores, and hyphens
    safe = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
    # Remove leading dots or path separators
    return safe.lstrip('.')
