# vision/cloud_handler.py

import asyncio
import logging
import time
from typing import Optional

from core.event_bus import EventBus
from events.events import (
    InterestingFrame,      # from vision_module
    ObjectDetected, OCRResult, ImageCaption
)
from vision.cloud_client import CloudVisionClient

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class SmartCloudVisionHandler:
    def __init__(
        self,
        bus: EventBus,
        base_url: str,
        caption_interval: float = 5.0,
        ocr_interval: float     = 2.0,
        object_interval: float  = 1.0,
    ):
        """
        :param bus:             your central event bus
        :param base_url:        URL of your Flask vision API
        :param caption_interval: min seconds between caption calls
        :param ocr_interval:     min seconds between OCR calls
        :param object_interval:  min seconds between object-detection calls
        """
        self.bus              = bus
        self.client           = CloudVisionClient(base_url)
        self.caption_interval = caption_interval
        self.ocr_interval     = ocr_interval
        self.object_interval  = object_interval

        # last time we called each endpoint
        self._last_caption:   float = 0.0
        self._last_ocr:       float = 0.0
        self._last_object:    float = 0.0

        # caches to avoid repeating identical results
        self._last_caption_text: Optional[str] = None
        self._last_ocr_text:     Optional[str] = None
        self._last_objects:      Optional[tuple] = None

        # we only need a single subscription
        self.bus.subscribe(InterestingFrame, self._on_interesting_frame)

    def stop(self):
        """If you ever need to cleanup the client session."""
        asyncio.create_task(self.client.close())

    def _should_run(self, last_run: float, interval: float) -> bool:
        return (time.time() - last_run) >= interval

    def _update_time(self, attr: str):
        setattr(self, attr, time.time())

    async def _on_interesting_frame(self, ev: InterestingFrame):
        """
        Called whenever VisionModule emits an InterestingFrame.
        metadata['type'] should be one of: 'text', 'object', 'scene'
        """
        mtype = ev.metadata.get('type')

        # ── OCR path ─────────────────────────────────────────────
        if mtype == 'text' and self._should_run(self._last_ocr, self.ocr_interval):
            logger.debug("Triggering OCR on cloud")
            try:
                txt = await self.client.ocr(ev.frame)
                if txt and txt != self._last_ocr_text:
                    self._last_ocr_text = txt
                    self._update_time('_last_ocr')
                    self.bus.emit(OCRResult(text=txt))
                    logger.info(f"OCRResult emitted: {txt!r}")
            except Exception as e:
                logger.warning(f"OCR error: {e}")

        # ── Object Detection path ──────────────────────────────
        elif mtype == 'object' and self._should_run(self._last_object, self.object_interval):
            logger.debug("Triggering object detection on cloud")
            try:
                objs = await self.client.detect_objects(ev.frame)
                objs_tuple = tuple(sorted(objs))
                if objs_tuple and objs_tuple != self._last_objects:
                    self._last_objects = objs_tuple
                    self._update_time('_last_object')
                    self.bus.emit(ObjectDetected(objects=list(objs_tuple)))
                    logger.info(f"ObjectDetected emitted: {objs_tuple}")
            except Exception as e:
                logger.warning(f"Object detection error: {e}")

        # ── Caption path ────────────────────────────────────────
        elif mtype == 'scene' and self._should_run(self._last_caption, self.caption_interval):
            logger.debug("Triggering image caption on cloud")
            try:
                cap = await self.client.caption(ev.frame)
                if cap and cap != self._last_caption_text:
                    self._last_caption_text = cap
                    self._update_time('_last_caption')
                    self.bus.emit(ImageCaption(caption=cap))
                    logger.info(f"ImageCaption emitted: {cap!r}")
            except Exception as e:
                logger.warning(f"Caption error: {e}")

        else:
            logger.debug(f"No cloud call for metadata type={mtype}")
