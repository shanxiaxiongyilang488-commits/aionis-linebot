
# app.py --- Phase1 Known-Good (最小安定板)
import os, yaml, logging

CHAR_FILE = os.getenv("CHARACTER_FILE", "personas/muryi.yaml")
PERSONA = {}

def load_persona(path: str):
    global PERSONA
    try:
        with open(path, "r", encoding="utf-8") as f:
            PERSONA = yaml.safe_load(f)
        logging.info(f"[BOOT] Loaded persona: {path}")
    except Exception as e:
        logging.exception(f"[BOOT] Failed to load persona: {path} -> {e}")
        PERSONA = {"name": "muryi", "style": "fallback"}  # 最低限のデフォルト

# アプリ起動時に 1 回だけ実行
load_persona(CHAR_FILE)



from fastapi import FastAPI, Request, Header
import os, hmac, hashlib, base64, httpx, re, random

app = FastAPI()

# ====== 設定 ======
REPLY_API_URL = "https://api.line.me/v2/bot/message/reply"
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
CHANNEL_TOKEN  = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")

# ====== 状態 ======
DEBUG_BY_USER = set()             # /debug on/off
PERSONA_BY_USER = {}              # userId -> "muryi" | "piona"
DEFAULT_PERSONA = "muryi"

def current_persona(user_id: str) -> str:
    return PERSONA_BY_USER.get(user_id, DEFAULT_PERSONA)

# ====== 署名検証 ======
def verify_signature(body: bytes, signature: str) -> bool:
    mac = hmac.new(CHANNEL_SECRET.encode("utf-8"), body, hashlib.sha256).digest()
    expect = base64.b64encode(mac).decode("utf-8")
    ok = hmac.compare_digest(expect, signature or "")
    if not ok:
        print("[SIG] NG expected=", expect, " got=", signature)
    return ok

# ====== 返信API ======
async def reply_message(reply_token: str, text: str):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CHANNEL_TOKEN}",
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(REPLY_API_URL, headers=headers, json=payload)
        print("[LINE] status=", r.status_code, "body=", r.text)
        r.raise_for_status()

# ====== 意図(最小) ======
def detect_intent(t: str) -> str:
    tl = t.lower()
    if re.search(r"(おはよう|こんにちは|こんちゃ|やっほー|hi|hello)", t):
        return "greet"
    if re.search(r"(むかつ|ムカつ|怒|ぷんぷん)", t):
        return "angry"
    if re.search(r"(ありがと|thanks|thx)", t):
        return "thanks"
    return "generic"

# ====== 返答(最小) ======
def generate_reply(text: str, persona: str, intent: str) -> str:
    # デバッグ中は意図タグを前置
    head = f"[{persona} | {intent}] " if persona else ""
    # ほんの少しだけキャラ差分
    if persona == "piona":
        tail = {
            "greet": "こんにちは、ピオナだよ！",
            "angry": "ピオナ、ちょっとむっとしてる…",
            "thanks": "手伝ってくれて感謝！",
            "generic": "うん、了解だよ。",
        }[intent]
    else:
        tail = {
            "greet": "こんちは、ミュリィだよ〜☆",
            "angry": "ぷんぷん！ミュリィ怒ったもん！",
            "thanks": "ありがとっ☆",
            "generic": "聞いてるよ！",
        }[intent]
    return head + tail

# ====== Webhook ======
@app.post("/webhook")
async def webhook(request: Request, x_line_signature: str = Header(None)):
    body = await request.body()
    print("[WH] raw_len=", len(body))
    if not verify_signature(body, x_line_signature):
        return {"status": "signature_error"}

    data = await request.json()
    events = data.get("events", [])
    print("[WH] events=", len(events))

    for ev in events:
        print("[EV] type=", ev.get("type"))
        if ev.get("type") != "message":
            continue
        if ev["message"].get("type") != "text":
            continue

        text = ev["message"].get("text", "")
        user_id = ev.get("source", {}).get("userId", "unknown")
        reply_token = ev.get("replyToken")
        print(f"[EV] user={user_id} text={text!r}")

        # ---- コマンド ----
        low = text.lower().strip()
        if low == "/ping":
            await reply_message(reply_token, "(system) pong")
            continue
        if low == "/debug on":
            DEBUG_BY_USER.add(user_id)
            await reply_message(reply_token, "debug: ON")
            continue
        if low == "/debug off":
            DEBUG_BY_USER.discard(user_id)
            await reply_message(reply_token, "debug: OFF")
            continue
        if low in ("/set muryi", "set:muryi", "/muryi"):
            PERSONA_BY_USER[user_id] = "muryi"
            await reply_message(reply_token, "(system) ミュリィに切替えたよ！")
            continue
        if low in ("/set piona", "set:piona", "/piona"):
            PERSONA_BY_USER[user_id] = "piona"
            await reply_message(reply_token, "(system) ピオナに切替えたよ！")
            continue
        if low in ("/who", "who?"):
            jp = "ミュリィ" if current_persona(user_id) == "muryi" else "ピオナ"
            await reply_message(reply_token, f"(system) 現在は「{jp}」です")
            continue

        # ---- 通常処理 ----
        try:
            persona = current_persona(user_id)
            intent = detect_intent(text)
            print(f"[EV] intent={intent} persona={persona}")
            # デバッグONの人にはタグを付ける
            head = f"[{persona} | {intent}] " if user_id in DEBUG_BY_USER else ""
            reply = head + generate_reply(text, persona, intent)
            await reply_message(reply_token, reply)
        except Exception as e:
            import traceback; traceback.print_exc()
            try:
                await reply_message(reply_token, "(system) ちょっと詰まったよ、もう一回送ってみて！")
            except Exception:
                pass
    return {"status": "ok"}

@app.get("/healthz")
def healthz():
    return {"ok": True}
