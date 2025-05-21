import os
import httpx
import asyncio
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

from config import Config

config = Config.get_config()

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

async def detect_text(frame_path: str) -> str:
    NO_TEXT_OR_FAILED = ""
    # Placeholder: implement OCR-based detection
    url = config["host"]["url"].rstrip("/") + config["ocr"]["endpoint"]
    print("url:", url)
    #return
    response = await ocr_image(frame_path, url)

    text = response.get("text", NO_TEXT_OR_FAILED)
    return text

async def test(N=3):
    import time
    times = list()
    for i in range(N):
        im_path = "test\ocr_test.png"
        start = time.time()
        text = await detect_text(im_path)
        times.append(time.time()-start)
        print(i, text)
        logger.info(f"[{i}] Captured text: {text}")
    print("AVG", sum(times)/len(times))
    print(times)
        
        

if __name__ == "__main__":
    asyncio.run(test(13))