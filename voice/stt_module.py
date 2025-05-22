# voice/stt_module.py

import os
import logging
import asyncio
import time
import httpx
import uuid
from pathlib import Path
from config import Config

config = Config.get_config()
logger = logging.getLogger(__name__)

class STTModule:
    """
    Resilient Speech-to-text / Chat / TTS client,
    using manual retry/back-off and built-in timeouts.
    """

    def __init__(self,
                 timeout: float = 10.0,
                 max_retries: int = 3,
                 backoff_factor: float = 1.0):
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    async def _post(self, url: str, **kwargs) -> httpx.Response:
        """
        POST with retries on network errors/timeouts.
        """
        delay = self.backoff_factor
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, **kwargs)
                    resp.raise_for_status()
                    return resp
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
                logger.warning("Request to %s failed (attempt %d/%d): %s",
                               url, attempt, self.max_retries, e)
                if attempt == self.max_retries:
                    logger.error("Max retries reached for %s", url)
                    raise
                await asyncio.sleep(delay)
                delay *= 2
            except httpx.HTTPStatusError as e:
                # 4xx or 5xx: no point retrying
                logger.error("Server returned error for %s: %s", url, e)
                raise

    async def transcribe(self, audio_path: str) -> str:
        if not os.path.isfile(audio_path):
            logger.warning("transcribe: file not found %s", audio_path)
            return ""

        url = config["host"]["url"].rstrip("/") + config["asr"]["endpoint"]
        logger.debug("Transcribing %s → %s", audio_path, url)

        try:
            filename = Path(audio_path).name
            headers = {"Accept": "application/json"}
            with open(audio_path, "rb") as f:
                files = {"audio_file": (filename, f, "audio/wav")}
                resp = await self._post(url, files=files, headers=headers)
            return resp.json().get("transcript", "")
        except Exception as e:
            logger.error("transcribe failed: %s", e, exc_info=True)
            return ""

    async def chat(self,
                   prompt: str,
                   user_id: str,
                   temperature: float = 0.7,
                   max_tokens: int = 100) -> str:
        url = config["host"]["url"].rstrip("/") + config["chat"]["endpoint"]
        payload = {
            "prompt": prompt,
            "user_id": user_id,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        logger.debug("Chat request → %s %r", url, payload)

        try:
            resp = await self._post(url, json=payload, headers=headers)
            return resp.json().get("response", "")
        except Exception as e:
            logger.error("chat failed: %s", e, exc_info=True)
            return "Sorry, something went wrong."

    async def synthesize_speech(self,
                                text: str,
                                *,
                                output_dir: str = "tmp") -> Path:
        url = config["host"]["url"].rstrip("/") + config["tts"]["endpoint"]
        payload = {"text": text}
        headers = {"Accept": "application/json"}

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        filename = f"tts_{uuid.uuid4().hex}.mp3"
        out_path = Path(output_dir) / filename

        logger.debug("TTS request → %s %r", url, payload)
        try:
            resp = await self._post(url, json=payload, headers=headers)
            out_path.write_bytes(resp.content)
            logger.info("TTS audio saved to %s", out_path)
        except Exception as e:
            logger.error("synthesize_speech failed: %s", e, exc_info=True)
            try:
                out_path = Path("sounds") / "tts_error.mp3"
            except Exception as e:
                logger.error("Failed to assign fallback path")
        return out_path

if __name__ == "__main__":
    async def _test():
        stt = STTModule()
        print("Transcription:", await stt.transcribe("sounds/recording_speech.wav"))
        print("Chat reply:", await stt.chat("Hello!", "user123"))
        tts_path = await stt.synthesize_speech("Test speech output")
        print("TTS saved to:", tts_path)

    # ensure logging shows up on console
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(_test())
