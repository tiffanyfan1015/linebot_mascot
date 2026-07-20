import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles

from src.ai_client import AIServiceError, gemini_ai_client
from src.config import settings
from src.handlers.webhook_handler import handle_events
from src.liff_auth import (
    LiffAuthenticationError,
    LiffConfigurationError,
    LiffServiceError,
    verify_group_access_ticket,
    verify_line_id_token,
)
from src.line_client import line_client
from src.meal_store import meal_store
from src.summary import (
    build_daily_summary,
    build_daily_title_profiles,
    get_summary_date,
    map_daily_titles_to_users,
    public_daily_title_profiles,
)
from src.security import verify_line_signature


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="LINE Bot")
app.mount("/liff", StaticFiles(directory=Path(__file__).resolve().parent / "liff", html=True), name="liff")


@app.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}


@app.post("/webhook")
async def webhook(
    request: Request,
    x_line_signature: str = Header(default=""),
) -> dict[str, bool]:
    body = await request.body()

    if not verify_line_signature(body, x_line_signature):
        raise HTTPException(status_code=403, detail="Invalid LINE signature")

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    await handle_events(payload.get("events", []))
    return {"ok": True}


@app.get("/api/liff/config")
async def liff_config() -> dict[str, str | None]:
    return {"liff_id": settings.liff_id}


@app.get("/api/liff/group-meals")
async def liff_group_meals(
    ticket: str = Query(min_length=20, max_length=2048),
    authorization: str = Header(default=""),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    meal_type: str | None = Query(default=None),
    member: str | None = Query(default=None, min_length=20, max_length=20),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> dict:
    access = await authenticate_liff_group_request(authorization, ticket)
    allowed_meal_types = {"breakfast", "lunch", "dinner", "late_night"}
    if meal_type and meal_type not in allowed_meal_types:
        raise HTTPException(status_code=400, detail="Invalid meal_type")

    today = datetime.now(ZoneInfo(settings.summary_timezone)).date()
    selected_to_date = to_date or today
    selected_from_date = from_date or (selected_to_date - timedelta(days=29))
    if selected_from_date > selected_to_date:
        raise HTTPException(status_code=400, detail="from must not be later than to")
    if (selected_to_date - selected_from_date).days > 366:
        raise HTTPException(status_code=400, detail="Date range cannot exceed 366 days")

    try:
        meals, next_cursor = meal_store.list_group_meals(
            target_id=access.target_id,
            from_date=selected_from_date.isoformat(),
            to_date=selected_to_date.isoformat(),
            meal_type=meal_type,
            selected_member_key=member,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "from": selected_from_date.isoformat(),
        "to": selected_to_date.isoformat(),
        "items": meals,
        "next_cursor": next_cursor,
    }


async def authenticate_liff_group_request(authorization: str, ticket: str):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing LINE ID token")
    id_token = authorization.removeprefix("Bearer ").strip()
    if not id_token:
        raise HTTPException(status_code=401, detail="Missing LINE ID token")

    try:
        access = verify_group_access_ticket(ticket)
        line_user_id = await verify_line_id_token(id_token)
    except LiffConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LiffAuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except LiffServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if access.user_id is not None and line_user_id != access.user_id:
        raise HTTPException(status_code=403, detail="This ticket belongs to another LINE user")
    if access.user_id is None:
        try:
            await line_client.get_group_member_profile(access.target_id, line_user_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {400, 403, 404}:
                raise HTTPException(status_code=403, detail="You are not a member of this LINE group") from exc
            raise HTTPException(status_code=502, detail="LINE group membership verification failed") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="LINE group membership verification is unavailable") from exc
    return access


@app.post("/jobs/daily-summary")
async def daily_summary(x_scheduler_secret: str = Header(default="")) -> dict[str, int | bool | str]:
    if not settings.scheduler_secret:
        raise HTTPException(status_code=500, detail="SCHEDULER_SECRET is not configured")
    if x_scheduler_secret != settings.scheduler_secret:
        raise HTTPException(status_code=403, detail="Invalid scheduler secret")

    local_date = get_summary_date()
    targets = meal_store.list_summary_targets()
    sent_count = 0

    for target in targets:
        target_id = target.get("target_id") or target.get("id")
        if not target_id:
            continue

        meals = meal_store.list_meals_for_date(target_id, local_date)
        daily_titles: dict[str, str] = {}
        if meals and gemini_ai_client.enabled:
            profiles = build_daily_title_profiles(meals)
            try:
                generated_titles = gemini_ai_client.generate_daily_titles(public_daily_title_profiles(profiles))
                daily_titles = map_daily_titles_to_users(profiles, generated_titles)
            except AIServiceError:
                logger.exception("Gemini daily title generation failed; using fallback titles")

        summary_text = build_daily_summary(local_date, meals, daily_titles)
        await line_client.push_text(target_id, summary_text)
        sent_count += 1

    return {"ok": True, "date": local_date, "targets": len(targets), "sent": sent_count}
