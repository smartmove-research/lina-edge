# camera.py

import threading
import logging
from vision.camera_helpers import get_camera

logging.basicConfig(level=logging.DEBUG)

class Camera:
    _instance      = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                # mark it un-initialized so __init__ will run exactly once
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        # only run real init once
        if self._initialized:
            return

        self.camera     = None
        self.is_running = False
        self._initialized = True

    def start(self):
        if not self.is_running:
            logging.info("Starting camera...")
            self.camera = get_camera()
            if not self.camera or not self.camera.isOpened():
                logging.error("Failed to start the camera.")
                raise RuntimeError("Failed to start the camera.")
            self.is_running = True
            logging.info("Camera started successfully.")
        return self.is_running

    def stop(self):
        if self.camera:
            logging.info("Stopping camera...")
            self.camera.release()
            self.camera = None
            self.is_running = False
            logging.info("Camera stopped successfully.")
        return self.is_running

    def get_frame(self):
        if not self.is_running:
            logging.error("Camera is not running. Please start the camera first.")
            raise RuntimeError("Camera is not running. Please start the camera first.")
        ret, frame = self.camera.read()
        if not ret:
            logging.warning("Failed to read frame from camera.")
            return None
        return frame
