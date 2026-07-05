import logging

import httpx

from src.handlers.reply_rules import build_rule_based_reply
from src.line_client import line_client


logger = logging.getLogger(__name__)


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
    if message.get("type") != "text":
        return

    text = message.get("text", "")
    source = event.get("source", {})
    display_name = await resolve_display_name(source)
    rule_reply = build_rule_based_reply(text)

    if rule_reply:
        await line_client.reply_text(reply_token, rule_reply)
        return

    await line_client.reply_text(reply_token, f"{display_name} 說：{text}")


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
