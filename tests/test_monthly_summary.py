import os
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ.setdefault("LINE_CHANNEL_SECRET", "test-secret")
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test-token")

from src.summary import (
    build_monthly_backpack_summary,
    build_monthly_meal_profiles,
    build_monthly_meal_summary,
    choose_monthly_title,
    get_month_range,
    public_monthly_feedback_profiles,
    split_text_messages,
)


class MonthlySummaryTests(unittest.TestCase):
    def test_previous_month_range_handles_year_boundary(self) -> None:
        start, end = get_month_range(now=datetime(2027, 1, 15, tzinfo=ZoneInfo("Asia/Taipei")))
        self.assertEqual((start, end), ("2026-12-01", "2026-12-31"))

    def test_explicit_month_range_handles_leap_year(self) -> None:
        self.assertEqual(get_month_range("2028-02"), ("2028-02-01", "2028-02-29"))

    def test_meal_profiles_count_distinct_days_per_meal(self) -> None:
        meals = [
            {"user_id": "u1", "display_name": "Wayne", "meal_type": "breakfast", "local_date": "2026-09-01", "description": "牛肉麵"},
            {"user_id": "u1", "display_name": "Wayne", "meal_type": "breakfast", "local_date": "2026-09-01", "description": "牛肉麵"},
            {"user_id": "u1", "display_name": "Wayne", "meal_type": "breakfast", "local_date": "2026-09-02", "description": "雞絲麵"},
            {"user_id": "u1", "display_name": "Wayne", "meal_type": "lunch", "local_date": "2026-09-02", "description": "拉麵"},
            {"user_id": "u1", "display_name": "Wayne", "meal_type": "dinner", "local_date": "2026-09-03", "description": "不太清楚內容"},
            {"user_id": "u1", "display_name": "Wayne", "meal_type": "dinner", "local_date": "2026-09-03", "description": "牛肉麵"},
        ]

        profiles = build_monthly_meal_profiles(meals)

        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["breakfast_days"], 2)
        self.assertEqual(profiles[0]["lunch_days"], 1)
        self.assertEqual(profiles[0]["dinner_days"], 1)
        self.assertEqual(profiles[0]["active_days"], 3)
        self.assertEqual(
            profiles[0]["food_counts"],
            [
                {"name": "牛肉麵", "count": 2},
                {"name": "拉麵", "count": 1},
                {"name": "雞絲麵", "count": 1},
            ],
        )
        self.assertEqual(
            public_monthly_feedback_profiles(profiles)[0],
            {
                "participant_id": "member_1",
                "active_days": 3,
                "meal_days": {"breakfast": 2, "lunch": 1, "dinner": 1, "late_night": 0},
                "food_counts": [
                    {"name": "牛肉麵", "count": 2},
                    {"name": "拉麵", "count": 1},
                    {"name": "雞絲麵", "count": 1},
                ],
            },
        )

    def test_fallback_title_is_based_on_foods(self) -> None:
        profile = {
            "food_counts": [{"name": "牛肉麵", "count": 3}, {"name": "蛋糕", "count": 1}],
            "breakfast_days": 30,
            "lunch_days": 0,
        }
        self.assertEqual(choose_monthly_title(profile), "麵食探險家")
        self.assertEqual(
            choose_monthly_title({"food_counts": [{"name": "吐司", "count": 2}, {"name": "麵包", "count": 1}]}),
            "烘焙尋味家",
        )

    def test_meal_summary_uses_generated_feedback(self) -> None:
        profiles = build_monthly_meal_profiles(
            [{"user_id": "u1", "display_name": "Wayne", "meal_type": "breakfast", "local_date": "2026-09-01"}]
        )
        feedback = "這個月留下了早餐紀錄。下個月可以試著分享不同餐別的餐點。"
        text = build_monthly_meal_summary("2026-09-01", profiles, {"u1": feedback})
        self.assertIn(f"Wayne\n紀錄天數：", text)
        self.assertIn(feedback, text)
        self.assertIn("早餐 1 天・午餐 0 天・晚餐 0 天", text)

    def test_missing_member_feedback_uses_personal_fallback(self) -> None:
        profiles = build_monthly_meal_profiles([
            {"user_id": "u1", "display_name": "Wayne", "meal_type": "lunch", "local_date": "2026-09-01", "description": "牛肉麵"},
            {"user_id": "u2", "display_name": "Amy", "meal_type": "dinner", "local_date": "2026-09-02", "description": "咖哩飯"},
        ])
        text = build_monthly_meal_summary("2026-09-01", profiles, {"u1": "你記錄了牛肉麵。下個月試一道新料理。"})
        self.assertIn("你記錄了牛肉麵。下個月試一道新料理。", text)
        self.assertIn("其中有咖哩飯", text)
        self.assertIn("還不足以看出整月的飲食習慣", text)
        self.assertIn("下個月可以多分享", text)

    def test_fallback_handles_unidentified_food_and_regular_records(self) -> None:
        for description, expected in [("不太清楚內容", "補上餐點名稱"), ("牛肉麵", "每週試一道")]:
            with self.subTest(description=description):
                profiles = build_monthly_meal_profiles([
                    {"user_id": "u1", "display_name": "Wayne", "meal_type": "lunch", "local_date": f"2026-09-0{day}", "description": description}
                    for day in range(1, 4)
                ])
                text = build_monthly_meal_summary("2026-09-01", profiles)
                self.assertIn("在 3 天留下了用餐紀錄", text)
                self.assertIn(expected, text)

    def test_empty_month_has_no_generated_member_paragraphs(self) -> None:
        self.assertIn("這個月還沒有用餐紀錄", build_monthly_meal_summary("2026-09-01", []))

    def test_backpack_summary_uses_shared_ranks_for_ties(self) -> None:
        text = build_monthly_backpack_summary(
            "2026-09-01",
            [
                {"display_name": "Amy", "count": 5},
                {"display_name": "Wayne", "count": 5},
                {"display_name": "Ben", "count": 2},
            ],
            12,
        )
        self.assertEqual(text.count("🥇"), 2)
        self.assertIn("🥉 Ben", text)
        self.assertIn("本月共發現 12 次藝寶包", text)

    def test_long_text_is_split_under_line_limit(self) -> None:
        chunks = split_text_messages("第一行\n" + "內容" * 20, max_length=12)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 12 for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
