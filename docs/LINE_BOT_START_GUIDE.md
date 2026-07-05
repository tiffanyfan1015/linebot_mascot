# LINE 聊天機器人建立入門規劃

更新日期：2026-07-05

這份文件以 Python + FastAPI 為主，目標是建立一個可以被加入 LINE 群組的 Bot。第一階段先做到：接收群組訊息、取得使用者名稱、回覆使用者剛剛說的話。第二階段再加入自動回覆規則。

## 目標功能

第一階段：

- 建立 LINE Official Account 與 Messaging API channel。
- 讓 Bot 可以被邀請進 LINE 群組。
- 部署 FastAPI webhook server 到雲端。
- 使用自己的 Cloudflare domain 設定 webhook URL。
- 接收 LINE webhook 事件。
- 從事件取得 `userId`、`groupId`、訊息文字。
- 透過 LINE API 查詢使用者顯示名稱。
- 使用 `replyToken` 回覆訊息，例如：「王小明 說：你好」。

第二階段：

- 加入自動回覆規則，例如 `/help`、`/ping`、關鍵字回覆。
- 後續可再接 LLM 或資料庫，讓 Bot 回覆更自然。

## 架構總覽

建議架構：

```text
LINE 使用者群組
  -> LINE Platform
  -> https://linebot.your-domain.com/webhook
  -> Cloudflare DNS
  -> 雲端 FastAPI server
  -> LINE Reply API
  -> 回覆到 LINE 群組
```

Webhook URL 的本質是一個公開 HTTPS endpoint。Cloudflare domain 只負責把 `linebot.your-domain.com` 指到你的雲端服務；真正處理訊息的是雲端上的 FastAPI 程式。

## 雲端部署選項

### 免費或低成本選項

以下選項適合初期測試：

- Google Cloud Run：有免費額度，適合 webhook 這種低流量服務。
- Render Free / Hobby 類方案：依當前方案限制，可能會休眠或需要綁卡。
- Railway：常見於小專案，但免費額度與政策可能變動。
- Fly.io：可跑小型服務，但免費額度與政策可能變動。

如果你已經有 Google 帳號，且願意設定 billing，建議優先選 Google Cloud Run。它很適合 LINE Bot，因為 webhook 通常不是長時間大量流量，Cloud Run 可以在沒有流量時縮到 0。

### Google Cloud Run 會需要錢嗎？

簡短答案：可能不用付錢，但通常需要啟用帳單。

Cloud Run 官方計費方式是依實際用量收費，並套用每月免費額度。官方文件列出的 request-based billing 免費額度包含每月一定量的 CPU、記憶體與 request 數；其中 requests 免費額度是每月 200 萬次。小型 LINE Bot 通常很難超過這個量。

但要注意：

- Cloud Run 是 pay-per-use，不是「永久完全免費」。
- 大多數 Google Cloud 服務需要綁定 Billing Account 才能部署。
- 如果流量暴增、設定了 minimum instances、使用外部網路大量傳輸，仍可能產生費用。
- 建議設定 Budget alert，例如每月 1 美元或 5 美元通知。
- 開發初期建議 `min-instances=0`，避免沒有流量時仍保留常駐實例。

建議初期 Cloud Run 設定：

```text
Region: asia-east1 或 asia-northeast1
CPU: 1
Memory: 512Mi
Min instances: 0
Max instances: 1 或 3
Allow unauthenticated invocations: yes
```

LINE webhook 必須讓 LINE Platform 可以公開呼叫，所以 Cloud Run service 要允許 unauthenticated invocations。安全性由 LINE 的 `x-line-signature` 驗證來處理。

## 除了 Cloud Run 以外的部署方式

LINE Bot 的 webhook server 只需要符合幾個條件：

- 有公開 HTTPS URL。
- 可以接收 `POST /webhook`。
- 可以穩定連到 LINE API。
- 可以設定環境變數或 secrets。
- 可以查看 logs，方便 debug。

因此不一定要用 Google Cloud Run。以下是常見選項。

### Render

適合：想要最少雲端基礎設施設定，直接從 GitHub 部署 FastAPI。

優點：

- 有 FastAPI 官方部署教學。
- 可以直接連 GitHub repo 自動部署。
- 會提供 HTTPS domain。
- 設定環境變數容易。

注意：

- 免費或低價方案可能會休眠，第一個請求會比較慢。
- 方案與免費額度可能調整，建立前要看最新 pricing。

Webhook URL 範例：

```text
https://your-linebot.onrender.com/webhook
```

### Railway

適合：想快速部署 Python app，並且希望設定流程簡單。

優點：

- 有 FastAPI 部署 guide。
- 可以從 GitHub 部署。
- 會提供公開 HTTPS domain。
- 適合小型 side project。

注意：

- 免費額度、trial、計費規則可能變動。
- 正式使用前要設定 spending limit 或預算控管。

Webhook URL 範例：

```text
https://your-linebot.up.railway.app/webhook
```

### Fly.io

適合：想用 Docker 部署，且希望更接近正式服務環境。

優點：

- 支援 Docker。
- 可以選擇部署區域。
- 適合需要長期跑的小服務。

注意：

- 設定比 Render / Railway 稍微偏工程化。
- 免費額度與計費規則可能變動。

### 自己的 VPS

適合：你已經有 Linux server，或想完整控制部署環境。

優點：

- 可控性最高。
- 可以搭配 Nginx、systemd、Docker Compose。
- 長期固定服務可能成本可預期。

注意：

- 需要自己處理 HTTPS 憑證、反向代理、防火牆、更新與監控。
- 對初期 LINE Bot 來說維運成本偏高。

### 本機加 Tunnel

適合：開發測試，不適合正式服務。

選項：

- Cloudflare Tunnel：適合你已經有 Cloudflare domain。
- ngrok：適合快速產生臨時 HTTPS URL。

這種方式可以讓 LINE Platform 呼叫你本機的 FastAPI server，但前提是你的電腦要開著，tunnel process 也要持續執行。

## 一定要部署才可以用嗎？

分成兩種情境。

本機功能測試：不一定要部署。

你可以直接在本機跑 FastAPI，測試：

- `/docs` 是否能打開。
- `/webhook` 是否能接收 request。
- signature validation 是否正常。
- event handler 是否能處理假資料。
- reply rule 是否符合預期。

但這種測試只有你的電腦能打到，例如：

```text
http://localhost:8080/webhook
```

LINE Platform 無法直接呼叫你的 localhost，所以不能直接拿 localhost 當 LINE webhook URL。

LINE 真實群組互動：需要公開 HTTPS URL。

要讓 LINE 群組裡的訊息真的打到你的 Bot，你需要其中一種方式：

- 正式部署到雲端，例如 Cloud Run、Render、Railway、Fly.io、VPS。
- 本機開發時用 ngrok 或 Cloudflare Tunnel 暫時公開 localhost。

因此更精確地說：不一定要正式部署到雲端，但一定要有一個 LINE 能連到的 HTTPS webhook URL。

## 本機測試方式

### 1. 只測 FastAPI 是否正常啟動

在本機啟動：

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload
```

打開：

```text
http://localhost:8080/docs
```

如果看到 FastAPI Swagger UI，代表 app 啟動成功。

### 2. 測試 webhook endpoint 有沒有回應

如果程式還沒有啟用 signature validation，可以先用 curl 測：

```bash
curl -X POST http://localhost:8080/webhook \
  -H "Content-Type: application/json" \
  -d '{"events":[]}'
```

預期回應：

```json
{"ok": true}
```

如果已經啟用 LINE signature validation，直接 curl 通常會失敗，因為缺少正確的 `x-line-signature`。這時候可以：

- 寫單元測試產生正確 signature。
- 暫時提供一個只在本機開啟的 `/healthz` endpoint。
- 用 tunnel 接 LINE 真實 webhook 來測。

### 3. 用 ngrok 暫時公開 localhost

先啟動 FastAPI：

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload
```

再啟動 ngrok：

```bash
ngrok http 8080
```

ngrok 會給你一個 HTTPS URL，例如：

```text
https://abc123.ngrok-free.app
```

LINE webhook URL 填：

```text
https://abc123.ngrok-free.app/webhook
```

注意：免費 ngrok URL 可能會變，每次重開 tunnel 後可能需要回 LINE Developers Console 更新 webhook URL。

### 4. 用 Cloudflare Tunnel 暫時公開 localhost

如果你已經有 Cloudflare domain，可以用 Cloudflare Tunnel 把本機服務對外公開。

概念：

```text
https://linebot.example.com -> Cloudflare Tunnel -> http://localhost:8080
```

常見流程：

1. 安裝 `cloudflared`。
2. 登入 Cloudflare 帳號。
3. 建立 tunnel。
4. 設定 public hostname，例如 `linebot.example.com`。
5. 指向本機服務 `http://localhost:8080`。
6. 在 LINE Developers Console 填 `https://linebot.example.com/webhook`。

優點：

- 可以使用自己的 domain。
- URL 可以比 ngrok 穩定。
- 很適合開發階段測 LINE webhook。

注意：

- 本機電腦關機後 Bot 就不能用。
- `cloudflared` process 停掉後 webhook 就打不進來。
- 不建議把本機 tunnel 當正式長期服務。

## 建議選擇

初期學習與開發：

```text
FastAPI 本機 + ngrok 或 Cloudflare Tunnel
```

原因是最快、不需要先處理雲端部署，也能讓 LINE webhook 真正打進來。

準備給朋友或小群組長期使用：

```text
Cloud Run / Render / Railway
```

原因是電腦不用一直開著，服務比較穩定。

想要正式維運與完整控制：

```text
Cloud Run / Fly.io / VPS
```

原因是可控性、擴充性與監控能力比較好。
## LINE 官方平台設定步驟

### 1. 建立 LINE Official Account

Messaging API 需要透過 LINE Official Account 啟用。流程是先建立 LINE Official Account，再為該帳號啟用 Messaging API。

入口：

- LINE Official Account Manager: https://manager.line.biz/
- LINE Developers Console: https://developers.line.biz/console/

### 2. 啟用 Messaging API

在 LINE Official Account Manager 中啟用 Messaging API。啟用後會建立對應的 Messaging API channel，接著到 LINE Developers Console 查看該 channel。

需要記下：

- Channel secret：用來驗證 Webhook 簽章。
- Channel access token：用來呼叫 Messaging API 回覆或推播訊息。

建議先用 long-lived channel access token 做開發測試，正式環境再評估官方推薦的 token 管理方式。

### 3. 允許 Bot 加入群組

預設 Bot 不能被邀請到群組，需要手動開啟。

設定位置：

```text
LINE Developers Console
-> Provider
-> Messaging API channel
-> Messaging API tab
-> Allow bot to join group chats
```

限制：

- 一個群組同時間只能加入一個 LINE Official Account。
- 舊的 multi-person chat 仍可能存在，但新版多人聊天室大多已併入群組概念。

### 4. 關閉預設自動回覆避免干擾

LINE Official Account Manager 預設可能啟用 Greeting messages 或 Auto-reply messages。開發第一版 Bot 時，建議先關閉這些設定，避免分不清楚回覆是官方帳號自動產生，還是你的程式產生。

設定位置：

```text
LINE Official Account Manager
-> 回應設定或 Messaging API Settings
-> 關閉 Greeting messages / Auto-reply messages
```

## FastAPI 專案設計

### 建議專案結構

```text
LineBot/
  docs/
    LINE_BOT_START_GUIDE.md
  src/
    main.py
    line_client.py
    handlers/
      webhook_handler.py
      reply_rules.py
  requirements.txt
  .env
  .env.example
  Dockerfile
```

職責拆分：

- `src/main.py`：啟動 FastAPI app，提供 `/webhook`。
- `src/line_client.py`：封裝 LINE API 呼叫，例如 reply、get profile。
- `src/handlers/webhook_handler.py`：解析與分派 LINE events。
- `src/handlers/reply_rules.py`：自動回覆規則。

### 環境變數

後端服務至少需要：

```env
LINE_CHANNEL_SECRET=你的 Channel secret
LINE_CHANNEL_ACCESS_TOKEN=你的 Channel access token
PORT=8080
```

不要把 token 寫死在程式碼或提交到 Git。Cloud Run 上應該用 environment variables 或 Secret Manager 管理。

### Webhook endpoint

服務需要提供一個 `POST /webhook` endpoint：

```text
POST /webhook
```

收到 LINE webhook 後要做：

1. 讀取原始 request body。
2. 驗證 `x-line-signature`，確認請求真的來自 LINE。
3. 解析 body 裡的 `events`。
4. 只處理需要的事件類型，例如 `message`、`join`。
5. 對文字訊息呼叫 Reply API 回覆。
6. 回傳 HTTP 200，避免 LINE 重送 webhook。

### FastAPI 最小 webhook 範例

正式版需要拆檔與補完整錯誤處理，最小測試可以先像這樣：

```python
import os
import hmac
import json
import base64
import hashlib
import httpx
from fastapi import FastAPI, Request, Header, HTTPException

app = FastAPI()

LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]


def verify_signature(body: bytes, signature: str) -> bool:
    digest = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


async def reply_text(reply_token: str, text: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            "https://api.line.me/v2/bot/message/reply",
            headers={
                "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "replyToken": reply_token,
                "messages": [{"type": "text", "text": text}],
            },
        )
        response.raise_for_status()


async def get_group_member_profile(group_id: str, user_id: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"https://api.line.me/v2/bot/group/{group_id}/member/{user_id}",
            headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
        )
        response.raise_for_status()
        return response.json()


@app.post("/webhook")
async def webhook(
    request: Request,
    x_line_signature: str = Header(default=""),
):
    body = await request.body()

    if not verify_signature(body, x_line_signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = json.loads(body.decode("utf-8"))

    for event in payload.get("events", []):
        if event.get("type") == "join":
            await reply_text(event["replyToken"], "大家好，我是 LINE Bot。")
            continue

        if event.get("type") != "message":
            continue

        message = event.get("message", {})
        if message.get("type") != "text":
            continue

        source = event.get("source", {})
        text = message.get("text", "")
        display_name = "有人"

        if source.get("type") == "group" and source.get("groupId") and source.get("userId"):
            profile = await get_group_member_profile(source["groupId"], source["userId"])
            display_name = profile.get("displayName", display_name)

        await reply_text(event["replyToken"], f"{display_name} 說：{text}")

    return {"ok": True}
```

`requirements.txt` 最小內容：

```text
fastapi
uvicorn[standard]
httpx
```

本機啟動：

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8080
```

## Cloud Run 部署設計

### Dockerfile

Cloud Run 可以部署 container。FastAPI 的基本 Dockerfile：

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

ENV PORT=8080

CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT}"]
```

### 部署到 Cloud Run 的流程

概念流程：

1. 建立 Google Cloud project。
2. 啟用 Billing Account。
3. 啟用 Cloud Run API 與 Artifact Registry API。
4. 建立 FastAPI 專案與 Dockerfile。
5. 使用 Google Cloud CLI 或 GitHub Actions 部署到 Cloud Run。
6. 設定環境變數 `LINE_CHANNEL_SECRET` 與 `LINE_CHANNEL_ACCESS_TOKEN`。
7. 允許 unauthenticated invocations。
8. 取得 Cloud Run 預設 URL。

部署後 Cloud Run 會給一個網址，例如：

```text
https://linebot-xxxxx-uc.a.run.app
```

這時候你的 LINE webhook URL 可以先直接填：

```text
https://linebot-xxxxx-uc.a.run.app/webhook
```

等驗證成功後，再改成自己的 Cloudflare 子網域。

## 使用 Cloudflare domain 設定 webhook URL

假設你的 domain 是：

```text
example.com
```

建議建立子網域：

```text
linebot.example.com
```

最後 webhook URL 會是：

```text
https://linebot.example.com/webhook
```

### Cloudflare DNS 設定

如果你使用 Cloud Run，常見做法有兩種。

第一種：先不綁自訂網域，直接用 Cloud Run 預設 URL。

```text
https://linebot-xxxxx-uc.a.run.app/webhook
```

這是最快驗證 LINE webhook 的方式。

第二種：把自訂網域對應到 Cloud Run。

Cloud Run 支援自訂網域對應，但設定會涉及 Google Cloud 的 domain mapping 或 load balancer。實務上建議分兩階段：

1. 先用 Cloud Run 預設 URL 完成 LINE webhook 驗證。
2. 再處理 `linebot.example.com` 自訂網域。

如果是一般雲端平台給你一個固定 domain，例如 Render：

```text
my-linebot.onrender.com
```

可以在 Cloudflare DNS 新增：

```text
Type: CNAME
Name: linebot
Target: my-linebot.onrender.com
Proxy status: Proxied 或 DNS only
```

如果是自己的 VPS 並有固定 IP：

```text
Type: A
Name: linebot
IPv4 address: 你的伺服器 IP
Proxy status: Proxied
```

Cloudflare SSL/TLS 建議：

```text
SSL/TLS mode: Full (strict)
```

前提是 origin server 也要有有效 TLS 憑證。Cloud Run、Render、Railway 這類平台通常會自動提供 HTTPS。

### LINE Developers Console 設定 webhook URL

設定位置：

```text
LINE Developers Console
-> Provider
-> Messaging API channel
-> Messaging API tab
-> Webhook settings
-> Webhook URL
```

填入：

```text
https://linebot.example.com/webhook
```

或先用 Cloud Run 預設 URL：

```text
https://linebot-xxxxx-uc.a.run.app/webhook
```

接著：

```text
Use webhook: Enabled
Verify: 點下去測試
```

Verify 成功代表 LINE 可以打到你的 `/webhook` endpoint，且你的 server 有回 HTTP 200。

注意：如果你的程式已經啟用 signature 驗證，LINE Console 的 Verify 也必須帶正確簽章才會通過。若驗證失敗，要檢查：

- Cloud Run service 是否允許 unauthenticated invocations。
- URL 是否包含 `/webhook`。
- FastAPI 是否真的監聽 Cloud Run 提供的 `PORT`。
- Channel secret 是否正確。
- Cloud Run logs 是否有錯誤。
- Cloudflare DNS 是否已生效。

## 事件處理邏輯

第一階段需要處理：

```text
event.type === "join"
```

Bot 被邀請進群組時收到，可回覆：

```text
大家好，我是 LINE Bot。請傳文字訊息給我測試。
```

```text
event.type === "message"
event.message.type === "text"
event.source.type === "group"
```

群組內使用者傳文字時收到。事件裡通常會有：

- `event.source.groupId`：群組 ID。
- `event.source.userId`：發話者 user ID。
- `event.message.text`：使用者說的文字。
- `event.replyToken`：回覆本次訊息要用的 token。

## 取得使用者名字

在群組中，如果要取得發話者顯示名稱，使用：

```text
GET /v2/bot/group/{groupId}/member/{userId}
```

如果是一對一聊天，則使用：

```text
GET /v2/bot/profile/{userId}
```

實作時建議依 `event.source.type` 分流：

- `user`：使用 user profile endpoint。
- `group`：使用 group member profile endpoint。
- `room`：使用 room member profile endpoint，主要處理舊 multi-person chat。

## 第二階段：自動回覆設計

先從 deterministic rules 開始，不要一開始就接大型語言模型，這樣比較容易測試與除錯。

### 指令型回覆

範例規則：

```text
/help
```

回覆：

```text
可用指令：
/help 顯示說明
/ping 測試機器人是否在線
```

```text
/ping
```

回覆：

```text
pong
```

### 關鍵字回覆

範例：

- 使用者訊息包含「早安」：回覆「早安，今天也請多指教。」
- 使用者訊息包含「開會」：回覆「需要我幫你整理會議提醒規則嗎？」
- 使用者訊息包含「help」：回覆說明文字。

### 回覆策略

群組機器人如果每句話都回覆，容易造成干擾。第二階段建議改成：

- 只有被 mention 時回覆。
- 只有訊息以 `/` 開頭時回覆。
- 只有命中特定關鍵字時回覆。
- 或限制冷卻時間，例如同一群組 10 秒內最多回覆一次。

## MVP 開發順序

1. 建立 LINE Official Account 並啟用 Messaging API。
2. 取得 Channel secret 與 Channel access token。
3. 建立 Python + FastAPI webhook server。
4. 本機測試 `POST /webhook` 可以回 HTTP 200。
5. 加入 LINE signature validation。
6. 建立 Dockerfile。
7. 部署到 Cloud Run。
8. 設定 Cloud Run 環境變數。
9. 用 Cloud Run 預設 URL 設定 LINE webhook。
10. 在 LINE Developers Console 開啟 Use webhook 並 Verify。
11. 啟用 Allow bot to join group chats。
12. 處理 `join` event，Bot 加入群組時回覆歡迎訊息。
13. 處理文字 `message` event，先 echo 使用者訊息。
14. 加入取得使用者 displayName 的 API 呼叫。
15. 回覆 `{displayName} 說：{messageText}`。
16. 加入 `/help`、`/ping` 等基本自動回覆規則。
17. 視需要把 Cloud Run 預設 URL 換成 Cloudflare 自訂子網域。

## 驗收清單

第一階段完成條件：

- FastAPI app 可以在本機啟動。
- Cloud Run service 可以公開存取。
- LINE Developers Console 的 Webhook Verify 成功。
- Bot 可以被加入群組。
- Bot 加入群組時會發歡迎訊息。
- 群組成員傳文字時，Bot 能收到 webhook。
- Bot 能取得發話者 displayName。
- Bot 會回覆「某某 說：原訊息」。
- Webhook 有驗證 LINE signature。
- Token 存在環境變數，不在 Git 裡。
- Cloud Run 設定 budget alert，避免意外費用。

第二階段完成條件：

- `/help` 可以回覆說明。
- `/ping` 可以回覆 `pong`。
- 至少有 2 到 3 個關鍵字回覆。
- 群組中不會每句話都無限制回覆。
- 有基本錯誤 log，方便查問題。

## 常見風險

- Webhook URL 不是 HTTPS，LINE Verify 會失敗。
- URL 忘記加 `/webhook`。
- Cloud Run 沒有允許 unauthenticated invocations，LINE 無法呼叫。
- FastAPI 沒有監聽 Cloud Run 指定的 `PORT`。
- Channel secret 設錯，signature validation 會失敗。
- 忘記開啟 Use webhook，Bot 不會收到事件。
- 忘記開啟 Allow bot to join group chats，Bot 不能加入群組。
- 官方帳號預設 Auto-reply 還開著，導致回覆混在一起。
- 在群組每句話都回覆，容易造成洗版。
- 沒設定 Google Cloud budget alert，流量異常時可能產生費用。

## 官方參考文件

- LINE Get started with the Messaging API: https://developers.line.biz/en/docs/messaging-api/getting-started/
- LINE Build a bot: https://developers.line.biz/en/docs/messaging-api/building-bot/
- LINE Receive messages webhook: https://developers.line.biz/en/docs/messaging-api/receiving-messages/
- LINE Group chats and multi-person chats: https://developers.line.biz/en/docs/messaging-api/group-chats/
- LINE Messaging API reference: https://developers.line.biz/en/reference/messaging-api/
- Google Cloud Run pricing: https://cloud.google.com/run/pricing
- Google Cloud free program: https://cloud.google.com/free/docs/free-cloud-features
- Cloudflare DNS records: https://developers.cloudflare.com/dns/manage-dns-records/how-to/create-dns-records/
- Cloudflare Full strict SSL mode: https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/
- Cloudflare Tunnel local tunnel: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/create-local-tunnel/
- ngrok getting started: https://ngrok.com/docs/getting-started/
- Render deploy FastAPI: https://render.com/docs/deploy-fastapi
- Railway deploy FastAPI: https://docs.railway.com/guides/fastapi


