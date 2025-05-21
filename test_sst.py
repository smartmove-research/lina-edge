from voice.stt_module import STTModule
import asyncio
stt = STTModule

async def main():
    text = await stt.transcribe("sounds/recording_speech.wav")
    print("Transcription", text)

asyncio.run(main())