import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from google.cloud import firestore

from src.config import settings
from src.liff_auth import (
    LiffAuthenticationError,
    create_meal_cursor,
    member_key,
    record_key,
    verify_meal_cursor,
)


logger = logging.getLogger(__name__)
MEAL_LOGS_COLLECTION = "meal_logs"
CHAT_TARGETS_COLLECTION = "chat_targets"


class MealStore:
    def __init__(self) -> None:
        self._client: firestore.Client | None = None

    @property
    def client(self) -> firestore.Client:
        if self._client is None:
            kwargs: dict[str, str] = {}
            if settings.google_cloud_project:
                kwargs["project"] = settings.google_cloud_project
            self._client = firestore.Client(**kwargs)
        return self._client

    def save_chat_target(self, source: dict[str, Any]) -> None:
        target = build_chat_target(source)
        if not target:
            return

        doc_ref = self.client.collection(CHAT_TARGETS_COLLECTION).document(target["target_id"])
        snapshot = doc_ref.get()
        payload = {
            **target,
            "enabled": True,
            "summary_enabled": True,
            "timezone": settings.summary_timezone,
            "last_seen_at": firestore.SERVER_TIMESTAMP,
        }
        if not snapshot.exists:
            payload["joined_at"] = firestore.SERVER_TIMESTAMP

        doc_ref.set(payload, merge=True)

    def save_meal_log(
        self,
        *,
        source: dict[str, Any],
        user_id: str | None,
        display_name: str,
        meal_type: str,
        description: str,
        nutrition: dict[str, str | int | float | None] | None,
        message: dict[str, Any],
        now: datetime,
    ) -> None:
        target = build_chat_target(source)
        if not target:
            logger.info("Skipping meal log because source has no group or room target")
            return

        message_id = message.get("id")
        local_now = now.astimezone(ZoneInfo(settings.summary_timezone))
        document_id = str(message_id) if message_id else None
        doc_ref = (
            self.client.collection(MEAL_LOGS_COLLECTION).document(document_id)
            if document_id
            else self.client.collection(MEAL_LOGS_COLLECTION).document()
        )

        doc_ref.set(
            {
                **target,
                "user_id": user_id,
                "display_name": display_name,
                "meal_type": meal_type,
                "description": description.strip() or "不太清楚內容",
                "nutrition": nutrition,
                "message_type": message.get("type", "image"),
                "line_message_id": message_id,
                "local_date": local_now.date().isoformat(),
                "local_time": local_now.time().replace(microsecond=0).isoformat(),
                "timezone": settings.summary_timezone,
                "created_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )

    def list_summary_targets(self) -> list[dict[str, Any]]:
        query = (
            self.client.collection(CHAT_TARGETS_COLLECTION)
            .where("enabled", "==", True)
            .where("summary_enabled", "==", True)
        )
        return [snapshot.to_dict() | {"id": snapshot.id} for snapshot in query.stream()]

    def list_meals_for_date(self, target_id: str, local_date: str) -> list[dict[str, Any]]:
        query = (
            self.client.collection(MEAL_LOGS_COLLECTION)
            .where("target_id", "==", target_id)
            .where("local_date", "==", local_date)
        )
        meals = [snapshot.to_dict() | {"id": snapshot.id} for snapshot in query.stream()]
        return sorted(meals, key=lambda meal: meal.get("local_time") or "")

    def list_group_meals(
        self,
        *,
        target_id: str,
        from_date: str,
        to_date: str,
        meal_type: str | None = None,
        selected_member_key: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        collection = self.client.collection(MEAL_LOGS_COLLECTION)
        query = (
            collection.where("target_id", "==", target_id)
            .where("local_date", ">=", from_date)
            .where("local_date", "<=", to_date)
            .order_by("local_date", direction=firestore.Query.DESCENDING)
            .order_by("local_time", direction=firestore.Query.DESCENDING)
        )

        if cursor:
            try:
                cursor_document_id = verify_meal_cursor(cursor, target_id)
            except LiffAuthenticationError as exc:
                raise ValueError(str(exc)) from exc
            cursor_snapshot = collection.document(cursor_document_id).get()
            cursor_data = cursor_snapshot.to_dict() if cursor_snapshot.exists else None
            if not cursor_data or cursor_data.get("target_id") != target_id:
                raise ValueError("Invalid pagination cursor")
            query = query.start_after(cursor_snapshot)

        matching_records: list[dict[str, Any]] = []
        for snapshot in query.stream():
            meal = snapshot.to_dict() or {}
            if meal_type and meal.get("meal_type") != meal_type:
                continue
            record_member_key = member_key(target_id, meal.get("user_id"))
            if selected_member_key and record_member_key != selected_member_key:
                continue

            matching_records.append(serialize_group_meal(snapshot.id, meal, record_member_key))
            if len(matching_records) > limit:
                break

        next_cursor = create_meal_cursor(target_id, matching_records[limit - 1]["document_id"]) if len(matching_records) > limit else None
        return [{key: value for key, value in record.items() if key != "document_id"} for record in matching_records[:limit]], next_cursor



def serialize_group_meal(document_id: str, meal: dict[str, Any], record_member_key: str) -> dict[str, Any]:
    nutrition = meal.get("nutrition")
    return {
        "document_id": document_id,
        "record_key": record_key(meal.get("target_id") or "", document_id),
        "member_key": record_member_key,
        "display_name": meal.get("display_name") or "有人",
        "meal_type": meal.get("meal_type") or "unknown",
        "description": meal.get("description") or "不太清楚內容",
        "nutrition": nutrition if isinstance(nutrition, dict) else None,
        "local_date": meal.get("local_date"),
        "local_time": meal.get("local_time"),
        "timezone": meal.get("timezone") or settings.summary_timezone,
    }


def build_chat_target(source: dict[str, Any]) -> dict[str, Any] | None:
    source_type = source.get("type")
    if source_type == "group" and source.get("groupId"):
        group_id = source["groupId"]
        return {
            "source_type": "group",
            "target_id": group_id,
            "group_id": group_id,
            "room_id": None,
        }
    if source_type == "room" and source.get("roomId"):
        room_id = source["roomId"]
        return {
            "source_type": "room",
            "target_id": room_id,
            "group_id": None,
            "room_id": room_id,
        }
    return None


meal_store = MealStore()
