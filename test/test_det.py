import os
import httpx
import asyncio
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

from config import Config

config = Config.get_config()

class Template:
    pass

self = Template()

self.backoff_factor, self.http_timeout, self.max_retries = 1., 10, 3

def list_to_freq_dict(lst):
    freq_dict = {}
    for item in lst:
        freq_dict[item] = freq_dict.get(item, 0) + 1
    return freq_dict


async def _post_with_retries(url: str, **kwargs) -> httpx.Response:
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

async def detect_objects(image_path: str) -> str:
    logger.info("Detecting objects: %s", image_path)
    filename = os.path.basename(image_path)
    url = config["host"]["url"].rstrip("/") + config["detect"]["endpoint"]
    logger.debug("Detect URL: %s", url)

    if config.get("dev_offline", False):
        detections = [ {"class_name": "person"}, {"class_name": "car"} ]
    else:
        try:
            with open(image_path, "rb") as f:
                files = {"file": (filename, f, "application/octet-stream")}
                resp = await _post_with_retries(url, files=files)
            detections = resp.json().get("detections", [])
        except Exception as e:
            logger.error("Detection failed: %s", e, exc_info=True)
            return "Detection error"
    occurences = list_to_freq_dict([obj.get("class_name", "") for obj in detections])
    return ", ".join(f"{v} {k}{'s' if v>1 else ''}" for k, v in occurences.items())


async def test(N=3):
    import time
    times = list()
    for i in range(N):
        im_path = "test/cameroun_road.jpeg"
        start = time.time()
        detection = await detect_objects(im_path)
        times.append(time.time()-start)
        print(i, detection)
    print("AVG", sum(times)/len(times))
    print(times)

if __name__ == "__main__":
    asyncio.run(test(10))