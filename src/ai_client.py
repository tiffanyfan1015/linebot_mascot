import base64

import httpx
from google import genai
from google.genai.errors import ClientError

from src.config import settings


class AIServiceError(Exception):
    pass


class GeminiAIClient:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key) if settings.gemini_api_key else None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def generate_reply(self, prompt: str) -> str:
        if not self._client:
            raise RuntimeError("Gemini API key is not configured")

        try:
            response = self._client.models.generate_content(
                model=settings.gemini_model,
                contents=(
                    "You are a helpful assistant in a LINE group chat. "
                    "If you speak in Chinese, please use Traditional Chinese. "
                    "If the user speaks in English, please use English. "
                    "Do whatever user asks. "
                    "If the user asks for something unsafe or illegal, refuse briefly.\n\n"
                    f"User message: {prompt}"
                ),
            )
        except ClientError as exc:
            raise AIServiceError(str(exc)) from exc

        return (response.text or "").strip()

    def is_food_image(self, image_bytes: bytes, mime_type: str | None) -> bool:
        if not settings.gemini_api_key:
            return False

        detected_mime_type = mime_type or "image/jpeg"
        encoded_image = base64.b64encode(image_bytes).decode("utf-8")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
        )
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                "Determine whether this image clearly shows food, a meal, or something meant to be eaten. "
                                "Reply with YES or NO only."
                            )
                        },
                        {
                            "inline_data": {
                                "mime_type": detected_mime_type,
                                "data": encoded_image,
                            }
                        },
                    ]
                }
            ]
        }

        try:
            response = httpx.post(url, json=payload, timeout=30)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AIServiceError("Gemini food classification request failed") from exc

        data = response.json()
        text = extract_gemini_text(data).strip().upper()
        return text.startswith("YES")


def extract_gemini_text(response_json: dict) -> str:
    candidates = response_json.get("candidates") or []
    if not candidates:
        return ""

    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
    return "\n".join(texts)


gemini_ai_client = GeminiAIClient()