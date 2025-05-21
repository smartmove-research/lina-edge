# events/events.py
from dataclasses import dataclass
from core.event_bus import Event
from typing import Any, Dict

@dataclass
class VoiceCommand(Event):
    text: str
    frame: bytes

@dataclass
class InterestingFrame(Event):
    frame: any       # e.g. OpenCV image
    metadata: dict

@dataclass
class ObstacleDetected(Event):
    distance: float

@dataclass
class ObjectDetected(Event):
    objects: list[str]

@dataclass
class OCRResult(Event):
    text: str

@dataclass
class ImageCaption(Event):
    caption: str

@dataclass
class UserCommand(Event):
    text: str               # full transcribed text
    command: str            # parsed command name (e.g. "describe", "navigate")
    params: Dict[str,Any]   # extracted parameters
    frame: Any              # vision frame at the time of the command

# …add more as needed (BatteryLow, WakeWordDetected, etc.)…
