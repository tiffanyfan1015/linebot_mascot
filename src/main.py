import json
import logging

from fastapi import FastAPI, Header, HTTPException, Request

from src.ai_client import AIServiceError, gemini_ai_client
from src.config import settings
from src.handlers.webhook_handler import handle_events
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
