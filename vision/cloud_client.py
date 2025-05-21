# vision/cloud_client.py

import aiohttp, cv2
from typing import List

class CloudVisionClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.session = aiohttp.ClientSession()

    async def close(self):
        await self.session.close()

    async def _post_image(self, path: str) -> dict:
        """Helper to POST a JPEG frame to /<path> endpoint."""
        return await self._post_bytes(f'{self.base_url}/{path}')

    async def _post_bytes(self, url: str) -> dict:
        headers = {'Content-Type': 'application/octet-stream'}
        # assume caller has JPEG‐encoded bytes ready
        async with self.session.post(url, data=self._last_img_bytes, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _encode(self, frame) -> bytes:
        _, buf = cv2.imencode('.jpg', frame)
        self._last_img_bytes = buf.tobytes()
        return self._last_img_bytes

    async def detect_objects(self, frame) -> List[str]:
        await self._encode(frame)
        data = await self._post_bytes(f'{self.base_url}/detect_objects')
        return data.get('objects', [])

    async def ocr(self, frame) -> str:
        await self._encode(frame)
        data = await self._post_bytes(f'{self.base_url}/ocr')
        return data.get('text', '').strip()

    async def caption(self, frame) -> str:
        await self._encode(frame)
        data = await self._post_bytes(f'{self.base_url}/caption')
        return data.get('caption', '').strip()
