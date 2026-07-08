import base64
import json
import logging

import httpx
from google import genai
from google.genai.errors import ClientError

from src.config import settings


logger = logging.getLogger(__name__)


class AIServiceError(Exception):
    pass


class ImageAnalysis:
    def __init__(self, is_food: bool, description: str) -> None:
        self.is_food = is_food
        self.description = description


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
        return self.analyze_image(image_bytes, mime_type).is_food

    def analyze_image(self, image_bytes: bytes, mime_type: str | None) -> ImageAnalysis:
        if not settings.gemini_api_key:
            return ImageAnalysis(is_food=False, description="照片")

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
                                "Analyze this image for a LINE group chat bot. "
                                "Return compact JSON only with this schema: "
                                '{"is_food": boolean, "description": string}. '
                                "Set is_food to true only if the image clearly shows food, a meal, or something meant to be eaten. "
                                "Write description as a short Traditional Chinese noun phrase describing the main non-food subject. "
                                "If the subject is unclear, use \"不太清楚內容\"."
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
            raise AIServiceError("Gemini image classification request failed") from exc

        data = response.json()
        text = extract_gemini_text(data).strip()
        analysis = parse_image_analysis(text)
        logger.info(
            "Gemini image analysis result: raw=%s is_food=%s description=%s",
            text,
            analysis.is_food,
            analysis.description,
        )
        return analysis


def extract_gemini_text(response_json: dict) -> str:
    candidates = response_json.get("candidates") or []
    if not candidates:
        return ""

    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
    return "\n".join(texts)


def parse_image_analysis(text: str) -> ImageAnalysis:
    if not text:
        return ImageAnalysis(is_food=False, description="不太清楚內容")

    normalized_text = text.strip()
    if normalized_text.startswith("```"):
        normalized_text = normalized_text.strip("`").strip()
        if normalized_text.lower().startswith("json"):
            normalized_text = normalized_text[4:].strip()

    try:
        parsed = json.loads(normalized_text)
    except json.JSONDecodeError:
        upper_text = normalized_text.upper()
        return ImageAnalysis(
            is_food=upper_text.startswith("YES"),
            description="不太清楚內容",
        )

    description = parsed.get("description")
    if not isinstance(description, str) or not description.strip():
        description = "不太清楚內容"

    return ImageAnalysis(
        is_food=parsed.get("is_food") is True,
        description=description.strip(),
    )


gemini_ai_client = GeminiAIClient()
