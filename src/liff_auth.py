import base64
import binascii
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

import httpx

from src.config import settings


LINE_ID_TOKEN_VERIFY_URL = "https://api.line.me/oauth2/v2.1/verify"
TICKET_TTL_SECONDS = 15 * 60


class LiffConfigurationError(Exception):
    pass


class LiffAuthenticationError(Exception):
    pass


class LiffServiceError(Exception):
    pass


@dataclass(frozen=True)
class GroupAccessTicket:
    target_id: str
    user_id: str
    expires_at: int


def create_group_access_ticket(target_id: str, user_id: str, now: int | None = None) -> str:
    secret = _ticket_secret()
    issued_at = int(time.time()) if now is None else now
    payload = {
        "version": 1,
        "target_id": target_id,
        "user_id": user_id,
        "issued_at": issued_at,
        "expires_at": issued_at + TICKET_TTL_SECONDS,
    }
    encoded_payload = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(secret, encoded_payload.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded_payload}.{_base64url_encode(signature)}"


def verify_group_access_ticket(ticket: str, now: int | None = None) -> GroupAccessTicket:
    secret = _ticket_secret()
    try:
        encoded_payload, encoded_signature = ticket.split(".", 1)
        supplied_signature = _base64url_decode(encoded_signature)
        expected_signature = hmac.new(secret, encoded_payload.encode("ascii"), hashlib.sha256).digest()
    except (ValueError, TypeError, UnicodeEncodeError, binascii.Error):
        raise LiffAuthenticationError("Invalid access ticket") from None

    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise LiffAuthenticationError("Invalid access ticket")

    try:
        payload = json.loads(_base64url_decode(encoded_payload).decode("utf-8"))
        target_id = payload["target_id"]
        user_id = payload["user_id"]
        expires_at = payload["expires_at"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        raise LiffAuthenticationError("Invalid access ticket") from None

    current_time = int(time.time()) if now is None else now
    if (
        payload.get("version") != 1
        or not isinstance(target_id, str)
        or not target_id
        or not isinstance(user_id, str)
        or not user_id
    ):
        raise LiffAuthenticationError("Invalid access ticket")
    if not isinstance(expires_at, int) or expires_at <= current_time:
        raise LiffAuthenticationError("Access ticket has expired")
    return GroupAccessTicket(target_id=target_id, user_id=user_id, expires_at=expires_at)


async def verify_line_id_token(id_token: str) -> str:
    if not settings.line_login_channel_id:
        raise LiffConfigurationError("LINE_LOGIN_CHANNEL_ID is not configured")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                LINE_ID_TOKEN_VERIFY_URL,
                data={"id_token": id_token, "client_id": settings.line_login_channel_id},
            )
    except httpx.HTTPError as exc:
        raise LiffServiceError("LINE token verification is unavailable") from exc

    if 400 <= response.status_code < 500:
        raise LiffAuthenticationError("Invalid LINE ID token")
    try:
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise LiffServiceError("LINE token verification failed") from exc

    try:
        claims = response.json()
    except ValueError as exc:
        raise LiffServiceError("LINE token verification returned invalid JSON") from exc

    user_id = claims.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise LiffAuthenticationError("LINE ID token has no user ID")
    return user_id


def build_liff_group_history_url(ticket: str) -> str:
    if not settings.liff_id:
        raise LiffConfigurationError("LIFF_ID is not configured")
    return f"https://liff.line.me/{settings.liff_id}?ticket={ticket}"


def member_key(target_id: str, user_id: str | None) -> str:
    value = f"{target_id}:{user_id or 'unknown'}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:20]


def record_key(target_id: str, document_id: str) -> str:
    value = f"{target_id}:{document_id}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:20]


def create_meal_cursor(target_id: str, document_id: str) -> str:
    payload = json.dumps(
        {"version": 1, "kind": "meal_cursor", "target_id": target_id, "document_id": document_id},
        separators=(",", ":"),
    )
    encoded_payload = _base64url_encode(payload.encode("utf-8"))
    signature = hmac.new(_ticket_secret(), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded_payload}.{_base64url_encode(signature)}"


def verify_meal_cursor(cursor: str, target_id: str) -> str:
    try:
        encoded_payload, encoded_signature = cursor.split(".", 1)
        supplied_signature = _base64url_decode(encoded_signature)
        expected_signature = hmac.new(
            _ticket_secret(),
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        payload = json.loads(_base64url_decode(encoded_payload).decode("utf-8"))
    except (ValueError, TypeError, UnicodeEncodeError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
        raise LiffAuthenticationError("Invalid pagination cursor") from None

    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise LiffAuthenticationError("Invalid pagination cursor")
    document_id = payload.get("document_id")
    if (
        payload.get("version") != 1
        or payload.get("kind") != "meal_cursor"
        or payload.get("target_id") != target_id
        or not isinstance(document_id, str)
        or not document_id
    ):
        raise LiffAuthenticationError("Invalid pagination cursor")
    return document_id


def _ticket_secret() -> bytes:
    if not settings.liff_ticket_secret:
        raise LiffConfigurationError("LIFF_TICKET_SECRET is not configured")
    if len(settings.liff_ticket_secret) < 32:
        raise LiffConfigurationError("LIFF_TICKET_SECRET must be at least 32 characters")
    return settings.liff_ticket_secret.encode("utf-8")


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
