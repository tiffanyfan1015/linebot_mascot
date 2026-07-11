import json
import logging

from fastapi import FastAPI, Header, HTTPException, Request

from src.config import settings
from src.handlers.webhook_handler import handle_events
from src.line_client import line_client
from src.meal_store import meal_store
from src.summary import build_daily_summary, get_summary_date
from src.security import verify_line_signature


logging.basicConfig(level=logging.INFO)

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
        summary_text = build_daily_summary(local_date, meals)
        await line_client.push_text(target_id, summary_text)
        sent_count += 1

    return {"ok": True, "date": local_date, "targets": len(targets), "sent": sent_count}
