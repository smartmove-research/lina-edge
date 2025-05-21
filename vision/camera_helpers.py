import cv2
import logging
from config import Config

# Function to get the camera object
def get_camera(retries=3):
    try:
        config = Config.get_config()
        # Validate the configuration
        validate_config(config)
        # Log the loaded configuration
        logging.info("Loaded configuration: %s", config)
        # Check if the camera is enabled in the config
        if config.get('camera', {}).get('enabled', False):
            # Get the camera URL from the config
            camera_url = config['camera'].get('url')
            logging.info("Initializing camera with URL: %s", camera_url)
            if not camera_url:
                logging.error("Camera URL is missing in the configuration.")
                raise ValueError("Camera URL is missing in the configuration.")
            for attempt in range(retries):
                logging.info(f"Attempting to connect to camera (attempt {attempt + 1})...")
                # Attempt to open the camera
                camera = cv2.VideoCapture(camera_url)
                if camera.isOpened():
                    logging.info("Camera opened successfully.")
                    return camera
                else:
                    logging.warning(f"Failed to open camera at {camera_url}. Retrying...")
            logging.error(f"All {retries} attempts to connect to camera at {camera_url} failed.")
            return None
        else:
            logging.error("Camera is not enabled in the configuration.")
            raise ValueError("Camera is not enabled in the configuration.")
    except FileNotFoundError:
        logging.error("Configuration file not found.")
        raise RuntimeError("Configuration file not found.")
    except KeyError as e:
        logging.error(f"Missing configuration key: {e}")
        raise RuntimeError(f"Missing configuration key: {e}")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        raise RuntimeError(f"Unexpected error: {e}")

def validate_config(config):
    if 'camera' not in config:
        raise RuntimeError("Missing 'camera' section in configuration.")
    if 'enabled' not in config['camera']:
        raise RuntimeError("Missing 'enabled' key in camera configuration.")
    if 'url' not in config['camera']:
        raise RuntimeError("Missing 'url' key in camera configuration.")