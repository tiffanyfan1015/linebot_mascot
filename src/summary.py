from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.config import settings
from src.handlers.webhook_handler import format_meal_type_zh


MEAL_ORDER = ["breakfast", "lunch", "dinner", "late_night"]
MAIN_MEAL_TYPES = {"breakfast", "lunch", "dinner"}


def get_summary_date(now: datetime | None = None) -> str:
    timezone = ZoneInfo(settings.summary_timezone)
    local_now = (now or datetime.now(timezone)).astimezone(timezone)
    return (local_now - timedelta(days=1)).date().isoformat()


def get_month_range(year_month: str | None = None, now: datetime | None = None) -> tuple[str, str]:
    if year_month:
        try:
            month_start = date.fromisoformat(f"{year_month}-01")
        except ValueError as exc:
            raise ValueError("month must use YYYY-MM") from exc
    else:
        timezone = ZoneInfo(settings.summary_timezone)
        local_now = (now or datetime.now(timezone)).astimezone(timezone)
        current_month_start = local_now.date().replace(day=1)
        month_start = (current_month_start - timedelta(days=1)).replace(day=1)

    if month_start.month == 12:
        next_month_start = date(month_start.year + 1, 1, 1)
    else:
        next_month_start = date(month_start.year, month_start.month + 1, 1)
    month_end = next_month_start - timedelta(days=1)
    return month_start.isoformat(), month_end.isoformat()


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
    lines.append("大家昨天吃了幾餐？")
    for user_key, records in meals_by_user.items():
        lines.append(f"- {display_names[user_key]}：{len(records)} 餐")

    lines.append("")
    lines.append("今天也請大家一起規律、健康飲食！💪")
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


def build_monthly_meal_profiles(meals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    meals_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for meal in meals:
        meals_by_user[get_user_key(meal)].append(meal)

    profiles: list[dict[str, Any]] = []
    for index, (user_key, records) in enumerate(meals_by_user.items(), start=1):
        meal_days = {
            meal_type: len(
                {
                    record["local_date"]
                    for record in records
                    if record.get("meal_type") == meal_type and isinstance(record.get("local_date"), str)
                }
            )
            for meal_type in MEAL_ORDER
        }
        active_days = len(
            {record["local_date"] for record in records if isinstance(record.get("local_date"), str)}
        )
        food_occurrences = {
            (record.get("local_date"), record.get("meal_type"), description)
            for record in records
            if (description := (record.get("description") or "").strip())
            if description != "不太清楚內容"
        }
        food_counts = Counter(description for _, _, description in food_occurrences)
        profiles.append(
            {
                "participant_id": f"member_{index}",
                "user_key": user_key,
                "display_name": records[-1].get("display_name") or "有人",
                "breakfast_days": meal_days["breakfast"],
                "lunch_days": meal_days["lunch"],
                "dinner_days": meal_days["dinner"],
                "late_night_days": meal_days["late_night"],
                "active_days": active_days,
                "food_counts": [
                    {"name": name, "count": count}
                    for name, count in sorted(food_counts.items(), key=lambda item: (-item[1], item[0]))[:40]
                ],
            }
        )
    return sorted(
        profiles,
        key=lambda profile: (
            -profile["active_days"],
            -(profile["breakfast_days"] + profile["lunch_days"] + profile["dinner_days"]),
            profile["display_name"],
        ),
    )


def public_monthly_feedback_profiles(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "participant_id": profile["participant_id"],
            "food_counts": profile.get("food_counts") or [],
            "active_days": profile["active_days"],
            "meal_days": {meal_type: profile[f"{meal_type}_days"] for meal_type in MEAL_ORDER},
        }
        for profile in profiles
    ]


def build_monthly_fallback_feedback(profile: dict[str, Any]) -> str:
    active_days = profile["active_days"]
    food_counts = profile.get("food_counts") or []
    opening = f"這個月你在 {active_days} 天留下了用餐紀錄。"
    if not food_counts:
        return opening + "目前可辨識的食物資訊還不多，下個月可以試著記錄不同餐別，並補上餐點名稱，讓回顧更有內容。📸"
    favorites = "、".join(item["name"] for item in food_counts[:3])
    if active_days < 3:
        return opening + f"其中有{favorites}，不過目前紀錄較少，還不足以看出整月的飲食習慣。下個月可以多分享幾天、不同餐別的餐點，慢慢累積自己的美食日記。📸"
    return (
        opening + f"其中較常出現的餐點有{favorites}，這些是你本月美食日記的一部分。"
        "下個月可以從常吃的餐點出發，每週試一道不同食材或做法的料理，也把新嘗試記錄下來，看看自己喜歡哪些變化。🌱"
    )


def build_monthly_meal_summary(
    month_start: str,
    profiles: list[dict[str, Any]],
    monthly_feedback: dict[str, str] | None = None,
    monthly_titles: dict[str, str] | None = None,
) -> str:
    month_label = format_month_label(month_start)
    lines = [f"🍽️ {month_label}用餐統計"]
    if not profiles:
        return "\n".join([*lines, "", "這個月還沒有用餐紀錄。"])

    for profile in profiles:
        title = (monthly_titles or {}).get(profile["user_key"]) or choose_monthly_title(profile)
        feedback = (monthly_feedback or {}).get(profile["user_key"]) or build_monthly_fallback_feedback(profile)
        lines.extend(
            [
                "",
                f"🏷️ {profile['display_name']}｜{title}",
                (
                    f"📅 紀錄天數：早餐 {profile['breakfast_days']} 天・午餐 {profile['lunch_days']} 天・"
                    f"晚餐 {profile['dinner_days']} 天"
                ),
                feedback,
            ]
        )
    return "\n".join(lines)


def build_monthly_backpack_summary(month_start: str, leaderboard: list[dict[str, Any]], total_sightings: int) -> str:
    month_label = format_month_label(month_start)
    lines = [f"🎒 {month_label}藝寶包排行榜"]
    if not leaderboard:
        return "\n".join([*lines, "", "這個月還沒有藝寶包發現紀錄。"])

    previous_count: int | None = None
    previous_rank = 0
    for position, item in enumerate(leaderboard, start=1):
        count = int(item.get("count") or 0)
        if count != previous_count:
            previous_rank = position
        rank_label = {1: "🥇", 2: "🥈", 3: "🥉"}.get(previous_rank, f"第 {previous_rank} 名")
        lines.append(f"{rank_label} {item.get('display_name') or '匿名'}　{count} 次")
        previous_count = count
    lines.extend(["", f"本月共發現 {total_sightings} 次藝寶包"])
    return "\n".join(lines)


def choose_monthly_title(profile: dict[str, Any]) -> str:
    food_counts = profile.get("food_counts") or [
        {"name": food, "count": 1} for food in profile.get("foods") or []
    ]
    title_keywords = [
        ("甜點收藏家", ("蛋糕", "甜點", "布丁", "冰淇淋", "餅乾", "巧克力", "鬆餅", "可麗露", "糖果")),
        ("烘焙尋味家", ("麵包", "吐司", "貝果", "可頌", "三明治")),
        ("麵食探險家", ("麵", "拉麵", "烏龍", "義大利麵", "米粉", "冬粉")),
        ("米飯料理家", ("飯", "便當", "丼", "咖哩", "粥", "燉飯", "壽司")),
        ("咖啡香氣家", ("咖啡", "拿鐵", "卡布奇諾", "美式")),
        ("蔬食彩盤家", ("蔬菜", "青菜", "沙拉", "花椰菜", "菠菜", "菇")),
        ("暖鍋尋味家", ("火鍋", "鍋物", "湯", "鍋燒", "關東煮")),
        ("海味探索家", ("魚", "蝦", "蟹", "蛤", "牡蠣", "海鮮", "生魚片")),
        ("肉食風味家", ("牛", "豬", "雞", "鴨", "羊", "排骨", "肉")),
        ("水果繽紛家", ("水果", "蘋果", "香蕉", "芭樂", "草莓", "葡萄", "西瓜")),
    ]
    best_title = "風味探索家"
    best_score = 0
    for title, keywords in title_keywords:
        score = sum(
            int(item.get("count") or 0)
            for item in food_counts
            if isinstance(item, dict)
            if any(keyword in str(item.get("name") or "").lower() for keyword in keywords)
        )
        if score > best_score:
            best_title = title
            best_score = score
    return best_title


def format_month_label(month_start: str) -> str:
    parsed = date.fromisoformat(month_start)
    return f"{parsed.year} 年 {parsed.month} 月"


def split_text_messages(text: str, max_length: int = 4900) -> list[str]:
    if len(text) <= max_length:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if current and len(current) + len(line) > max_length:
            chunks.append(current.rstrip())
            current = ""
        while len(line) > max_length:
            chunks.append(line[:max_length].rstrip())
            line = line[max_length:]
        current += line
    if current:
        chunks.append(current.rstrip())
    return chunks


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
