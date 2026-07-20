import json
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

import httpx

from src.ai_client import AIServiceError, gemini_ai_client
from src.handlers.reply_rules import build_rule_based_reply
from src.liff_auth import (
    LiffConfigurationError,
    build_liff_group_history_url,
    create_group_access_ticket,
)
from src.line_client import line_client
from src.meal_store import meal_store


logger = logging.getLogger(__name__)
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")


async def handle_events(events: list[dict]) -> None:
    for event in events:
        try:
            await handle_event(event)
        except Exception:
            logger.exception("Failed to handle LINE event")


async def handle_event(event: dict) -> None:
    event_type = event.get("type")
    reply_token = event.get("replyToken")
    source = event.get("source", {})

    if event_type == "join" and reply_token:
        save_chat_target_safely(source)
        await line_client.reply_text(reply_token, "大家好，我是 LINE Bot。請傳文字訊息給我測試。")
        return

    if event_type != "message" or not reply_token:
        return

    message = event.get("message", {})
    save_chat_target_safely(source)
    display_name = await resolve_display_name(source)

    if message.get("type") == "image":
        await handle_image_message(reply_token, message, source, display_name)
        return

    if message.get("type") != "text":
        return

    text = message.get("text", "")
    if text.strip() == "/飲食紀錄":
        await handle_group_history_command(reply_token, source)
        return

    rule_reply = build_rule_based_reply(text)

    if rule_reply:
        await line_client.reply_text(reply_token, rule_reply)
        return

    ai_prompt = await extract_ai_prompt(message, text)
    if ai_prompt:
        if not gemini_ai_client.enabled:
            await line_client.reply_text(reply_token, "AI 功能尚未設定完成，請先設定 Gemini API key。")
            return

        try:
            ai_reply = gemini_ai_client.generate_reply(ai_prompt)
        except AIServiceError:
            logger.exception("Gemini API request failed")
            await line_client.reply_text(reply_token, "AI 服務目前暫時異常，請稍後再試。")
            return

        await line_client.reply_text(reply_token, ai_reply or "我現在暫時想不到要怎麼回答。")
        return

    return


async def handle_group_history_command(reply_token: str, source: dict) -> None:
    group_id = source.get("groupId") if source.get("type") == "group" else None
    user_id = source.get("userId")
    if not group_id:
        await line_client.reply_text(reply_token, "請在 LINE 群組內使用 /飲食紀錄。")
        return
    if not user_id:
        await line_client.reply_text(reply_token, "目前無法確認你的 LINE 身分，請稍後再試。")
        return

    try:
        ticket = create_group_access_ticket(group_id, user_id)
        history_url = build_liff_group_history_url(ticket)
    except LiffConfigurationError:
        logger.exception("LIFF group history is not configured")
        await line_client.reply_text(reply_token, "飲食紀錄頁面尚未完成設定，請稍後再試。")
        return

    await line_client.reply_text(
        reply_token,
        f"這是你查看本群組飲食紀錄的專屬連結（15 分鐘內有效）：\n{history_url}",
    )


async def handle_image_message(reply_token: str, message: dict, source: dict, display_name: str) -> None:
    logger.info("Received LINE image message payload=%s", json.dumps(message, ensure_ascii=False))

    if not gemini_ai_client.enabled:
        logger.info("Skipping image food classification because Gemini is not configured")
        return

    try:
        image_bytes, mime_type = await fetch_image_bytes(message)
        image_analysis = gemini_ai_client.analyze_image(image_bytes, mime_type)
    except AIServiceError:
        logger.exception("Gemini image classification failed")
        return
    except httpx.HTTPError:
        logger.exception(
            "Failed to fetch image content in image handler: payload=%s",
            json.dumps(message, ensure_ascii=False),
        )
        return

    if image_analysis.is_food:
        now = datetime.now(TAIPEI_TIMEZONE)
        meal_type = detect_meal_type(now)
        save_meal_log_safely(
            source=source,
            user_id=source.get("userId"),
            display_name=display_name,
            meal_type=meal_type,
            description=image_analysis.description,
            nutrition=image_analysis.nutrition.as_dict() if image_analysis.nutrition else None,
            message=message,
            now=now,
        )
        await line_client.reply_text(
            reply_token,
            build_photo_meal_reply(
                display_name,
                meal_type=meal_type,
                description=image_analysis.description,
                nutrition=image_analysis.nutrition.as_dict() if image_analysis.nutrition else None,
            ),
        )
        return

    await line_client.reply_text(reply_token, build_non_food_photo_reply(display_name, image_analysis.description))


async def fetch_image_bytes(message: dict) -> tuple[bytes, str | None]:
    content_provider = message.get("contentProvider") or {}
    provider_type = content_provider.get("type")
    original_content_url = content_provider.get("originalContentUrl")
    message_id = message.get("id")

    if provider_type == "external" and original_content_url:
        image_bytes, mime_type = await line_client.get_external_content(original_content_url)
        logger.info(
            "Fetched external image content: url=%s mime_type=%s size=%s",
            original_content_url,
            mime_type,
            len(image_bytes),
        )
        return image_bytes, mime_type

    if not message_id:
        raise httpx.HTTPError("LINE image message ID is missing")

    try:
        image_bytes, mime_type = await line_client.get_message_content(message_id)
        logger.info(
            "Fetched LINE image content: message_id=%s mime_type=%s size=%s",
            message_id,
            mime_type,
            len(image_bytes),
        )
        return image_bytes, mime_type
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404 and original_content_url:
            logger.info(
                "LINE content fetch returned 404; falling back to originalContentUrl: message_id=%s url=%s",
                message_id,
                original_content_url,
            )
            return await line_client.get_external_content(original_content_url)
        raise


async def resolve_display_name(source: dict) -> str:
    source_type = source.get("type")
    user_id = source.get("userId")

    if not user_id:
        return "有人"

    try:
        if source_type == "group" and source.get("groupId"):
            profile = await line_client.get_group_member_profile(source["groupId"], user_id)
        elif source_type == "room" and source.get("roomId"):
            profile = await line_client.get_room_member_profile(source["roomId"], user_id)
        else:
            profile = await line_client.get_user_profile(user_id)
    except httpx.HTTPError:
        logger.exception("Failed to resolve LINE display name")
        return "有人"

    return profile.get("displayName", "有人")


def build_non_food_photo_reply(display_name: str, description: str) -> str:
    cleaned_description = description.strip() or "不太清楚內容"
    return f"{display_name} 傳了一張 {cleaned_description} 的照片"


def build_photo_meal_reply(
    display_name: str,
    now: datetime | None = None,
    meal_type: str | None = None,
    description: str | None = None,
    nutrition: dict[str, str | int | float | None] | None = None,
) -> str:
    detected_meal_type = meal_type or detect_meal_type(now or datetime.now(TAIPEI_TIMEZONE))
    lines = [f"{display_name} 吃{format_meal_type_zh(detected_meal_type)}了"]
    if description and description.strip():
        lines.append(f"食物： {description.strip()}")
    nutrition_text = format_nutrition_estimate(nutrition)
    if nutrition_text:
        lines.append(f"營養估算（照片判讀，僅供參考）\n{nutrition_text}")
    else:
        lines.append("營養估算：無法從這張照片可靠判讀")
    return "\n".join(lines)


def format_nutrition_estimate(nutrition: dict[str, str | int | float | None] | None) -> str | None:
    if not nutrition:
        return None

    parts: list[str] = []
    serving_description = nutrition.get("serving_description")
    if isinstance(serving_description, str) and serving_description.strip():
        parts.append(f"份量：約 {serving_description.strip()}")

    calories = nutrition.get("calories_kcal")
    if isinstance(calories, (int, float)) and not isinstance(calories, bool):
        parts.append(f"熱量：約 {round(calories)} kcal")

    nutrient_labels = {
        "protein_g": "蛋白質",
        "carbohydrates_g": "碳水",
        "fat_g": "脂肪",
        "fiber_g": "纖維",
    }
    macros = []
    for field, label in nutrient_labels.items():
        value = nutrition.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            macros.append(f"{label} {value:g}g")
    if macros:
        parts.append("、".join(macros))

    return "\n".join(parts) or None


def detect_meal_type(now: datetime) -> str:
    current_time = now.astimezone(TAIPEI_TIMEZONE).timetz().replace(tzinfo=None)

    if time(6, 0) <= current_time < time(11, 0):
        return "breakfast"
    if time(11, 0) <= current_time < time(16, 30):
        return "lunch"
    if time(16, 30) <= current_time < time(22, 0):
        return "dinner"
    return "late_night"


def format_meal_type_zh(meal_type: str) -> str:
    return {
        "breakfast": "早餐",
        "lunch": "午餐",
        "dinner": "晚餐",
        "late_night": "宵夜",
    }.get(meal_type, "東西")


def save_chat_target_safely(source: dict) -> None:
    try:
        meal_store.save_chat_target(source)
    except Exception:
        logger.exception("Failed to save LINE chat target")


def save_meal_log_safely(
    *,
    source: dict,
    user_id: str | None,
    display_name: str,
    meal_type: str,
    description: str,
    nutrition: dict[str, str | int | float | None] | None,
    message: dict,
    now: datetime,
) -> None:
    try:
        meal_store.save_meal_log(
            source=source,
            user_id=user_id,
            display_name=display_name,
            meal_type=meal_type,
            description=description,
            nutrition=nutrition,
            message=message,
            now=now,
        )
    except Exception:
        logger.exception("Failed to save meal log")


async def extract_ai_prompt(message: dict, text: str) -> str | None:
    stripped_text = text.strip()
    lowered_text = stripped_text.lower()

    if lowered_text.startswith("/ask"):
        prompt = stripped_text[4:].strip()
        return prompt or "請介紹你自己。"

    if await is_bot_mentioned(message):
        prompt = remove_mention_ranges(text, message.get("mention", {}).get("mentionees", [])).strip()
        return prompt or "請介紹你自己。"

    return None


async def is_bot_mentioned(message: dict) -> bool:
    mention = message.get("mention") or {}
    mentionees = mention.get("mentionees") or []
    if not mentionees:
        return False

    bot_user_id = await line_client.get_bot_user_id()

    for mentionee in mentionees:
        if mentionee.get("isSelf") is True:
            return True
        if mentionee.get("type") == "user" and mentionee.get("userId") == bot_user_id:
            return True

    return False


def remove_mention_ranges(text: str, mentionees: list[dict]) -> str:
    ranges: list[tuple[int, int]] = []
    for mentionee in mentionees:
        start = mentionee.get("index")
        length = mentionee.get("length")
        if isinstance(start, int) and isinstance(length, int):
            ranges.append((start, start + length))

    if not ranges:
        return text

    parts: list[str] = []
    cursor = 0
    for start, end in sorted(ranges):
        if cursor < start:
            parts.append(text[cursor:start])
        cursor = max(cursor, end)
    if cursor < len(text):
        parts.append(text[cursor:])
    return " ".join(part.strip() for part in parts if part.strip())
