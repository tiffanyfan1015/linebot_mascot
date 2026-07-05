import json
import logging

from fastapi import FastAPI, Header, HTTPException, Request

from src.handlers.webhook_handler import handle_events
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
