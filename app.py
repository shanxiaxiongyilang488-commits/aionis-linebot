from fastapi import FastAPI, Request, Header
import os, hmac, hashlib, base64
import httpx

# 先頭のimports等はそのまま。下の2行をグローバルに追加
PERSONA_BY_USER = {}                     # userId -> "muryi" / "piona"
DEFAULT_PERSONA = "muryi"                # 既存のままでもOK（初期値）

def current_persona(user_id: str) -> str:
    return PERSONA_BY_USER.get(user_id, DEFAULT_PERSONA)


app = FastAPI()


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
        user_id = ev["source"]["userId"]   # 誰が送ったか取得

        # コマンド処理
        if text.lower() == "/set muryi":
            PERSONA_BY_USER[user_id] = "muryi"
            reply = "✅ キャラをミュリィに切り替えたよ！"
        elif text.lower() == "/set piona":
            PERSONA_BY_USER[user_id。] = "piona"
            reply = "✅ キャラをピオナに切り替えたよ！"
        else:
            persona = current_persona(user_id)
            reply = generate_reply(text, persona)

        await reply_message(ev["replyToken"], reply)
