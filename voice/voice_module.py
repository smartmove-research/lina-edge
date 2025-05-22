import asyncio
import logging
import time
from uuid import uuid4
from typing import Any, List

from core.event_bus import EventBus
from events.events import UserCommand
from audio.audio_module import AudioModule
from vision.vision_module import VisionModule, ocr_image
from voice.stt_module import STTModule
from voice.command_parser import CommandParser

# Configure logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class VoiceModule:
    """
    Listens for speech (via VAD), transcribes it, grabs the current frame,
    parses the intent, and emits a UserCommand event.
    """
    def __init__(
        self,
        bus: EventBus,
        audio: AudioModule,
        vision: VisionModule,
        stt: STTModule,
        parser: CommandParser,
        silence_duration: float = 2.0,
    ):
        self.bus = bus
        self.audio = audio
        self.vision = vision
        self.stt = stt
        self.parser = parser
        self.silence_duration = silence_duration
        self._task: asyncio.Task = None

    def start(self):
        if self._task is None:
            try:
                # preload some sounds if needed
                self.audio.add_audio_to_queue("sounds/waterdropletechoed.wav")
            except Exception as e:
                logger.error("Failed to preload audio: %s", e, exc_info=True)

            self._task = asyncio.create_task(self._run())
            logger.info("VoiceModule started")

    def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None
            logger.info("VoiceModule stopped")

    async def _run(self):
        while True:
            try:
                logger.info("Waiting for user speech...")
                # record audio
                try:
                    pid = self.audio.schedule("sounds/waterdropletechoed.wav", priority=0, loop=True)
                except Exception as e:
                    logger.warning("Failed to play prompt sound: %s", e, exc_info=True)
                    pid = None

                try:
                    audio_path = await asyncio.wait_for(
                        self.audio.record(silence_duration=self.silence_duration),
                        timeout=self.silence_duration + 5
                    )
                    logger.info("Recorded audio: %s", audio_path)
                except Exception as e:
                    logger.error("Audio recording failed: %s", e, exc_info=True)
                    audio_path = None

                # stop prompt sound
                if pid is not None:
                    try:
                        self.audio.stop_sound(pid)
                    except Exception:
                        pass

                # capture frame
                frame_path = None
                try:
                    frame = self.vision.latest_frame
                    frame_path = self.vision.save_frame(frame)
                    logger.info("Saved frame: %s", frame_path)
                except Exception as e:
                    logger.error("Frame capture failed: %s", e, exc_info=True)

                # transcription
                userinput = ""
                if audio_path:
                    try:
                        if self.stt:
                            userinput = await self.stt.transcribe(audio_path)
                    except Exception as e:
                        logger.error("Transcription failed: %s", e, exc_info=True)
                logger.info("Transcribed text: %r", userinput)

                if not userinput:
                    logger.info("No user input; skipping processing")
                    await asyncio.sleep(0.5)
                    continue

                # vision processing
                caption = ""
                detection = ""
                ocr_text = ""
                try:
                    caption = await self.vision.caption(frame_path)
                except Exception as e:
                    logger.warning("Captioning failed: %s", e, exc_info=True)
                try:
                    detection = await self.vision.detect_objects(frame_path)
                except Exception as e:
                    logger.warning("Object detection failed: %s", e, exc_info=True)
                try:
                    ocr_text = await self.vision.detect_text(frame_path)
                except Exception as e:
                    logger.warning("OCR failed: %s", e, exc_info=True)

                # prepare prompt
                prompt = self.prepare_prompt(
                    userinput, caption, detection, ocr_text
                )
                logger.info("Generated prompt for LLM: %s", prompt)

                # chat response
                reply = ""
                try:
                    reply = await self.stt.chat(prompt, user_id=self.stt.config.get("user_id", ""))
                except Exception as e:
                    logger.error("Chat request failed: %s", e, exc_info=True)

                # speak reply
                try:
                    reply_audio = await self.stt.synthesize_speech(reply)
                    self.audio.add_audio_to_queue(str(reply_audio))
                except Exception as e:
                    logger.error("Speech synthesis failed: %s", e, exc_info=True)

                # emit event
                try:
                    cmd, params = await self.parser.parse(reply)
                    evt = UserCommand(text=reply, command=cmd, params=params)
                    self.bus.emit(evt)
                except Exception as e:
                    logger.warning("Command parsing or emit failed: %s", e, exc_info=True)

                await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                logger.info("VoiceModule cancelled")
                break
            except Exception as e:
                logger.error("Unexpected error in VoiceModule loop: %s", e, exc_info=True)
                await asyncio.sleep(1)

    def prepare_prompt(
        self,
        userinput: str,
        caption: str,
        objects: Any,
        text: str
    ) -> str:
        """
        Builds a user-role message combining speech and vision context.
        """
        try:
            return (
                f"{userinput}\n\n"
                f"Caption: \"{caption}\"\n"
                f"Detected objects: {objects}\n"
                f"Detected text: {text or 'none'}\n"
                "Using this context, respond clearly and concisely."
            )
        except Exception as e:
            logger.error("prepare_prompt failed: %s", e, exc_info=True)
            return userinput

    def prompt_llm(self, prompt: str):
        # placeholder for synchronous LLM calls
        pass

if __name__ == "__main__":
    # minimal demo
    logging.basicConfig(level=logging.INFO)
    bus = EventBus()
    audio = AudioModule()
    vision = VisionModule(bus)
    stt = STTModule()
    parser = CommandParser()
    vm = VoiceModule(bus, audio, vision, stt, parser)
    vm.start()
    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        vm.stop()
