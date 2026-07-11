import os


class Settings:
    def __init__(self) -> None:
        self.line_channel_secret = self._required("LINE_CHANNEL_SECRET")
        self.line_channel_access_token = self._required("LINE_CHANNEL_ACCESS_TOKEN")
        self.gemini_api_key = self._optional("GEMINI_API_KEY")
        self.line_bot_user_id = self._optional("LINE_BOT_USER_ID")
        self.gemini_model = self._optional("GEMINI_MODEL") or "gemini-3.1-flash-lite"
        self.google_cloud_project = self._optional("GOOGLE_CLOUD_PROJECT")
        self.scheduler_secret = self._optional("SCHEDULER_SECRET")
        self.summary_timezone = self._optional("SUMMARY_TIMEZONE") or "Asia/Taipei"

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.gemini_api_key)

    @staticmethod
    def _required(name: str) -> str:
        value = os.getenv(name)
        if not value:
            raise RuntimeError(f"Missing required environment variable: {name}")
        return value

    @staticmethod
    def _optional(name: str) -> str | None:
        value = os.getenv(name)
        return value or None


settings = Settings()