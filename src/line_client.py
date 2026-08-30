import asyncio
import logging
import random
import uuid

import httpx

from src.config import settings


LINE_API_BASE_URL = "https://api.line.me"
LINE_API_DATA_BASE_URL = "https://api-data.line.me"
logger = logging.getLogger(__name__)


class LineClient:
    def __init__(self) -> None:
        self._headers = {
            "Authorization": f"Bearer {settings.line_channel_access_token}",
            "Content-Type": "application/json",
        }
        self._bot_info_cache: dict | None = None

    async def reply_text(self, reply_token: str, text: str) -> None:
        await self.reply_messages(reply_token, [{"type": "text", "text": text}])

    async def reply_messages(self, reply_token: str, messages: list[dict]) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{LINE_API_BASE_URL}/v2/bot/message/reply",
                headers=self._headers,
                json={"replyToken": reply_token, "messages": messages},
            )
            response.raise_for_status()

    async def push_text(self, to: str, text: str) -> None:
        # A 429 can be a short-lived token-bucket limit. Keep retries bounded;
        # a monthly/target quota 429 will not be fixed by retrying forever.
        retry_key = uuid.uuid4().hex
        async with httpx.AsyncClient(timeout=10) as client:
            for attempt in range(4):
                request_headers = {**self._headers, "X-Line-Retry-Key": retry_key}
                response = await client.post(
                    f"{LINE_API_BASE_URL}/v2/bot/message/push",
                    headers=request_headers,
                    json={
                        "to": to,
                        "messages": [{"type": "text", "text": text}],
                    },
                )
                if response.status_code != 429 or attempt == 3:
                    if response.is_error:
                        logger.error(
                            "LINE push failed: to=%s status=%s body=%s",
                            to,
                            response.status_code,
                            response.text[:500],
                        )
                    response.raise_for_status()
                    return

                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else 2**attempt
                except ValueError:
                    delay = 2**attempt
                delay = min(max(delay, 0.5) + random.uniform(0, 0.5), 30)
                logger.warning(
                    "LINE push rate-limited: to=%s attempt=%s/4 retry_in=%.1fs body=%s",
                    to,
                    attempt + 1,
                    delay,
                    response.text[:500],
                )
                await asyncio.sleep(delay)

    async def get_message_content(self, message_id: str) -> tuple[bytes, str | None]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{LINE_API_DATA_BASE_URL}/v2/bot/message/{message_id}/content",
                headers=self._headers,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError:
                logger.exception(
                    "Failed to fetch LINE message content: message_id=%s status=%s body=%s",
                    message_id,
                    response.status_code,
                    response.text,
                )
                raise
            return response.content, response.headers.get("content-type")

    async def get_external_content(self, url: str) -> tuple[bytes, str | None]:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(url)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError:
                logger.exception(
                    "Failed to fetch external image content: url=%s status=%s body=%s",
                    url,
                    response.status_code,
                    response.text[:500],
                )
                raise
            return response.content, response.headers.get("content-type")

    async def get_user_profile(self, user_id: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{LINE_API_BASE_URL}/v2/bot/profile/{user_id}",
                headers=self._headers,
            )
            response.raise_for_status()
            return response.json()

    async def get_group_member_profile(self, group_id: str, user_id: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{LINE_API_BASE_URL}/v2/bot/group/{group_id}/member/{user_id}",
                headers=self._headers,
            )
            response.raise_for_status()
            return response.json()

    async def get_room_member_profile(self, room_id: str, user_id: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{LINE_API_BASE_URL}/v2/bot/room/{room_id}/member/{user_id}",
                headers=self._headers,
            )
            response.raise_for_status()
            return response.json()

    async def get_bot_info(self) -> dict:
        if self._bot_info_cache is not None:
            return self._bot_info_cache

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{LINE_API_BASE_URL}/v2/bot/info",
                headers=self._headers,
            )
            response.raise_for_status()
            self._bot_info_cache = response.json()
            return self._bot_info_cache

    async def get_bot_user_id(self) -> str | None:
        if settings.line_bot_user_id:
            return settings.line_bot_user_id

        bot_info = await self.get_bot_info()
        return bot_info.get("userId")


line_client = LineClient()
