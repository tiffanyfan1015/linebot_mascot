import os


class Settings:
    def __init__(self) -> None:
        self.line_channel_secret = self._required("LINE_CHANNEL_SECRET")
        self.line_channel_access_token = self._required("LINE_CHANNEL_ACCESS_TOKEN")

    @staticmethod
    def _required(name: str) -> str:
        value = os.getenv(name)
        if not value:
            raise RuntimeError(f"Missing required environment variable: {name}")
        return value


settings = Settings()
