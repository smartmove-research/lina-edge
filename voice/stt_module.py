# voice/stt_module.py

import os
import logging
import asyncio
import httpx
import uuid
from config import Config
from pathlib import Path


config = Config.get_config()


class STTModule:
    """
    Speech-to-text client for ASR service.
    """

    async def transcribe(self, audio_path: str) -> str:
        logging.info(f"Transcribing … {audio_path}")
        # Build URL, ensure no double-slash
        url = config["host"]["url"].rstrip("/") + config["asr"]["endpoint"]
        logging.info(f"Transcribe URL: {url}")

        filename = os.path.basename(audio_path)
        headers = {"accept": "application/json"}

        async with httpx.AsyncClient() as client:
            # open file inside context to ensure it’s closed
            with open(audio_path, "rb") as f:
                files = {
                    "audio_file": (
                        filename,
                        f,
                        "audio/wav",
                    )
                }
                response = await client.post(url, files=files, headers=headers)

        if response.status_code == 200:
            transcription = response.json().get("transcript", "")
            return transcription
        else:
            logging.error("REQUEST Failed %s %s",
                          response.status_code, response.text)
            return ""
    
    async def chat(
        self,
        prompt: str,
        user_id: str,
        temperature: float = 0.7,
        max_tokens: int = 100
    ) -> str:
        """
        Send a chat-completion request to the ASR/chat endpoint.
        """
        logging.info(f"Chat request → prompt={prompt!r}, user_id={user_id!r}")

        # Build URL (e.g. "http://27.106.106.102:8000" + "/chat/")
        url = config["host"]["url"].rstrip("/") + config["chat"]["endpoint"]
        logging.info(f"Chat URL: {url}")

        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
        }

        payload = {
            "prompt": prompt,
            "user_id": user_id,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code == 200:
            # adjust key if your API uses something else (e.g. "reply" or "message")
            return resp.json().get("response", "")
        else:
            logging.error("Chat request failed %d %s", resp.status_code, resp.text)
            return "Sorry but I failed to get an answer"

    async def synthesize_speech(self, text: str, *, output_dir: str = "tmp") -> Path:
        """
        Send `text` to the TTS service and save the returned audio to a file.
        
        :param text: The text to be synthesized.
        :param output_dir: Directory where the audio file will be written.
        :return: Path to the saved audio file.
        """
        url = config["host"]["url"].rstrip("/") + config["tts"]["endpoint"]
        print("TTS URL:", url)
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

if __name__ == "__main__":
    # Simple runner for testing from the command-line
    async def main_synth():
        stt = STTModule()
        path = await stt.synthesize_speech("Greetings Master Lyne! I hope you are good today")
        print(f"Audio saved to {path}")
    async def main_trans():
        stt = STTModule()
        transcript = await stt.transcribe("sounds/recording_speech.wav")
        print(transcript)

    asyncio.run(main_synth())
