def build_rule_based_reply(text: str) -> str | None:
    normalized = text.strip().lower()

    if normalized == "/ping":
        return "pong"

    if normalized == "/help":
        return "可用指令：\n/help 顯示說明\n/ping 測試機器人是否在線"

    if "早安" in text:
        return "早安，今天也請多指教。"

    if "開會" in text:
        return "需要我幫你整理會議提醒規則嗎？"

    return None
