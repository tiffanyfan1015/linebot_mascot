# LINE Bot FastAPI Starter

Python + FastAPI LINE Bot starter for Cloud Run.

## Features

- `POST /webhook` for LINE Messaging API.
- LINE `x-line-signature` validation.
- Replies when the bot joins a group.
- Rule replies for `/help`, `/ping`, `早安`, and `開會`.
- Image meal replies based on Taiwan time.
- Stores food image logs, including AI-estimated serving, calories, and macronutrients, in Firestore. Photo-based nutrition estimates are for reference only.
- `POST /jobs/daily-summary` for scheduled LINE group meal summaries, with AI-generated daily titles and deterministic fallbacks.
- `/飲食紀錄` returns a persistent Flex Message button; `GET /api/liff/group-meals` verifies the signed group link, LIFF identity, and current group membership.
- `/liff/` provides a mobile-first today and calendar history UI, with mock preview data until LIFF is configured.
- Gemini AI replies when the bot is mentioned or when a message starts with `/ask`.
- `GET /healthz` for deployment checks.

## Required Environment Variables

Set these in Cloud Run. Do not commit real values to GitHub.

```env
LINE_CHANNEL_SECRET=replace-with-your-channel-secret
LINE_CHANNEL_ACCESS_TOKEN=replace-with-your-channel-access-token
PORT=8080
GOOGLE_CLOUD_PROJECT=replace-with-your-gcp-project-id
SCHEDULER_SECRET=replace-with-a-random-secret
SUMMARY_TIMEZONE=Asia/Taipei
LIFF_ID=replace-after-creating-your-liff-app
LINE_LOGIN_CHANNEL_ID=replace-after-creating-your-line-login-channel
LIFF_TICKET_SECRET=replace-with-at-least-32-random-characters
```

## Optional AI Environment Variables

```env
GEMINI_API_KEY=replace-with-your-gemini-api-key
LINE_BOT_USER_ID=replace-with-your-line-bot-user-id
GEMINI_MODEL=gemini-3.1-flash-lite
```

`LINE_BOT_USER_ID` is used to detect when users mention the bot in a group.
If `GEMINI_API_KEY` is not set, the AI feature stays disabled and the rest of the bot still works.

## Local Development

Create a virtual environment and install dependencies:

```bash
python -m venv .venv
pip install -r requirements.txt
```

Set environment variables, then run:

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload
```

Health check:

```text
http://localhost:8080/healthz
```

## Cloud Run Deployment

Use:

```text
Cloud Run -> Deploy service -> Continuously deploy from a repository
```

Recommended settings:

```text
Service name: linebot
Region: asia-east1 or asia-northeast1
Authentication: Allow unauthenticated invocations
Port: 8080
Minimum instances: 0
Maximum instances: 1 or 3
Build type: Dockerfile
```

After deployment, Cloud Run gives a service URL like:

```text
https://linebot-xxxxx.a.run.app
```

Set LINE webhook URL to:

```text
https://linebot-xxxxx.a.run.app/webhook
```

Then enable `Use webhook` and click `Verify` in LINE Developers Console.


## LIFF Group History Backend

The UI is served at `/liff/`. Before a LIFF app is configured it displays local preview data; after configuration it initializes LIFF and reads authenticated group data from the API.

After creating the LIFF app, set `LIFF_ID`, `LINE_LOGIN_CHANNEL_ID`, and a random `LIFF_TICKET_SECRET` of at least 32 characters. Members run `/飲食紀錄` inside a group to receive a persistent Flex Message button. The server verifies that the signed-in LINE user is still a member of that group each time the link is opened.

The future LIFF page should send its LINE ID token as a bearer token:

```text
GET /api/liff/group-meals?ticket=<ticket>&from=2026-07-01&to=2026-07-31&meal_type=lunch&member=<member_key>&limit=50&cursor=<cursor>
Authorization: Bearer <LINE ID token>
```

The API derives the group from the signed ticket and never accepts a group ID from the client. Create this Firestore composite index for history queries:

```text
meal_logs: target_id ASC, local_date DESC, local_time DESC
```

## Security Notes

- `.env` files are ignored.
- Keep secrets only in Cloud Run environment variables or Secret Manager.
- Do not expose `GEMINI_API_KEY` in client-side code.

## Daily Summary Scheduler

Create a Cloud Scheduler HTTP job to call:

```text
POST https://<your-cloud-run-url>/jobs/daily-summary
Header: x-scheduler-secret: <SCHEDULER_SECRET>
Timezone: Asia/Taipei
Schedule example: 30 22 * * *
```

The job reads enabled `chat_targets` from Firestore, queries that target's `meal_logs` for the current local date, and sends the summary with LINE push messages.
