"""
Unified AI Client

Manages communication with AI models.
UPDATED: Falls back to OpenAI if local models (Brockston/UltimateEV) are offline.
"""

import os
import httpx
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

class AIClient:
    """
    Unified client for interacting with AI models.
    Now supports direct OpenAI connection for the 'Brockston' persona.
    """

    def __init__(
        self,
        brockston_url: Optional[str] = None,
        ultimateev_url: Optional[str] = None,
        timeout: float = 120.0
    ):
        # Load API Key from Environment
        self.api_key = os.getenv("OPENAI_API_KEY")
        
        # Configuration
        self.endpoints = {
            "brockston": brockston_url,
            "ultimateev": ultimateev_url
        }
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)

        logger.info("AI Client Initialized.")
        if self.api_key:
            logger.info("  - OpenAI Link: ACTIVE (Primary)")
        else:
            logger.warning("  - OpenAI Link: INACTIVE (No Key Found)")

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: str = "brockston",
        context: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Send a chat request. 
        Priority: Local URL -> OpenAI -> Mock.
        """
        # 1. Add System Context if available
        if context and context.get('code'):
            system_msg = f"Current File Context ({context.get('path')}):\n\n{context.get('code')}"
            messages.insert(0, {"role": "system", "content": system_msg})

        # 2. Try OpenAI (The Reliable Brain)
        if self.api_key:
            try:
                return await self._chat_openai(messages)
            except Exception as e:
                logger.error(f"OpenAI Connection Failed: {e}")
                # Fall through to other methods if OpenAI fails
        
        # 3. Try Local Endpoint (The Custom Brain)
        base_url = self._get_endpoint(model)
        if base_url:
            try:
                return await self._chat_local(base_url, messages, context)
            except Exception as e:
                logger.warning(f"Local Brain {model} failed: {e}")

        # 4. Give Up (Mock)
        return self._mock_chat_response(messages, model, context)

    async def _chat_openai(self, messages: List[Dict[str, str]]) -> str:
        """Direct connection to OpenAI."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-4-turbo", # Or gpt-3.5-turbo
            "messages": messages,
            "temperature": 0.7
        }
        
        response = await self.client.post(
            "https://api.openai.com/v1/chat/completions",
            json=payload,
            headers=headers
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def _chat_local(self, base_url, messages, context):
        """Connection to local microservices (port 6006/6007)."""
        payload = {"messages": messages, "context": context or {}}
        response = await self.client.post(f"{base_url}/chat", json=payload)
        response.raise_for_status()
        return response.json().get("reply", "")

    async def suggest_fix(
        self,
        code: str,
        instruction: str,
        model: str = "brockston",
        path: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Ask AI to fix code. Uses OpenAI directly.
        """
        if not self.api_key:
            return self._mock_suggest_fix_response(code, instruction, model, path)

        prompt = f"Instruction: {instruction}\n\nFile: {path}\n\nCode:\n{code}\n\nReturn only the fixed code."
        messages = [
            {"role": "system", "content": "You are a coding assistant. Return the full fixed code block only."},
            {"role": "user", "content": prompt}
        ]

        try:
            fixed_code = await self._chat_openai(messages)
            return {
                "proposed_code": fixed_code,
                "summary": f"Applied fix: {instruction}"
            }
        except Exception as e:
            logger.error(f"Fix failed: {e}")
            return self._mock_suggest_fix_response(code, instruction, model, path)

    def _get_endpoint(self, model: str) -> Optional[str]:
        return self.endpoints.get(model.lower())

    def _mock_chat_response(self, messages, model, context):
        return "[SYSTEM ERROR]: No AI Brain connected. Please check OPENAI_API_KEY in .env."

    def _mock_suggest_fix_response(self, code, instruction, model, path):
        return {
            "proposed_code": code,
            "summary": "Error: No AI available to process fix."
        }

    async def close(self):
        if self.client:
            await self.client.aclose()
