from fastapi import FastAPI, Request, Header
import os, hmac, hashlib, base64
import httpx

app = FastAPI()

# ---- キャラ管理（ユーザーごと切替）----
PERSONA_BY_USER = {}              # userId -> "muryi" / "piona"
DEFAULT_PERSONA = "muryi"         # 初期キャラ

def current_persona(user_id: str) -> str:
    return PERSONA_BY_USER.get(user_id, DEFAULT_PERSONA)

REPLY_API_URL = "https://api.line.me/v2/bot/message/reply"

# ---- 署名検証 ----
def verify_signature(body: bytes, signature: str) -> bool:
    secret = os.environ["LINE_CHANNEL_SECRET"].encode("utf-8")
    mac = hmac.new(secret, body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature or "")

# ---- 返答生成（最小キャラ分岐）----
def generate_reply(user_text: str, persona: str) -> str:
    if persona == "muryi":
        return f"（ミュリィ）{user_text}、すごく良いです！ まず小さく試してみよ！ きらーん☆"
    else:
        return f"（ピオナ）いいね！ まず優先度だけ整理しよ。最初は小さくテスト！"

# ---- LINE返信 ----
async def reply_message(reply_token: str, text: str):
    headers = {
        "Authorization": f"Bearer {os.environ['LINE_CHANNEL_TOKEN']}",
        "Content-Type": "application/json"
    }
    payload = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(REPLY_API_URL, headers=headers, json=payload)

# ---- ヘルスチェック ----
@app.get("/healthz")
def healthz():
    return {"ok": True}

# ---- Webhook ----
@app.post("/webhook")
async def webhook(request: Request, x_line_signature: str = Header(None)):
    body = await request.body()
    if not verify_signature(body, x_line_signature):
        # 署名NGでも200を返すとLINE側の再試行が止まらないことがあるので、ここは200以外は返さない実装でもOK
        return {"status": "signature_error"}

    data = await request.json()

    for ev in data.get("events", []):
        if ev.get("type") == "message" and ev["message"].get("type") == "text":
            text = ev["message"]["text"].strip()
            user_id = ev.get("source", {}).get("userId", "unknown")

            # --- コマンド（ゆるめ判定）---
            low = text.lower().replace("：", ":").replace("　", " ").strip()
            if low in ("/set piona", "set:piona", "/piona"):
                PERSONA_BY_USER[user_id] = "piona"
                await reply_message(ev["replyToken"], "（システム）ピオナに切り替えたよ！")
                continue
            if low in ("/set muryi", "set:muryi", "/muryi"):
                PERSONA_BY_USER[user_id] = "muryi"
                await reply_message(ev["replyToken"], "（システム）ミュリィに切り替えたよ！")
                continue
            if low in ("/who", "who?"):
                who = current_persona(user_id)
                jp = "ミュリィ" if who == "muryi" else "ピオナ"
                await reply_message(ev["replyToken"], f"（システム）現在は {jp} です")
                continue

            # --- 通常返信 ---
            persona = current_persona(user_id)
            reply = generate_reply(text, persona)
            await reply_message(ev["replyToken"], reply)

    return {"status": "ok"}
