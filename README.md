# LINE Bot FastAPI Starter

Python + FastAPI LINE Bot starter for Cloud Run.

## Features

- `POST /webhook` for LINE Messaging API.
- LINE `x-line-signature` validation.
- Replies when the bot joins a group.
- Echoes group text messages with the sender display name.
- Basic rule replies for `/help`, `/ping`, `早安`, and `開會`.
- `GET /healthz` for deployment checks.

## Required Environment Variables

Set these in Cloud Run. Do not commit real values to GitHub.

```env
LINE_CHANNEL_SECRET=replace-with-your-channel-secret
LINE_CHANNEL_ACCESS_TOKEN=replace-with-your-channel-access-token
PORT=8080
```

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

## Security Notes

- `.env` files are ignored.
- Keep `LINE_CHANNEL_ACCESS_TOKEN` and `LINE_CHANNEL_SECRET` only in Cloud Run environment variables or Secret Manager.
