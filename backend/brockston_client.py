"""
BROCKSTON Client

Bridge interface for communicating with the BROCKSTON model.
Supports both HTTP endpoint and in-process calls.
"""

import httpx
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class BrockstonClient:
    """
    Client for interacting with the BROCKSTON model.

    Abstracts the communication layer so the backend doesn't need to know
    whether BROCKSTON is accessed via HTTP, gRPC, or in-process.
    """

    def __init__(self, base_url: Optional[str] = None, timeout: float = 120.0):
        """
        Initialize BROCKSTON client.

        Args:
            base_url: HTTP endpoint for BROCKSTON (e.g., 'http://localhost:6006')
                      If None, falls back to mock/in-process mode for development.
            timeout: Request timeout in seconds (default: 120s for LLM inference)
        """
        self.base_url = base_url
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout) if base_url else None

        if base_url:
            logger.info(f"BROCKSTON client initialized with endpoint: {base_url}")
        else:
            logger.warning("BROCKSTON client initialized in MOCK mode (no base_url provided)")

    async def chat(
        self,
        messages: List[Dict[str, str]],
        context: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Send a chat request to BROCKSTON.

        Args:
            messages: List of message dicts with 'role' and 'content' keys
                      Example: [
                          {"role": "system", "content": "You are BROCKSTON..."},
                          {"role": "user", "content": "Explain this code..."}
                      ]
            context: Optional context dict with 'path' and 'code' keys

        Returns:
            Assistant reply text from BROCKSTON

        Raises:
            RuntimeError: If BROCKSTON request fails
        """
        if not self.base_url:
            return self._mock_chat_response(messages, context)

        try:
            # Prepare request payload
            payload = {
                "messages": messages,
                "context": context or {}
            }

            # Make HTTP request to BROCKSTON
            response = await self.client.post(
                f"{self.base_url}/chat",
                json=payload
            )
            response.raise_for_status()

            result = response.json()
            return result.get("reply", "")

        except httpx.HTTPError as e:
            logger.error(f"BROCKSTON chat request failed: {e}")
            raise RuntimeError(f"Failed to communicate with BROCKSTON: {e}")

    async def suggest_fix(
        self,
        code: str,
        instruction: str,
        path: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Request BROCKSTON to suggest code improvements.

        Args:
            code: Current file contents
            instruction: What to do (e.g., "refactor for clarity", "fix bug")
            path: Optional file path for context

        Returns:
            Dict with keys:
                - 'proposed_code': Full rewritten version of the file
                - 'summary': Short description of changes

        Raises:
            RuntimeError: If BROCKSTON request fails
        """
        if not self.base_url:
            return self._mock_suggest_fix_response(code, instruction, path)

        try:
            # Prepare request payload
            payload = {
                "code": code,
                "instruction": instruction,
                "path": path
            }

            # Make HTTP request to BROCKSTON
            response = await self.client.post(
                f"{self.base_url}/suggest_fix",
                json=payload
            )
            response.raise_for_status()

            result = response.json()
            return {
                "proposed_code": result.get("proposed_code", ""),
                "summary": result.get("summary", "")
            }

        except httpx.HTTPError as e:
            logger.error(f"BROCKSTON suggest_fix request failed: {e}")
            raise RuntimeError(f"Failed to communicate with BROCKSTON: {e}")

    def _mock_chat_response(
        self,
        messages: List[Dict[str, str]],
        context: Optional[Dict[str, str]]
    ) -> str:
        """
        Mock chat response for development/testing when BROCKSTON is unavailable.
        """
        last_message = messages[-1]["content"] if messages else "No message"
        return (
            f"[MOCK BROCKSTON RESPONSE]\n\n"
            f"You asked: '{last_message}'\n\n"
            f"This is a mock response. Configure BROCKSTON_BASE_URL to connect "
            f"to the real BROCKSTON model.\n\n"
            f"Context: {context.get('path', 'No file') if context else 'No context'}"
        )

    def _mock_suggest_fix_response(
        self,
        code: str,
        instruction: str,
        path: Optional[str]
    ) -> Dict[str, str]:
        """
        Mock suggest_fix response for development/testing.
        """
        # Add a mock comment to the code
        mock_code = f"# MOCK FIX: {instruction}\n# File: {path or 'unknown'}\n\n{code}"

        return {
            "proposed_code": mock_code,
            "summary": (
                f"[MOCK] Applied instruction: '{instruction}'. "
                f"Configure BROCKSTON_BASE_URL to connect to the real BROCKSTON model."
            )
        }

    async def close(self):
        """Close the HTTP client."""
        if self.client:
            await self.client.aclose()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
