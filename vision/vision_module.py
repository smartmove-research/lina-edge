# vision/vision_module.py

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

class VisionModule:
    def __init__(
        self,
        bus: EventBus,
        max_queue: int = 10,
        scene_threshold: float = 0.7,
        config: dict = config,
    ):
        """
        :param bus:             shared EventBus
        :param max_queue:       max asyncio queue size for frames
        :param scene_threshold: Bhattacharyya distance above which
                                 we consider the scene “changed”
        """
        self.bus = bus
        self._frame_queue = asyncio.Queue(maxsize=max_queue)
        self._running = False
        self._capture_thread = None
        self.config = config
        self._latest_frame = None

        # For scene change detection
        self._prev_hist: Optional[np.ndarray] = None
        self.scene_threshold = scene_threshold

    @property
    def latest_frame(self) -> Optional[Any]:
        return self._latest_frame

    def start(self) -> None:
        if self._running:
            return
        Camera().start()
        self._running = True

        self._capture_thread = threading.Thread(
            target=self._capture_loop, daemon=True
        )
        self._capture_thread.start()
        logger.info("Camera capture thread started")

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
                logger.error(f"Camera read error: {e}")
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
            frame = await self._frame_queue.get()

            if self._detect_scene_change(frame):
                logger.info("Scene change detected → emitting scene event")
                self.bus.emit(InterestingFrame(frame=frame, metadata={"type": "scene"}))

            if self._detect_text(frame):
                logger.debug("Text detected → emitting text event")
                self.bus.emit(InterestingFrame(frame=frame, metadata={"type": "text"}))

            elif (dist := self._detect_obstacle(frame)) is not None:
                logger.debug(f"Obstacle at {dist:.2f} m → emitting obstacle event")
                self.bus.emit(ObstacleDetected(distance=dist))

            self._frame_queue.task_done()

    def _detect_scene_change(self, frame: Any) -> bool:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
        cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)

        if self._prev_hist is None:
            self._prev_hist = hist
            return False

        dist = cv2.compareHist(self._prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA)
        logger.debug(f"Scene hist distance: {dist:.3f}")

        changed = dist > self.scene_threshold
        if changed:
            self._prev_hist = hist
        return changed

    def _detect_text(self, frame: Any) -> bool:
        return False

    def _detect_obstacle(self, frame: Any) -> Optional[float]:
        return None

    async def detect_objects(self, image_path: str) -> str:
        logger.info(f"Detecting objects… {image_path}")
        filename = os.path.basename(image_path)
        url = self.config["host"]["url"].rstrip("/") + self.config["detect"]["endpoint"]
        logger.info(f"Detect URL: {url}")

        if self.config.get("dev_offline", False):
            detections = [
                {"class_name": "person"},
                {"class_name": "car"},
            ]
        else:
            async with httpx.AsyncClient() as client:
                with open(image_path, "rb") as f:
                    files = {"file": (filename, f, "application/octet-stream")}
                    resp = await client.post(url, files=files)
            if resp.status_code != 200:
                logger.error("Detection failed %s %s", resp.status_code, resp.text)
                return "Had difficulties identifying objects"
            detections = resp.json().get("detections", []) 

        return ", ".join(obj["class_name"] for obj in detections)

    async def caption(self, image_path: str) -> str:
        logger.info(f"Captioning… {image_path}")
        filename = os.path.basename(image_path)
        url = self.config["host"]["url"].rstrip("/") + self.config["caption"]["endpoint"]
        logger.info(f"Caption URL: {url}")

        headers = {"accept": "application/json"}
        timeout = httpx.Timeout(50.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            with open(image_path, "rb") as f:
                files = {"file": (filename, f, "image/jpeg")}  # match curl
                resp = await client.post(url, files=files, headers=headers)
        logger.info("Got caption...")
        if resp.status_code == 200:
            return resp.json().get("caption", "")
        logger.error("Caption failed %s %s", resp.status_code, resp.text)
        return ""

    def save_frame(self, frame: Any) -> str:
        frame_path = os.path.join("tmp", f"{uuid.uuid4().hex}.jpg")
        cv2.imwrite(frame_path, frame)
        logger.info("Done writing image to: %s", frame_path)
        return frame_path
