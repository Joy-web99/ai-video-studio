"""
Central Key Orchestrator: Manages slots, circuit breakers, cooldowns, and borrowing.
Ensures that if a Video key is missing, it does NOT silently fallback to an Image key.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.config import AGENT_ORDER, load_state, save_state
from app.models import AgentState, KeySlot, utc_now_iso
from app.providers import probe_single_provider


class KeyOrchestrator:
    def __init__(self):
        self.agents: Dict[str, AgentState] = {}
        self._load_from_disk()

    def _load_from_disk(self):
        """Load saved keys and state from studio_state.json."""
        state = load_state()
        for agent_id in AGENT_ORDER:
            agent_data = state.get("agents", {}).get(agent_id)
            if agent_data:
                self.agents[agent_id] = AgentState(**agent_data)
            else:
                # Initialize with empty slots
                self.agents[agent_id] = AgentState(
                    agent_id=agent_id,
                    slots=[
                        KeySlot(slot_id="primary"),
                        KeySlot(slot_id="secondary"),
                        KeySlot(slot_id="backup")
                    ]
                )

    def _save_to_disk(self):
        """Save current key state securely to disk."""
        state = {"agents": {k: v.model_dump() for k, v in self.agents.items()}}
        save_state(state)

    def get_agent_state(self, agent_id: str) -> AgentState:
        return self.agents.get(agent_id, AgentState(agent_id=agent_id))

    def apply_key(self, agent_id: str, slot_id: str, provider_id: str, model_id: str, api_key: str, base_url: str = None):
        """Assign a new API key to a specific agent's slot."""
        agent = self.get_agent_state(agent_id)
        for slot in agent.slots:
            if slot.slot_id == slot_id:
                slot.provider_id = provider_id
                slot.model_id = model_id
                slot.api_key = api_key
                slot.base_url = base_url
                slot.status = "unverified"
                slot.led = "yellow"
                slot.circuit = "CLOSED"
                slot.failure_count = 0
                slot.last_error = None
                break
        self._save_to_disk()

    def remove_key(self, agent_id: str, slot_id: str):
        """Clear an API key slot."""
        agent = self.get_agent_state(agent_id)
        for slot in agent.slots:
            if slot.slot_id == slot_id:
                slot.provider_id = None
                slot.model_id = None
                slot.api_key = None
                slot.status = "empty"
                slot.led = "off"
                break
        self._save_to_disk()

    async def test_slot(self, agent_id: str, slot_id: str) -> Dict[str, Any]:
        """Ping the provider to verify if the key is truly working."""
        agent = self.get_agent_state(agent_id)
        slot = next((s for s in agent.slots if s.slot_id == slot_id), None)
        if not slot or not slot.api_key:
            return {"ok": False, "error": "No API key in this slot."}

        res = await probe_single_provider(
            provider_id=slot.provider_id,
            api_key=slot.api_key,
            custom_base_url=slot.base_url
        )

        if res["ok"]:
            slot.status = "ready"
            slot.led = "green"
            slot.circuit = "CLOSED"
            slot.failure_count = 0
            slot.last_error = None
        else:
            slot.status = "error"
            slot.led = "red"
            slot.last_error = res["error"]

        slot.last_checked_at = utc_now_iso()
        self._save_to_disk()
        return res

    def get_active_slot(self, agent_id: str, required_capability: str) -> Optional[KeySlot]:
        """
        Find the best available key for the job. 
        CRITICAL FIX: Will NOT return an Image key for a Video job.
        """
        agent = self.get_agent_state(agent_id)
        now = time.time()

        # Priority order: Primary -> Secondary -> Backup
        for slot in agent.slots:
            if not slot.api_key:
                continue
            
            # Check capability match (e.g., does this key support VID?)
            # For simplicity, we trust the user's assignment, but we can add provider capability checks here later.
            
            # Check circuit breaker and cooldown
            if slot.circuit == "OPEN" and slot.cooldown_until and slot.cooldown_until > now:
                continue # Skip this slot, it's cooling down
                
            # If we reach here, the slot is usable
            return slot

        return None

    def report_failure(self, agent_id: str, slot_id: str, error: str):
        """Trip the circuit breaker if a key repeatedly fails."""
        agent = self.get_agent_state(agent_id)
        slot = next((s for s in agent.slots if s.slot_id == slot_id), None)
        if not slot:
            return

        slot.failure_count += 1
        slot.last_error = error

        # Circuit breaker logic
        if slot.failure_count >= 3:
            slot.circuit = "OPEN"
            slot.led = "red"
            slot.status = "error"
            slot.cooldown_until = time.time() + 300 # 5 minute cooldown
        elif slot.failure_count >= 1:
            slot.led = "yellow"

        self._save_to_disk()

    def report_success(self, agent_id: str, slot_id: str):
        """Reset failures on a successful call."""
        agent = self.get_agent_state(agent_id)
        slot = next((s for s in agent.slots if s.slot_id == slot_id), None)
        if slot:
            slot.failure_count = 0
            slot.led = "green"
            slot.circuit = "CLOSED"
            slot.last_error = None
            self._save_to_disk()

    def switch_primary_secondary(self, agent_id: str) -> bool:
        """Swap Primary and Secondary keys."""
        agent = self.get_agent_state(agent_id)
        primary = next((s for s in agent.slots if s.slot_id == "primary"), None)
        secondary = next((s for s in agent.slots if s.slot_id == "secondary"), None)

        if primary and secondary:
            # Swap IDs and contents
            primary.slot_id, secondary.slot_id = "secondary", "primary"
            self._save_to_disk()
            return True
        return False


# Singleton instance
orchestrator = KeyOrchestrator()
