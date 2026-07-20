def build_rule_based_reply(text: str) -> str | None:
    normalized = text.strip().lower()

    if normalized == "/ping":
        return "pong"

    if normalized == "/help":
        return (
            "ℹ️ 目前可用功能：\n"
            "/help 顯示這份說明\n"
            "/ping 測試機器人是否在線\n"
            "/飲食紀錄 開啟本群組的飲食歷史\n"
            "/ask 你的問題 觸發 Gemini AI 回覆\n"
            "標記我並輸入問題，也可以觸發 AI 回覆\n"
            "傳圖片時，我會依照時間回覆早餐 / 午餐 / 晚餐 / 宵夜\n"
            "關鍵字：早安、午安、晚安、開會\n"
            "ℹ️ 歡迎和我聊天~"
        )

    if "早安" in text:
        return "早安☀️ 祝你有個美好的一天。"
    if "午安" in text:
        return "午安🌤️ 今天也請繼續加油！"
    if "晚安" in text:
        return "Good night🌙 Have a sweet dream."

    if "開會" in text:
        return "需要我幫你整理會議提醒規則嗎？"

    return None