import httpx

from src.config import settings


LINE_API_BASE_URL = "https://api.line.me"


class LineClient:
    def __init__(self) -> None:
        self._headers = {
            "Authorization": f"Bearer {settings.line_channel_access_token}",
            "Content-Type": "application/json",
        }

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


line_client = LineClient()
