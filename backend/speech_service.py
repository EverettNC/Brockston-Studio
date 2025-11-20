"""
Speech Service

Handles speech-to-text transcription and text-to-speech synthesis.
Uses OpenAI's Whisper API for transcription and TTS API for synthesis.
"""

import os
import logging
from pathlib import Path
from typing import Optional
import httpx

logger = logging.getLogger(__name__)


class SpeechService:
    """
    Service for speech operations: transcription and synthesis.

    Uses OpenAI's APIs for both operations:
    - Whisper API for speech-to-text
    - TTS API for text-to-speech
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize speech service.

        Args:
            api_key: OpenAI API key (optional, falls back to OPENAI_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = "https://api.openai.com/v1"
        self.timeout = 60.0  # 60 seconds for audio processing

        if self.api_key:
            logger.info("Speech service initialized with OpenAI API")
        else:
            logger.warning("Speech service initialized in MOCK mode (no API key)")

    async def transcribe_audio(self, audio_data: bytes, filename: str = "audio.webm") -> str:
        """
        Transcribe audio to text using OpenAI Whisper API.

        Args:
            audio_data: Audio file bytes (supports mp3, mp4, mpeg, mpga, m4a, wav, webm)
            filename: Name of the audio file (with extension)

        Returns:
            Transcribed text

        Raises:
            RuntimeError: If transcription fails
        """
        if not self.api_key:
            return self._mock_transcribe(audio_data, filename)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Prepare multipart form data
                files = {
                    "file": (filename, audio_data, "audio/webm")
                }
                data = {
                    "model": "whisper-1"
                }
                headers = {
                    "Authorization": f"Bearer {self.api_key}"
                }

                # Make request to Whisper API
                response = await client.post(
                    f"{self.base_url}/audio/transcriptions",
                    files=files,
                    data=data,
                    headers=headers
                )
                response.raise_for_status()

                result = response.json()
                transcribed_text = result.get("text", "")

                logger.info(f"Transcribed audio: {transcribed_text[:100]}...")
                return transcribed_text

        except httpx.HTTPError as e:
            logger.error(f"Transcription failed: {e}")
            raise RuntimeError(f"Failed to transcribe audio: {e}")

    async def synthesize_speech(self, text: str, voice: str = "alloy") -> bytes:
        """
        Convert text to speech using OpenAI TTS API.

        Args:
            text: Text to convert to speech
            voice: Voice to use (alloy, echo, fable, onyx, nova, shimmer)

        Returns:
            Audio data as bytes (MP3 format)

        Raises:
            RuntimeError: If synthesis fails
        """
        if not self.api_key:
            return self._mock_synthesize(text, voice)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Prepare request payload
                payload = {
                    "model": "tts-1",
                    "input": text,
                    "voice": voice,
                    "response_format": "mp3"
                }
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }

                # Make request to TTS API
                response = await client.post(
                    f"{self.base_url}/audio/speech",
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()

                audio_data = response.content
                logger.info(f"Synthesized speech: {len(audio_data)} bytes")
                return audio_data

        except httpx.HTTPError as e:
            logger.error(f"Speech synthesis failed: {e}")
            raise RuntimeError(f"Failed to synthesize speech: {e}")

    def _mock_transcribe(self, audio_data: bytes, filename: str) -> str:
        """
        Mock transcription for development/testing.
        """
        logger.info(f"MOCK: Received {len(audio_data)} bytes of audio ({filename})")
        return (
            "This is a mock transcription. "
            "Configure OPENAI_API_KEY to use real speech-to-text. "
            f"Audio file size: {len(audio_data)} bytes."
        )

    def _mock_synthesize(self, text: str, voice: str) -> bytes:
        """
        Mock speech synthesis for development/testing.
        Returns a minimal valid MP3 header to avoid errors.
        """
        logger.info(f"MOCK: Would synthesize with voice '{voice}': {text[:100]}...")
        # Minimal MP3 header (valid but empty audio)
        # This prevents errors when the frontend tries to play it
        mp3_header = b'\xff\xfb\x90\x00' + b'\x00' * 100
        return mp3_header
