from collections import defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.config import settings
from src.handlers.webhook_handler import format_meal_type_zh


MEAL_ORDER = ["breakfast", "lunch", "dinner", "late_night"]


def get_summary_date(now: datetime | None = None) -> str:
    timezone = ZoneInfo(settings.summary_timezone)
    local_now = (now or datetime.now(timezone)).astimezone(timezone)
    return local_now.date().isoformat()


def build_daily_summary(local_date: str, meals: list[dict[str, Any]]) -> str:
    title = f"🍽️今日吃飯紀錄🍽️\n 📅{local_date}"
    if not meals:
        return f"{title}\n\n今天還沒有食物紀錄。"

    by_meal_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_users: set[str] = set()
    for meal in meals:
        meal_type = meal.get("meal_type") or "unknown"
        by_meal_type[meal_type].append(meal)
        user_key = meal.get("user_id") or meal.get("display_name") or meal.get("id")
        if user_key:
            seen_users.add(str(user_key))

    lines = [title]
    ordered_meal_types = MEAL_ORDER + sorted(meal_type for meal_type in by_meal_type if meal_type not in MEAL_ORDER)
    for meal_type in ordered_meal_types:
        records = by_meal_type.get(meal_type, [])
        lines.append("")
        lines.append(format_meal_type_zh(meal_type))
        if not records:
            lines.append("- 還沒有人記錄")
            continue
        for record in records:
            display_name = record.get("display_name") or "有人"
            description = (record.get("description") or "不太清楚內容").strip()
            calories = (record.get("nutrition") or {}).get("calories_kcal")
            calorie_text = f"，約 {round(calories)} kcal" if isinstance(calories, (int, float)) else ""
            lines.append(f"- {display_name}：{description}{calorie_text}")

    lines.append("")
    lines.append(f"總計：{len(seen_users)} 人，{len(meals)} 筆紀錄")
    return "\n".join(lines)
