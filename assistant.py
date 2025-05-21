# app.py

import asyncio
from core.event_bus import EventBus
from audio.audio_module import AudioModule
from vision.vision_module import VisionModule
from voice.voice_module import VoiceModule
from voice.stt_module import STTModule
from voice.command_parser import CommandParser
from events.events import UserCommand

async def main():
    bus     = EventBus()
    audio   = AudioModule()
    vision  = VisionModule(bus)
    stt     = STTModule()    # Do not instatiate
    parser  = CommandParser()
    voice   = VoiceModule(bus, audio, vision, stt, parser)

    # subscribe to user commands
    def handle_user_command(ev: UserCommand):
        print(f"[APP] Got UserCommand: {ev.command}, params={ev.params}")
        # e.g. if ev.command == "describe": kick off captioning or LLM
    bus.subscribe(UserCommand, handle_user_command)

    # start all modules
    audio.start_scheduler()
    vision.start()
    voice.start()

    # run forever
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
