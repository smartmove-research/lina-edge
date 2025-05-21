# app/tts/tts_client.py

import uuid
import os
import httpx
from pathlib import Path
import asyncio

async def synthesize_speech(text: str, *, output_dir: str = "tmp") -> Path:
    """
    Send `text` to the TTS service and save the returned audio to a file.
    
    :param text: The text to be synthesized.
    :param output_dir: Directory where the audio file will be written.
    :return: Path to the saved audio file.
    """
    url = "http://127.0.0.1:8000/tts/"
    payload = {"text": text}
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json=payload,
            headers={"Accept": "application/json"},
            timeout=30.0
        )
        response.raise_for_status()
        audio_bytes = response.content

    # Write to a uniquely-named file
    filename = f"tts_{uuid.uuid4().hex}.mp3"
    output_path = Path(output_dir) / filename
    output_path.write_bytes(audio_bytes)
    return output_path

async def main():
    path = await synthesize_speech("Greetings Master Ryan! I hope you are good today")
    print(f"Audio saved to {path}")

if __name__ == "__main__":
    asyncio.run(main())