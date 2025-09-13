from fastapi import FastAPI, Request, Header
import os, hmac, hashlib, base64
import httpx
import re
import random

app = FastAPI()
random.seed()

# ==== キャラ管理（ユーザーごと切替）====
PERSONA_BY_USER = {}              # userId -> "muryi" / "piona"
DEFAULT_PERSONA = "muryi"         # 初期キャラ

def current_persona(user_id: str) -> str:
    return PERSONA_BY_USER.get(user_id, DEFAULT_PERSONA)

REPLY_API_URL = "https://api.line.me/v2/bot/message/reply"

# ==== 署名検証 ====
def verify_signature(body: bytes, signature: str) -> bool:
    secret = os.environ["LINE_CHANNEL_SECRET"].encode("utf-8")
    mac = hmac.new(secret, body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature or "")

# ==== セリフ辞書 & ルール ====
INTENT_RULES = [
    (r"^/?help|ヘルプ|使い方", "help"),
    (r"おは|こん(にち|ばん)は|やっほ|hi|hello", "greet"),
    (r"ありがと|感謝|thx", "thanks"),
    (r"未来|将来|ミライ|将来的|204|20[3-9][0-9]", "future"),
    (r"天気|天候|暑い|寒い", "smalltalk_weather"),
    (r"疲れ|しんど|つかれ", "care"),
]
PHRASES = {
    "muryi": {},
    "piona": {}
}

# ==== フリートーク用セリフ辞書 ====
DIALOGUES = {
    "muryi": [
        "ガワもコアもkawaii☆ {user_text} もそう思わない？"
    ],
    "piona": [
        "よーし！ {user_text} なら任せといて！"
    ]
}


# ==== 意図検出 & 返答 ====
def detect_intent(text: str) -> str:
    for pat, intent in INTENT_RULES:
        if re.search(pat, text, flags=re.IGNORECASE):
            return intent
    return "generic"

def pick(persona: str, intent: str, q: str) -> str:
    bucket = PHRASES.get(persona, {}).get(intent)
    if not bucket:
        bucket = PHRASES.get(persona, {}).get("generic", ["{q}"])
    return random.choice(bucket).format(q=q)

def generate_reply(user_text: str, persona: str) -> str:
    intent = detect_intent(user_text)
    return pick(persona, intent, user_text)

# ==== LINE返信 ====
async def reply_message(reply_token: str, text: str):
    headers = {
        "Authorization": f"Bearer {os.environ['LINE_CHANNEL_TOKEN']}",
        "Content-Type": "application/json"
    }
    payload = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(REPLY_API_URL, headers=headers, json=payload)

# ==== ヘルスチェック ====
@app.get("/healthz")
def healthz():
    return {"ok": True}

# ==== Webhook ====
@app.post("/webhook")
async def webhook(request: Request, x_line_signature: str = Header(None)):
    body = await request.body()
    if not verify_signature(body, x_line_signature):
        return {"status": "signature_error"}

    data = await request.json()
    for ev in data.get("events", []):
        if ev.get("type") == "message" and ev["message"].get("type") == "text":
            text = ev["message"]["text"].strip()
            user_id = ev.get("source", {}).get("userId", "unknown")

            # --- コマンド（表記ゆれに少し強く）---
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

