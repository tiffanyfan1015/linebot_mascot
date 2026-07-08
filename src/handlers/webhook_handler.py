import json
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

import httpx

from src.ai_client import AIServiceError, gemini_ai_client
from src.handlers.reply_rules import build_rule_based_reply
from src.line_client import line_client


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

    if event_type == "join" and reply_token:
        await line_client.reply_text(reply_token, "大家好，我是 LINE Bot。請傳文字訊息給我測試。")
        return

    if event_type != "message" or not reply_token:
        return

    message = event.get("message", {})
    source = event.get("source", {})
    display_name = await resolve_display_name(source)

    if message.get("type") == "image":
        await handle_image_message(reply_token, message, display_name)
        return

    if message.get("type") != "text":
        return

    text = message.get("text", "")
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


async def handle_image_message(reply_token: str, message: dict, display_name: str) -> None:
    logger.info("Received LINE image message payload=%s", json.dumps(message, ensure_ascii=False))

    if not gemini_ai_client.enabled:
        logger.info("Skipping image food classification because Gemini is not configured")
        return

    try:
        image_bytes, mime_type = await fetch_image_bytes(message)
        is_food = gemini_ai_client.is_food_image(image_bytes, mime_type)
    except AIServiceError:
        logger.exception("Gemini image classification failed")
        return
    except httpx.HTTPError:
        logger.exception(
            "Failed to fetch image content in image handler: payload=%s",
            json.dumps(message, ensure_ascii=False),
        )
        return

    if is_food:
        await line_client.reply_text(reply_token, build_photo_meal_reply(display_name))
        return

    logger.info("Image was not classified as food; skipping meal reply")


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


def build_photo_meal_reply(display_name: str, now: datetime | None = None) -> str:
    current_time = (now or datetime.now(TAIPEI_TIMEZONE)).timetz().replace(tzinfo=None)

    if time(6, 0) <= current_time < time(11, 0):
        meal_text = "吃早餐了"
    elif time(11, 0) <= current_time < time(16, 30):
        meal_text = "吃午餐了"
    elif time(16, 30) <= current_time < time(22, 0):
        meal_text = "吃晚餐了"
    else:
        meal_text = "吃消夜了"

    return f"{display_name} {meal_text}"


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