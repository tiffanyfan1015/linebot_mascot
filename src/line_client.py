import logging

import httpx

from src.config import settings


LINE_API_BASE_URL = "https://api.line.me"
logger = logging.getLogger(__name__)


class LineClient:
    def __init__(self) -> None:
        self._headers = {
            "Authorization": f"Bearer {settings.line_channel_access_token}",
            "Content-Type": "application/json",
        }
        self._bot_info_cache: dict | None = None

    async def reply_text(self, reply_token: str, text: str) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{LINE_API_BASE_URL}/v2/bot/message/reply",
                headers=self._headers,
                json={
                    "replyToken": reply_token,
                    "messages": [{"type": "text", "text": text}],
                },
            )
            response.raise_for_status()

    async def get_message_content(self, message_id: str) -> tuple[bytes, str | None]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{LINE_API_BASE_URL}/v2/bot/message/{message_id}/content",
                headers=self._headers,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError:
                logger.exception(
                    "Failed to fetch LINE message content",
                    extra={
                        "line_message_id": message_id,
                        "status_code": response.status_code,
                        "response_text": response.text,
                    },
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