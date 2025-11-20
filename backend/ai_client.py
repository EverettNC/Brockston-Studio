"""
Unified AI Client

Manages communication with multiple AI models (BROCKSTON, UltimateEV).
Routes requests to the appropriate model based on user selection.
"""

import httpx
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class AIClient:
    """
    Unified client for interacting with multiple AI models.

    Supports BROCKSTON and UltimateEV, routing requests to the
    appropriate endpoint based on model selection.
    """

    def __init__(
        self,
        brockston_url: Optional[str] = None,
        ultimateev_url: Optional[str] = None,
        timeout: float = 120.0
    ):
        """
        Initialize AI client with multiple model endpoints.

        Args:
            brockston_url: HTTP endpoint for BROCKSTON (e.g., 'http://localhost:6006')
            ultimateev_url: HTTP endpoint for UltimateEV (e.g., 'http://localhost:6007')
            timeout: Request timeout in seconds (default: 120s for LLM inference)
        """
        self.endpoints = {
            "brockston": brockston_url,
            "ultimateev": ultimateev_url
        }
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)

        logger.info(f"AI client initialized:")
        logger.info(f"  - BROCKSTON: {brockston_url or 'MOCK MODE'}")
        logger.info(f"  - UltimateEV: {ultimateev_url or 'MOCK MODE'}")

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: str = "brockston",
        context: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Send a chat request to the specified AI model.

        Args:
            messages: List of message dicts with 'role' and 'content' keys
            model: Which model to use ('brockston' or 'ultimateev')
            context: Optional context dict with 'path' and 'code' keys

        Returns:
            Assistant reply text from the AI model

        Raises:
            ValueError: If model is not supported
            RuntimeError: If AI request fails
        """
        base_url = self._get_endpoint(model)

        if not base_url:
            return self._mock_chat_response(messages, model, context)

        try:
            # Prepare request payload
            payload = {
                "messages": messages,
                "context": context or {}
            }

            # Make HTTP request to AI model
            response = await self.client.post(
                f"{base_url}/chat",
                json=payload
            )
            response.raise_for_status()

            result = response.json()
            return result.get("reply", "")

        except httpx.HTTPError as e:
            logger.error(f"{model.upper()} chat request failed: {e}")
            raise RuntimeError(f"Failed to communicate with {model.upper()}: {e}")

    async def suggest_fix(
        self,
        code: str,
        instruction: str,
        model: str = "brockston",
        path: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Request AI model to suggest code improvements.

        Args:
            code: Current file contents
            instruction: What to do (e.g., "refactor for clarity", "fix bug")
            model: Which model to use ('brockston' or 'ultimateev')
            path: Optional file path for context

        Returns:
            Dict with keys:
                - 'proposed_code': Full rewritten version of the file
                - 'summary': Short description of changes

        Raises:
            ValueError: If model is not supported
            RuntimeError: If AI request fails
        """
        base_url = self._get_endpoint(model)

        if not base_url:
            return self._mock_suggest_fix_response(code, instruction, model, path)

        try:
            # Prepare request payload
            payload = {
                "code": code,
                "instruction": instruction,
                "path": path
            }

            # Make HTTP request to AI model
            response = await self.client.post(
                f"{base_url}/suggest_fix",
                json=payload
            )
            response.raise_for_status()

            result = response.json()
            return {
                "proposed_code": result.get("proposed_code", ""),
                "summary": result.get("summary", "")
            }

        except httpx.HTTPError as e:
            logger.error(f"{model.upper()} suggest_fix request failed: {e}")
            raise RuntimeError(f"Failed to communicate with {model.upper()}: {e}")

    def _get_endpoint(self, model: str) -> Optional[str]:
        """
        Get the endpoint URL for a specific model.

        Args:
            model: Model name ('brockston' or 'ultimateev')

        Returns:
            Base URL for the model, or None if not configured

        Raises:
            ValueError: If model is not supported
        """
        model_lower = model.lower()
        if model_lower not in self.endpoints:
            raise ValueError(
                f"Unsupported model: {model}. "
                f"Supported models: {', '.join(self.endpoints.keys())}"
            )
        return self.endpoints[model_lower]

    def _mock_chat_response(
        self,
        messages: List[Dict[str, str]],
        model: str,
        context: Optional[Dict[str, str]]
    ) -> str:
        """
        Mock chat response for development/testing when AI model is unavailable.
        """
        last_message = messages[-1]["content"] if messages else "No message"
        model_name = model.upper()
        return (
            f"[MOCK {model_name} RESPONSE]\n\n"
            f"You asked: '{last_message}'\n\n"
            f"This is a mock response. Configure {model_name}_BASE_URL to connect "
            f"to the real {model_name} model.\n\n"
            f"Context: {context.get('path', 'No file') if context else 'No context'}"
        )

    def _mock_suggest_fix_response(
        self,
        code: str,
        instruction: str,
        model: str,
        path: Optional[str]
    ) -> Dict[str, str]:
        """
        Mock suggest_fix response for development/testing.
        """
        model_name = model.upper()
        mock_code = f"# MOCK FIX from {model_name}: {instruction}\n# File: {path or 'unknown'}\n\n{code}"

        return {
            "proposed_code": mock_code,
            "summary": (
                f"[MOCK] Applied instruction: '{instruction}' using {model_name}. "
                f"Configure {model_name}_BASE_URL to connect to the real model."
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
