import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from google.cloud import firestore

from src.config import settings


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
