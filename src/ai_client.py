import base64
import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from google import genai
from google.genai.errors import ClientError

from src.config import settings


logger = logging.getLogger(__name__)


class AIServiceError(Exception):
    pass


@dataclass
class NutritionEstimate:
    serving_description: str | None = None
    calories_kcal: int | None = None
    protein_g: float | None = None
    carbohydrates_g: float | None = None
    fat_g: float | None = None
    fiber_g: float | None = None

    def as_dict(self) -> dict[str, str | int | float | None]:
        return {
            "serving_description": self.serving_description,
            "calories_kcal": self.calories_kcal,
            "protein_g": self.protein_g,
            "carbohydrates_g": self.carbohydrates_g,
            "fat_g": self.fat_g,
            "fiber_g": self.fiber_g,
        }


@dataclass
class ImageAnalysis:
    is_food: bool
    description: str
    nutrition: NutritionEstimate | None = None


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

    def generate_daily_titles(self, profiles: list[dict[str, Any]]) -> dict[str, str]:
        if not self._client or not profiles:
            return {}

        participant_ids = {profile.get("participant_id") for profile in profiles if isinstance(profile.get("participant_id"), str)}
        if not participant_ids:
            return {}

        prompt = (
            "You create one playful, varied Traditional Chinese daily meal title for each anonymous LINE group participant. "
            "Base every title only on the supplied meal records, food names, meal timing, and estimated nutrition totals. "
            "Treat food diversity as variety of dishes, ingredients, and meal types, not merely the number of log entries. "
            "Use warm, non-judgmental titles such as 食材探索家, 早餐活力王, 宵夜戰士, or 餐盤藝術家. "
            "Do not make medical, body-weight, morality, or health claims. Do not use participant names. "
            "Give every participant a different title when their records support it. Each title must be 2 to 12 Traditional Chinese characters, with no emoji or explanation. "
            "Return JSON only: {\"titles\":[{\"participant_id\":string,\"title\":string}]}.\n\n"
            f"Participants: {json.dumps(profiles, ensure_ascii=False, separators=(',', ':'))}"
        )
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 1.2,
                "responseMimeType": "application/json",
            },
        }

        try:
            response = httpx.post(url, json=payload, timeout=30)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AIServiceError("Gemini daily title request failed") from exc

        titles = parse_daily_titles(extract_gemini_text(response.json()), participant_ids)
        logger.info("Gemini generated %s daily titles", len(titles))
        return titles

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
                                '{"is_food": boolean, "description": string, "nutrition": '
                                '{"serving_description": string, "calories_kcal": number, '
                                '"protein_g": number, "carbohydrates_g": number, "fat_g": number, '
                                '"fiber_g": number} | null}. '
                                "Set is_food to true only if the image clearly shows food, a meal, or something meant to be eaten. "
                                "Write description as a short Traditional Chinese name of the food for food images, "
                                "or a short noun phrase describing the main non-food subject otherwise. "
                                "For food, estimate the visible portion's total nutrition, not per 100 grams. "
                                "Use reasonable whole-number calorie estimates and one decimal place at most for grams. "
                                "Set nutrition to null if the food or portion cannot be estimated from the image. "
                                "Do not make medical, dietary, or health claims. If the subject is unclear, use \"不太清楚內容\"."
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
            "Gemini image analysis result: raw=%s is_food=%s description=%s nutrition=%s",
            text,
            analysis.is_food,
            analysis.description,
            analysis.nutrition,
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


def parse_daily_titles(text: str, participant_ids: set[str]) -> dict[str, str]:
    normalized_text = strip_json_fence(text)
    try:
        parsed = json.loads(normalized_text)
    except json.JSONDecodeError:
        return {}

    entries = parsed.get("titles") if isinstance(parsed, dict) else None
    if not isinstance(entries, list):
        return {}

    titles: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        participant_id = entry.get("participant_id")
        title = normalize_daily_title(entry.get("title"))
        if isinstance(participant_id, str) and participant_id in participant_ids and title:
            titles[participant_id] = title
    return titles


def normalize_daily_title(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    title = " ".join(value.split())
    if not 2 <= len(title) <= 12:
        return None
    if any(ord(character) < 0x4E00 or ord(character) > 0x9FFF for character in title):
        return None
    return title


def strip_json_fence(text: str) -> str:
    normalized_text = text.strip()
    if normalized_text.startswith("```"):
        normalized_text = normalized_text.strip("`").strip()
        if normalized_text.lower().startswith("json"):
            normalized_text = normalized_text[4:].strip()
    return normalized_text


def parse_image_analysis(text: str) -> ImageAnalysis:
    if not text:
        return ImageAnalysis(is_food=False, description="不太清楚內容")

    normalized_text = strip_json_fence(text)

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
        nutrition=parse_nutrition_estimate(parsed.get("nutrition")) if parsed.get("is_food") is True else None,
    )


def parse_nutrition_estimate(value: Any) -> NutritionEstimate | None:
    if not isinstance(value, dict):
        return None

    serving_description = value.get("serving_description")
    if not isinstance(serving_description, str) or not serving_description.strip():
        serving_description = None

    calories_kcal = parse_number(value.get("calories_kcal"), integer=True)
    protein_g = parse_number(value.get("protein_g"))
    carbohydrates_g = parse_number(value.get("carbohydrates_g"))
    fat_g = parse_number(value.get("fat_g"))
    fiber_g = parse_number(value.get("fiber_g"))
    if all(item is None for item in (calories_kcal, protein_g, carbohydrates_g, fat_g, fiber_g)):
        return None

    return NutritionEstimate(
        serving_description=serving_description.strip() if serving_description else None,
        calories_kcal=calories_kcal,
        protein_g=protein_g,
        carbohydrates_g=carbohydrates_g,
        fat_g=fat_g,
        fiber_g=fiber_g,
    )


def parse_number(value: Any, *, integer: bool = False) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0:
        return None
    return int(round(value)) if integer else round(float(value), 1)


gemini_ai_client = GeminiAIClient()
