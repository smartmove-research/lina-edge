# voice/voice_module.py

import asyncio
from uuid import uuid4
from typing import Any

from core.event_bus import EventBus
from events.events import UserCommand
from audio.audio_module import AudioModule
from vision.vision_module import VisionModule
from voice.stt_module import STTModule
from voice.command_parser import CommandParser
import requests

import logging
import time

from config import Config

class VoiceModule:
    """
    Listens for any speech (via VAD), transcribes it, grabs the current frame,
    parses the intent, and emits a UserCommand event.
    """
    def __init__(self,
                 bus: EventBus,
                 audio: AudioModule,
                 vision: VisionModule,
                 stt: STTModule,
                 parser: CommandParser,
                 silence_duration: float = 2.0,
                 config = Config.get_config()):
        self.bus              = bus
        self.audio            = audio
        self.vision           = vision
        self.stt              = stt
        self.parser           = parser
        self.silence_duration = silence_duration
        self.config           = config
        self._task            = None

    def start(self):
        if self._task is None:
            #self.audio.add_audio_to_queue("sounds/waterdropletechoed.wav")
            self.audio.add_audio_to_queue("sounds/res_part1.wav")
            time.sleep(1)
            self.audio.add_audio_to_queue("sounds/res_part2.wav")
            self._task = asyncio.create_task(self._run())
            print("VoiceModule started")

    def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run(self):
        print("_run")
        try:
            while True:
                # 1) wait for user to speak (non-blocking)
                logging.info("Waiting for record")
                frame = self.vision.latest_frame
                # Save the frame locally
                frame_path = self.vision.save_frame(frame)
                print("im_path", frame_path)
                pid = self.audio.schedule("sounds/waterdropletechoed.wav", priority=0, loop=True)
                audio_path = await self.audio.record(silence_duration=self.silence_duration)
                logging.info(f"Audio path [{audio_path}]")
                #continue
                #audio_path = "/home/userlina/lina/sounds/recording_speech.wav"
                frame = self.vision.latest_frame
                # Save the frame locally
                frame_path = self.vision.save_frame(frame)
                logging.info("Processing record")
                self.audio.stop_sound(pid)
                logging.info(f"Got record: {audio_path}")
                # 2) transcribe
                logging.info("Sending to transcription...")
                print(self.config["dev_offline"])
                if self.config["dev_offline"]:
                    userinput = "Text DEBUG"
                else:
                    logging.info("Trying to get transcription online...")
                    userinput = await self.stt.transcribe(audio_path)
                    #userinput = " Okay, good morning everyone, my name is Kerry, I'm from Admove.  I am working on a new project all the way around the apartment."
                print(f"[VoiceModule] Transcribed: {userinput!r}")
                if len(userinput):
                    # 3) capture current frame
                    
                    # Get captions
                    frame_caption = await self.vision.caption(frame_path)
                    #frame_caption = "A woman lying on a bed"
                    print("Got caption :", frame_caption)
                    # Get detection
                    
                    #frame_detection = await self.vision.detect_objects(frame_path)
                    frame_detection = "Object detection service currently unavailable"
                    print("Got objects :", frame_detection)

                    # prepare prompt
                    prompt = self.prepare_prompt(userinput, frame_caption, frame_detection)
                    logging.info(f"PROMPT: {prompt}")

                    # get chat_response
                    reply = await self.stt.chat(prompt, user_id=self.config["user_id"])
                    #reply = "   I could see a woman lying on a white bed. Is it your wife?"
                    print("Response:", reply)

                    reply_audio_path = await self.stt.synthesize_speech(reply)
                    print(reply_audio_path)
                    self.audio.add_audio_to_queue(reply_audio_path)
                    #command, params = await self.parser.parse(text)
                    #print(f"[VoiceModule] Parsed command={command}, params={params}")

                    # 5) emit the high-level event
                    #evt = UserCommand(text=text, command=command, params=params, frame=frame)
                    #self.bus.emit(evt)

                # small pause before listening again
                print("Looping... in 10s")
                await asyncio.sleep(0.1)
                

        except asyncio.CancelledError as e:
            print("e")
            pass
    
    def prepare_prompt(self, userinput: str, caption: str, objects: list) -> str:
        """
        Builds a user‐role message content for Llama 3.2 by combining user input, image caption, and detected objects.

        Args:
            userinput: The original prompt from the user.
            caption: The generated image caption.
            objects: A list of detected object names.

        Returns:
            A formatted string to be used as the "content" of a user message.
        """
        # Convert objects list to JSON‐style string for clarity
        logging.info("preparing prompt")
        prompt = (
            f"{userinput}\n\n"
            f"Caption: \"{caption}\"\n"
            f"Detected objects: {objects}\n\n"
            "Using the image context above, compose a response referencing the caption and objects where relevant. "
            "Be clear and concise."
        )

        return prompt
    def prompt_llm(self, prompt):
        user_id = config.get("user_id", "test")
        # TODO
        pass
