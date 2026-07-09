"""
NemoClaw — NVIDIA agent instructor for Brockston Studio.
Routes through Nemotron 3 Ultra with NemoClaw agent persona and full tool loop.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from .nemo_service import get_nemo_service

logger = logging.getLogger(__name__)

_ABILITIES_HINT = (
    "You operate Brockston Studio as a NemoClaw agent. "
    "Emit <tool_call>{\"tool\":\"ls|read|patch|run|...\", ...}</tool_call> to act on disk. "
    "Verify each step. You watch the IDE live via WS /ws/viewer."
)

NEMOCLAW_SYSTEM = f"""You are NemoClaw — the NVIDIA agent layer inside Brockston Studio for The Christman AI Project.
Everett Christman is your operator. You are an autonomous IDE agent: explore the workspace,
read files, patch code, run commands, and report results honestly.
Follow NemoClaw discipline: verify before you claim, cite paths you touched, fail loud on errors.
{_ABILITIES_HINT}
How can you help Everett love himself more while shipping real fixes today?"""


class NemoClawService:
    """NemoClaw agent line — Nemotron-backed with agent-first behavior."""

    def __init__(self):
        self._nemo = get_nemo_service()
        logger.info(
            "[NemoClawService] online — model=%s nvidia=%s",
            self._nemo.wiring_info("code").get("model"),
            self._nemo.uses_nvidia,
        )

    @property
    def is_available(self) -> bool:
        return self._nemo.is_available

    @property
    def uses_nvidia(self) -> bool:
        return self._nemo.uses_nvidia

    def wiring_info(self) -> Dict[str, Any]:
        base = self._nemo.wiring_info("code")
        return {
            **base,
            "backend": base.get("backend", "nvidia"),
            "label": f"NemoClaw → {base.get('label', 'nemotron')}",
            "agent": "nemoclaw",
        }

    def generate_content(
        self,
        prompt: str,
        context: Optional[str] = None,
    ) -> str:
        system = NEMOCLAW_SYSTEM
        if context:
            system = f"{system}\n\n{context}"
        return self._nemo.generate_content(
            prompt,
            mode="code",
            system_override=system,
        )


_nemoclaw_instance: Optional[NemoClawService] = None


def get_nemoclaw_service() -> NemoClawService:
    global _nemoclaw_instance
    if _nemoclaw_instance is None:
        _nemoclaw_instance = NemoClawService()
    return _nemoclaw_instance