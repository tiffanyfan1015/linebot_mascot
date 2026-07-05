import base64
import hashlib
import hmac

from src.config import settings


def verify_line_signature(body: bytes, signature: str) -> bool:
    if not signature:
        return False

    digest = hmac.new(
        settings.line_channel_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected_signature = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected_signature, signature)
