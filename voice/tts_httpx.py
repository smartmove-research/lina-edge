# app/tts/tts_client.py

import uuid
import os
import logging
import asyncio
import httpx
from pathlib import Path

logger = logging.getLogger(__name__)

# Configuration
TTS_URL = "http://127.0.0.1:8000/tts/"
TIMEOUT = 10.0         # seconds per request
MAX_RETRIES = 3
BACKOFF_FACTOR = 1.0    # initial backoff in seconds

async def _post_with_retries(url: str, **kwargs) -> httpx.Response:
    delay = BACKOFF_FACTOR
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.post(url, **kwargs)
                resp.raise_for_status()
                return resp
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
            logger.warning(
                "TTS request failed (attempt %d/%d) to %s: %s",
                attempt, MAX_RETRIES, url, e
            )
            if attempt == MAX_RETRIES:
                logger.error("Max retries reached for TTS at %s", url)
                raise
            await asyncio.sleep(delay)
            delay *= 2
        except httpx.HTTPStatusError as e:
            # 4xx/5xx – won’t succeed on retry
            logger.error("TTS service returned HTTP %d: %s", e.response.status_code, e)
            raise

async def synthesize_speech(text: str, *, output_dir: str = "tmp") -> Path:
    """
    Send `text` to the TTS service and save the returned audio to a file.
    Uses timeouts, retries, and ensures output directory exists.
    """
    payload = {"text": text}
    headers = {"Accept": "application/json"}

    # Ensure output directory exists
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    try:
        logger.debug("Sending TTS payload to %s: %r", TTS_URL, payload)
        resp = await _post_with_retries(TTS_URL, json=payload, headers=headers)
        audio_bytes = resp.content

        # Write to a uniquely-named file
        filename = f"tts_{uuid.uuid4().hex}.mp3"
        output_path = Path(output_dir) / filename
        output_path.write_bytes(audio_bytes)
        logger.info("TTS audio saved to %s", output_path)
        return output_path

    except Exception as e:
        logger.error("Failed to synthesize speech: %s", e, exc_info=True)
        # Return a dummy Path so caller never sees None
        return Path(output_dir) / "tts_error.mp3"

async def main():
    # configure logging to console for testing
    logging.basicConfig(level=logging.DEBUG)
    path = await synthesize_speech("Greetings Master Ryan! I hope you are good today")
    print(f"Audio saved to {path}")

if __name__ == "__main__":
    asyncio.run(main())
