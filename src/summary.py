from collections import defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.config import settings
from src.handlers.webhook_handler import format_meal_type_zh


MEAL_ORDER = ["breakfast", "lunch", "dinner", "late_night"]
MAIN_MEAL_TYPES = {"breakfast", "lunch", "dinner"}


def get_summary_date(now: datetime | None = None) -> str:
    timezone = ZoneInfo(settings.summary_timezone)
    local_now = (now or datetime.now(timezone)).astimezone(timezone)
    return local_now.date().isoformat()


def build_daily_summary(
    local_date: str,
    meals: list[dict[str, Any]],
    daily_titles: dict[str, str] | None = None,
) -> str:
    title = f"🍽️ {local_date} 吃飯紀錄🍽️\n "
    if not meals:
        return f"{title}\n\n今天還沒有食物紀錄。"

    by_meal_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    meals_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    display_names: dict[str, str] = {}
    for meal in meals:
        meal_type = meal.get("meal_type") or "unknown"
        by_meal_type[meal_type].append(meal)
        user_key = get_user_key(meal)
        meals_by_user[user_key].append(meal)
        display_names.setdefault(user_key, meal.get("display_name") or "有人")

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
            calories = get_nutrition_number(record, "calories_kcal")
            calorie_text = f"，約 {round(calories)} kcal" if calories is not None else ""
            lines.append(f"- {display_name}：{description}{calorie_text}")

    lines.append("")
    lines.append("今日稱號✨")
    for user_key, records in meals_by_user.items():
        generated_title = (daily_titles or {}).get(user_key)
        lines.append(f"- {display_names[user_key]}：{generated_title or choose_daily_title(records)}")

    lines.append("")
    lines.append("大家今天吃了幾餐？")
    for user_key, records in meals_by_user.items():
        lines.append(f"- {display_names[user_key]}：{len(records)} 餐")
    return "\n".join(lines)


def build_daily_title_profiles(meals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    meals_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for meal in meals:
        meals_by_user[get_user_key(meal)].append(meal)

    profiles: list[dict[str, Any]] = []
    for index, (user_key, records) in enumerate(meals_by_user.items(), start=1):
        food_names = list(
            dict.fromkeys(
                (record.get("description") or "不太清楚內容").strip()
                for record in records
                if (record.get("description") or "").strip()
            )
        )
        profiles.append(
            {
                "participant_id": f"member_{index}",
                "user_key": user_key,
                "meal_types": sorted({record.get("meal_type") or "unknown" for record in records}),
                "foods": food_names[:8],
                "meal_count": len(records),
                "estimated_nutrition": {
                    "calories_kcal": round(sum_nutrition(records, "calories_kcal")),
                    "protein_g": round(sum_nutrition(records, "protein_g"), 1),
                    "carbohydrates_g": round(sum_nutrition(records, "carbohydrates_g"), 1),
                    "fat_g": round(sum_nutrition(records, "fat_g"), 1),
                    "fiber_g": round(sum_nutrition(records, "fiber_g"), 1),
                },
            }
        )
    return profiles


def public_daily_title_profiles(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in profile.items() if key != "user_key"} for profile in profiles]


def map_daily_titles_to_users(profiles: list[dict[str, Any]], titles: dict[str, str]) -> dict[str, str]:
    return {
        profile["user_key"]: title
        for profile in profiles
        if isinstance(profile.get("user_key"), str)
        if (title := titles.get(profile.get("participant_id")))
    }


def choose_daily_title(meals: list[dict[str, Any]]) -> str:
    meal_types = {meal.get("meal_type") for meal in meals}
    main_meal_count = len(meal_types & MAIN_MEAL_TYPES)
    descriptions = {
        (meal.get("description") or "").strip()
        for meal in meals
        if (meal.get("description") or "").strip() and (meal.get("description") or "").strip() != "不太清楚內容"
    }
    calories_kcal = sum_nutrition(meals, "calories_kcal")
    protein_g = sum_nutrition(meals, "protein_g")
    fiber_g = sum_nutrition(meals, "fiber_g")

    if main_meal_count == len(MAIN_MEAL_TYPES) and protein_g >= 50 and fiber_g >= 10:
        return "健康王"
    if main_meal_count == len(MAIN_MEAL_TYPES):
        return "準時用餐王"
    if len(descriptions) >= 4:
        return "飲食豐盛王"
    if protein_g >= 60:
        return "蛋白補給王"
    if fiber_g >= 10:
        return "纖維補給王"
    if calories_kcal >= 1800:
        return "能量滿格王"
    if main_meal_count == 2:
        return "雙餐達人"
    if "late_night" in meal_types:
        return "宵夜戰士"
    if "breakfast" in meal_types:
        return "早餐活力王"
    if "lunch" in meal_types:
        return "午餐充電王"
    if "dinner" in meal_types:
        return "晚餐品味王"
    if len(meals) >= 2:
        return "加餐小達人"
    return "美食探索王"


def get_user_key(meal: dict[str, Any]) -> str:
    return str(meal.get("user_id") or meal.get("display_name") or meal.get("id") or "unknown")


def sum_nutrition(meals: list[dict[str, Any]], field: str) -> float:
    return sum(value for meal in meals if (value := get_nutrition_number(meal, field)) is not None)


def get_nutrition_number(meal: dict[str, Any], field: str) -> float | None:
    nutrition = meal.get("nutrition")
    if not isinstance(nutrition, dict):
        return None
    value = nutrition.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
