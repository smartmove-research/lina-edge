import threading
import asyncio
import time
import logging
from typing import Any, Optional
import uuid
import os

import cv2
import numpy as np
import httpx

from vision.camera import Camera
from core.event_bus import EventBus
from events.events import InterestingFrame, ObstacleDetected
from config import Config

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

config = Config.get_config()

def list_to_freq_dict(lst):
    freq_dict = {}
    for item in lst:
        freq_dict[item] = freq_dict.get(item, 0) + 1
    return freq_dict

class VisionModule:
    def __init__(
        self,
        bus: EventBus,
        max_queue: int = 10,
        scene_threshold: float = 0.7,
        http_timeout: float = 10.0,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
        config: dict = config,
    ):
        """
        :param bus:             shared EventBus
        :param max_queue:       max asyncio queue size for frames
        :param scene_threshold: Bhattacharyya distance above which
                                 we consider the scene "changed"
        :param http_timeout:    seconds timeout for HTTP calls
        :param max_retries:     number of retries for HTTP calls
        :param backoff_factor:  initial backoff delay in seconds
        """
        self.bus = bus
        self._frame_queue = asyncio.Queue(maxsize=max_queue)
        self._running = False
        self._capture_thread: threading.Thread = None
        self.config = config
        self._latest_frame = None

        # Scene change detection
        self._prev_hist: Optional[np.ndarray] = None
        self.scene_threshold = scene_threshold

        # HTTP retry settings
        self.http_timeout = http_timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    @property
    def latest_frame(self):
        return self._latest_frame

    def start(self) -> None:
        if self._running:
            return

        Camera().start()
        self._running = True

        # start capture in background thread
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            daemon=True
        )
        self._capture_thread.start()
        logger.info("Camera capture thread started")

        # start processing loop in event loop
        asyncio.create_task(self._process_loop())
        logger.info("Vision async processor started")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        Camera().stop()
        logger.info("VisionModule stopped")

    def _capture_loop(self) -> None:
        while self._running:
            try:
                frame = Camera().get_frame()
            except Exception as e:
                logger.error("Camera read error: %s", e, exc_info=True)
                break

            if frame is not None:
                self._latest_frame = frame
                try:
                    self._frame_queue.put_nowait(frame)
                except asyncio.QueueFull:
                    logger.debug("Frame queue full; dropping frame")

            time.sleep(0.01)

    async def _process_loop(self) -> None:
        while self._running:
            try:
                frame = await asyncio.wait_for(self._frame_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            try:
                if self._detect_scene_change(frame):
                    logger.info("Scene change detected -> emitting event")
                    self.bus.emit(InterestingFrame(frame=frame, metadata={"type": "scene"}))

                if self.detect_text(frame):
                    logger.debug("Text detected -> emitting text event")
                    self.bus.emit(InterestingFrame(frame=frame, metadata={"type": "text"}))
                else:
                    dist = self._detect_obstacle(frame)
                    if dist is not None:
                        logger.debug("Obstacle at %.2f m -> emitting obstacle event", dist)
                        self.bus.emit(ObstacleDetected(distance=dist))

            except Exception as e:
                logger.error("Error in processing loop: %s", e, exc_info=True)
            finally:
                self._frame_queue.task_done()

    def _detect_scene_change(self, frame: Any) -> bool:
        try:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
            cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)

            if self._prev_hist is None:
                self._prev_hist = hist
                return False

            dist = cv2.compareHist(self._prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA)
            logger.debug("Scene hist distance: %.3f", dist)

            if dist > self.scene_threshold:
                self._prev_hist = hist
                return True
        except Exception as e:
            logger.error("Error in scene detection: %s", e, exc_info=True)
        return False
    
    def _detect_text(self, frame_path: str) -> str:
        return self.detect_text(frame_path)

    def detect_text(self, frame_path: str) -> str:
        NO_TEXT_OR_FAILED = ""
        # Placeholder: implement OCR-based detection
        url = self.config["host"]["url"].rstrip("/") + self.config["ocr"]["endpoint"]
        response = ocr_image(frame_path, url)
        
        text = response.get("text", NO_TEXT_OR_FAILED)
        return text

    def _detect_obstacle(self, frame: Any) -> Optional[float]:
        # Placeholder: implement depth/distance measurement
        return None

    async def _post_with_retries(self, url: str, **kwargs) -> httpx.Response:
        delay = self.backoff_factor
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.http_timeout) as client:
                    resp = await client.post(url, **kwargs)
                    resp.raise_for_status()
                    return resp
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
                logger.warning("HTTP request failed (attempt %d/%d) to %s: %s",
                               attempt, self.max_retries, url, e)
                if attempt == self.max_retries:
                    logger.error("Max HTTP retries reached for %s", url)
                    raise
                await asyncio.sleep(delay)
                delay *= 2
            except httpx.HTTPStatusError as e:
                logger.error("HTTP status error %d for %s: %s",
                             e.response.status_code, url, e, exc_info=True)
                raise

    async def detect_objects(self, image_path: str) -> str:
        logger.info("Detecting objects: %s", image_path)
        filename = os.path.basename(image_path)
        url = self.config["host"]["url"].rstrip("/") + self.config["detect"]["endpoint"]
        logger.debug("Detect URL: %s", url)

        if self.config.get("dev_offline", False):
            detections = [ {"class_name": "person"}, {"class_name": "car"} ]
        else:
            try:
                with open(image_path, "rb") as f:
                    files = {"file": (filename, f, "application/octet-stream")}
                    resp = await self._post_with_retries(url, files=files)
                detections = resp.json().get("detections", [])
            except Exception as e:
                logger.error("Detection failed: %s", e, exc_info=True)
                return "Detection error"
        occurences = list_to_freq_dict([obj.get("class_name", "") for obj in detections])
        return ", ".join(f"{v} {k}{'s' if v>1 else ''}" for k, v in occurences.items())

    async def caption(self, image_path: str) -> str:
        logger.info("Captioning: %s", image_path)
        filename = os.path.basename(image_path)
        url = self.config["host"]["url"].rstrip("/") + self.config["caption"]["endpoint"]
        logger.debug("Caption URL: %s", url)

        headers = {"Accept": "application/json"}
        try:
            with open(image_path, "rb") as f:
                files = {"file": (filename, f, "image/jpeg")}
                resp = await self._post_with_retries(url, files=files, headers=headers)
            return resp.json().get("caption", "")
        except Exception as e:
            logger.error("Caption failed: %s", e, exc_info=True)
            return ""

    def save_frame(self, frame: Any) -> str:
        try:
            frame_dir = "tmp"
            os.makedirs(frame_dir, exist_ok=True)
            frame_path = os.path.join(frame_dir, f"{uuid.uuid4().hex}.jpg")
            cv2.imwrite(frame_path, frame)
            logger.info("Frame saved to: %s", frame_path)
            return frame_path
        except Exception as e:
            logger.error("Failed to save frame: %s", e, exc_info=True)
            return ""

# OCR helper function
async def ocr_image(
    image_path: str,
    url: str = "http://127.0.0.1:8866/ocr/",
    timeout: float = 10.0,
    max_retries: int = 3,
    backoff_factor: float = 1.0
) -> dict:
    """
    Send an image to the OCR service and return the JSON response.
    Implements manual retry/back-off on network errors.
    """
    filename = os.path.basename(image_path)
    headers = {"accept": "application/json"}
    delay = backoff_factor

    for attempt in range(1, max_retries + 1):
        try:
            with open(image_path, "rb") as f:
                files = {"image": (filename, f, "image/png")}
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(url, headers=headers, files=files)
                    resp.raise_for_status()
                    return resp.json()
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
            logger.warning(
                "OCR request failed (attempt %d/%d) to %s: %s",
                attempt, max_retries, url, e
            )
            if attempt == max_retries:
                logger.error("Max OCR retries reached for %s", url)
                return {}
            await asyncio.sleep(delay)
            delay *= 2
        except httpx.HTTPStatusError as e:
            logger.error(
                "OCR service returned HTTP %d: %s",
                e.response.status_code, e
            )
            return {}

if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)
    bus = EventBus()
    vision = VisionModule(bus)
    vision.start()
    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        vision.stop()
