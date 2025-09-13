from fastapi import FastAPI, Request, Header
import os, hmac, hashlib, base64
import httpx

app = FastAPI()

DEFAULT_PERSONA = "muryi"
REPLY_API_URL = "https://api.line.me/v2/bot/message/reply"

def verify_signature(body: bytes, signature: str) -> bool:
    secret = os.environ["LINE_CHANNEL_SECRET"].encode("utf-8")
    mac = hmac.new(secret, body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature or "")

def generate_reply(user_text: str, persona: str = DEFAULT_PERSONA) -> str:
    if persona == "muryi":
        return f"（ミュリィ）{user_text}、すごく良いです！ まず小さく試してみよ！ きらーん☆"
    else:
        return f"（ピオナ）いいね！ まず優先度だけ整理しよ。最初は小さくテスト！"

async def reply_message(reply_token: str, text: str):
    headers = {
        "Authorization": f"Bearer {os.environ['LINE_CHANNEL_TOKEN']}",
        "Content-Type": "application/json"
    }
    payload = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(REPLY_API_URL, headers=headers, json=payload)

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.post("/webhook")
async def webhook(request: Request, x_line_signature: str = Header(None)):
    body = await request.body()
    if not verify_signature(body, x_line_signature):
        return {"status": "signature_error"}

    data = await request.json()
    for ev in data.get("events", []):
        if ev.get("type") == "message" and ev["message"].get("type") == "text":
            text = ev["message"]["text"]
            reply = generate_reply(text, DEFAULT_PERSONA)
            await reply_message(ev["replyToken"], reply)
    return {"status": "ok"}
