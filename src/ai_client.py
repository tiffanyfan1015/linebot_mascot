from google import genai

from src.config import settings


class GeminiAIClient:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key) if settings.gemini_api_key else None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def generate_reply(self, prompt: str) -> str:
        if not self._client:
            raise RuntimeError("Gemini API key is not configured")

        response = self._client.models.generate_content(
            model=settings.gemini_model,
            contents=(
                "You are a helpful assistant in a LINE group chat. "
                "Reply in concise Traditional Chinese. "
                "If the user asks for something unsafe or illegal, refuse briefly.\n\n"
                f"User message: {prompt}"
            ),
        )
        return (response.text or "").strip()


gemini_ai_client = GeminiAIClient()