import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles

from src.ai_client import AIServiceError, gemini_ai_client
from src.config import settings
from src.handlers.webhook_handler import build_backpack_dashboard_flex_message, handle_events
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

MEAL_TYPES = {"breakfast", "lunch", "dinner", "late_night"}
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
_nominatim_lock = asyncio.Lock()
_nominatim_last_request = 0.0


class LiffMealUpdate(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=500)
    meal_type: str | None = None


class LiffTimezoneUpdate(BaseModel):
    timezone: str = Field(min_length=1, max_length=64)


class LiffBackpackLocationUpdate(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    address: str = Field(min_length=1, max_length=500)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


app = FastAPI(title="LINE Bot")
app.mount("/liff", StaticFiles(directory=Path(__file__).resolve().parent / "liff", html=True), name="liff")


@app.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}


@app.get("/assets/e-bao-bao.png", include_in_schema=False)
async def target_backpack_image() -> FileResponse:
    return FileResponse(Path(__file__).resolve().parent.parent / "e-bao-bao.png", media_type="image/png")


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
    access, line_user_id = await authenticate_liff_group_request(authorization, ticket)
    if meal_type and meal_type not in MEAL_TYPES:
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
            viewer_user_id=line_user_id,
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


@app.get("/api/liff/group-backpacks")
async def liff_group_backpacks(
    ticket: str = Query(min_length=20, max_length=2048), authorization: str = Header(default=""), period: str = Query(default="month")
) -> dict:
    access, _ = await authenticate_liff_group_request(authorization, ticket)
    if period not in {"month", "all"}:
        raise HTTPException(status_code=400, detail="Invalid period")
    today = datetime.now(ZoneInfo(settings.summary_timezone)).date()
    from_date = today.replace(day=1).isoformat() if period == "month" else None
    data = meal_store.get_backpack_dashboard(target_id=access.target_id, from_date=from_date)
    return {"period": period, "from": from_date, **data}


@app.get("/api/liff/backpack-location/search")
async def search_backpack_location(
    q: str = Query(min_length=2, max_length=200), ticket: str = Query(min_length=20, max_length=2048), authorization: str = Header(default="")
) -> dict:
    await authenticate_liff_group_request(authorization, ticket)
    global _nominatim_last_request
    async with _nominatim_lock:
        delay = 1.0 - (asyncio.get_running_loop().time() - _nominatim_last_request)
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(NOMINATIM_SEARCH_URL, params={"q": q, "format": "jsonv2", "limit": 5, "countrycodes": "tw", "accept-language": "zh-TW"}, headers={"User-Agent": "LineBot-BackpackMap/1.0"})
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="Location search is unavailable") from exc
        _nominatim_last_request = asyncio.get_running_loop().time()
    results = []
    for item in response.json():
        try:
            results.append({"label": item["display_name"], "address": item["display_name"], "latitude": float(item["lat"]), "longitude": float(item["lon"])})
        except (KeyError, TypeError, ValueError):
            continue
    return {"items": results}


@app.put("/api/liff/backpack-location")
async def save_liff_backpack_location(
    update: LiffBackpackLocationUpdate, ticket: str = Query(min_length=20, max_length=2048), authorization: str = Header(default="")
) -> dict[str, bool]:
    access, line_user_id = await authenticate_liff_group_request(authorization, ticket)
    saved = meal_store.save_pending_backpack_location_picker(target_id=access.target_id, user_id=line_user_id, label=update.label, address=update.address, latitude=update.latitude, longitude=update.longitude, now=datetime.now(ZoneInfo(settings.summary_timezone)))
    if not saved:
        raise HTTPException(status_code=404, detail="No pending backpack sighting")
    if access.target_id.startswith("C"):
        try:
            await line_client.push_messages(access.target_id, [build_backpack_dashboard_flex_message(access.target_id)])
        except (httpx.HTTPError, LiffConfigurationError):
            logger.exception("Failed to push backpack dashboard after LIFF location save")
    return {"ok": True}


@app.get("/api/liff/timezone")
async def get_liff_timezone(
    ticket: str = Query(min_length=20, max_length=2048),
    authorization: str = Header(default=""),
) -> dict[str, str | bool]:
    _, line_user_id = await authenticate_liff_group_request(authorization, ticket)
    timezone, confirmed = meal_store.get_user_timezone_preference(line_user_id)
    return {"timezone": timezone, "confirmed": confirmed}


@app.put("/api/liff/timezone")
async def update_liff_timezone(
    update: LiffTimezoneUpdate,
    ticket: str = Query(min_length=20, max_length=2048),
    authorization: str = Header(default=""),
) -> dict[str, str | bool]:
    _, line_user_id = await authenticate_liff_group_request(authorization, ticket)
    timezone = update.timezone.strip()
    try:
        meal_store.save_user_timezone_preference(line_user_id, timezone)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid IANA timezone") from exc
    return {"timezone": timezone, "confirmed": True}


@app.patch("/api/liff/group-meals/{record_id}")
async def update_liff_group_meal(
    record_id: str,
    update: LiffMealUpdate,
    ticket: str = Query(min_length=20, max_length=2048),
    authorization: str = Header(default=""),
) -> dict:
    if not record_id or len(record_id) > 256 or "/" in record_id:
        raise HTTPException(status_code=400, detail="Invalid record ID")
    if update.meal_type is not None and update.meal_type not in MEAL_TYPES:
        raise HTTPException(status_code=400, detail="Invalid meal_type")
    if update.description is not None and not update.description.strip():
        raise HTTPException(status_code=400, detail="Description must not be blank")
    if update.description is None and update.meal_type is None:
        raise HTTPException(status_code=400, detail="Provide a description or meal_type")

    access, line_user_id = await authenticate_liff_group_request(authorization, ticket)
    item = meal_store.update_group_meal(
        target_id=access.target_id,
        viewer_user_id=line_user_id,
        record_id=record_id,
        description=update.description,
        meal_type=update.meal_type,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Meal record not found")
    return {"item": item}


@app.delete("/api/liff/group-meals/{record_id}")
async def delete_liff_group_meal(
    record_id: str,
    ticket: str = Query(min_length=20, max_length=2048),
    authorization: str = Header(default=""),
) -> dict[str, bool]:
    if not record_id or len(record_id) > 256 or "/" in record_id:
        raise HTTPException(status_code=400, detail="Invalid record ID")

    access, line_user_id = await authenticate_liff_group_request(authorization, ticket)
    deleted = meal_store.delete_group_meal(
        target_id=access.target_id,
        viewer_user_id=line_user_id,
        record_id=record_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Meal record not found")
    return {"ok": True}


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
    return access, line_user_id


@app.post("/jobs/daily-summary")
async def daily_summary(x_scheduler_secret: str = Header(default="")) -> dict[str, int | bool | str]:
    if not settings.scheduler_secret:
        raise HTTPException(status_code=500, detail="SCHEDULER_SECRET is not configured")
    if x_scheduler_secret != settings.scheduler_secret:
        raise HTTPException(status_code=403, detail="Invalid scheduler secret")

    local_date = get_summary_date()
    targets = meal_store.list_summary_targets()
    sent_count = 0
    failed_count = 0

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
        try:
            await line_client.push_text(target_id, summary_text)
        except httpx.HTTPStatusError as exc:
            failed_count += 1
            logger.exception(
                "Daily summary push failed: target_id=%s status=%s body=%s",
                target_id,
                exc.response.status_code,
                exc.response.text[:1000],
            )
        except httpx.HTTPError:
            failed_count += 1
            logger.exception("Daily summary push failed: target_id=%s", target_id)
        else:
            sent_count += 1

    return {
        "ok": failed_count == 0,
        "date": local_date,
        "targets": len(targets),
        "sent": sent_count,
        "failed": failed_count,
    }
