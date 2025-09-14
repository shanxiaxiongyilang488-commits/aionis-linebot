# app.py --- LINE × FastAPI 最小完成版（フェーズ3: 意図判定 + キャラ切替 + 口調・台詞辞書）

from fastapi import FastAPI, Request, Header
import os
import hmac
import hashlib
import base64
import httpx
import re
import random
from collections import defaultdict, deque

app = FastAPI()
random.seed()

# === デバッグONユーザー集合 ===
DEBUG_BY_USER = set()  # /debug on で追加、/debug off で除外

# === ユーザー状態（最低限） ===
USER_STATE = defaultdict(lambda: {"mood": "normal", "style": "default"})
LAST_SENT = defaultdict(lambda: deque(maxlen=5))  # 直近5件のテンプレを記録（重複抑制の足がかり）

# === キャラ管理 ===
PERSONA_BY_USER = {}             # userId -> "muryi" / "piona"
DEFAULT_PERSONA = "muryi"        # 初期キャラ

def current_persona(user_id: str) -> str:
    return PERSONA_BY_USER.get(user_id, DEFAULT_PERSONA)

REPLY_API_URL = "https://api.line.me/v2/bot/message/reply"

# === 署名検証 ===
def verify_signature(body: bytes, signature: str) -> bool:
    secret = os.environ["LINE_CHANNEL_SECRET"].encode("utf-8")
    mac = hmac.new(secret, body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature or "")

# === 返答送信 ===
async def reply_message(reply_token: str, text: str):
    headers = {
        "Authorization": f"Bearer {os.environ['LINE_CHANNEL_ACCESS_TOKEN']}",
        "Content-Type": "application/json",
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(REPLY_API_URL, headers=headers, json=payload)

# === 意図判定（フェーズ3 完成形） ===
def detect_intent(t: str) -> str:
    t = t.lower()

    if any(w in t for w in ["ありがとう", "thanks", "thx"]):
        return "thanks"

    if any(w in t for w in ["未来", "将来", "future"]):
        return "future"

    if any(w in t for w in ["天気", "weather", "雨", "晴れ"]):
        return "smalltalk_weather"

    if any(w in t for w in ["助けて", "help", "どうする"]):
        return "help"

    if any(w in t for w in ["疲れた", "しんどい", "休み"]):
        return "care"

    if any(w in t for w in ["ムカつく", "嫌い", "怒", "ぷんぷん"]):
        return "angry"

    if any(w in t for w in ["勉強", "宿題", "仕事", "課題", "テスト", "受験"]):
        return "study"

    if any(w in t for w in ["ばいばい", "またね", "おやすみ", "さようなら", "バイ", "see you"]):
        return "bye"

    if any(w in t for w in ["ジョーク", "冗談", "笑わせ", "笑って"]):
        return "joke"

    if any(w in t for w in ["がんばれ", "応援", "疲れた", "しんどい", "つらい"]):
        return "cheer"

    if any(w in t for w in ["好き", "大好き", "すき", "love"]):
        return "love"

    # ← ここを regex で厳格に（半角/全角・表記ゆれを吸収）
    if re.search(r"(おはよう|こんにちは|こんには|こんちわ|こんちゃ|やっほー|hi|hello)", t):
        return "greet"

    return "generic"

# === 口調テーブル（最小） ===
PERSONA_TONE = {
    "muryi": {
        "you": "わたし",
        "ender": {
            "default": "☆",
            "greet": "っ！",
            "thanks": "、ありがとっ☆",
            "angry": "（ぷぷん）",
            "cheer": "、いっしょにがんばろっ！",
        },
    },
    "piona": {
        "you": "私",
        "ender": {
            "default": "！",
            "greet": "！",
            "thanks": "、サンキュ！",
            "cheer": "、フルパワーで応援だ！",
            "angry": "（むぅ）",
        },
    },
}

# === 台詞辞書（フェーズ3） ===
PHRASES = {
    "muryi": {
        # 既存カテゴリ（thanks / greet / generic など）は残す前提
        "joke": [
            "ふふっ、笑わせてほしいの？ じゃあ…ダジャレいっちゃおうかな〜！",
            "ミュリィの必殺☆ミュリィジョーク！…今のは前フリだからね？",
            "にゃはは！笑顔はプロデューサーの最強バフだよ！",
        ],
        "love": [
            "えっ…/// そんなこと言われたら照れちゃうよ…♡",
            "ミュリィ、今とっても幸せ…{user_text} のせいだよ？",
            "だいすきって言われたら…お返しにぎゅー！",
        ],
        "angry": [
            "むむっ…ミュリィ、ぷんぷん！でも深呼吸しよ？いっしょに〜すぅ…はぁ…",
        ],
        "greet": [
            "こんちわ〜！今日もテンション上がってくよ！",
            "やっほ〜！準備OK？",
        ],
        "thanks": [
            "ありがとっ☆ 助かった〜！",
        ],
        "cheer": [
            "いっしょにがんばろっ！ミュリィが全力応援だよ！",
        ],
        "generic": [
            "うんうん、なるほど〜！",
            "ミュリィ、聞いてるよ！",
        ],
        "smalltalk_weather": [
            "お天気？おひさま出てるとテンションMAX☆",
        ],
        "help": [
            "困ってるの？ミュリィ、一緒にやってみよ！",
        ],
        "study": [
            "勉強タイム☆ まずは5分だけ集中ダッシュ！",
        ],
        "bye": [
            "またね！ いつでも呼んでねっ☆",
        ],
        "future": [
            "未来の話？ ワクワクが止まらないね！",
        ],
    },

    "piona": {
        "joke": [
            "私にジョーク任せなって！…笑った？ …ねぇ笑ったでしょ？",
        ],
        "love": [
            "好きって言われると…ちょっと照れるな…でも、ありがと！",
        ],
        "angry": [
            "むか…でも大丈夫。私がクールに収めるよ。",
        ],
        "greet": [
            "こんちは！",
            "やっほー！準備オーケー？",
        ],
        "thanks": [
            "ありがと！助かった！",
        ],
        "cheer": [
            "フルパワーで応援だ！",
        ],
        "generic": [
            "了解、次いこっ！",
            "ふむ…なるほど。",
        ],
        "smalltalk_weather": [
            "天気か。私は晴れが好きだな。",
        ],
        "help": [
            "状況を整理しよう。何が起きてる？",
        ],
        "study": [
            "勉強？ いいね。まずは短距離ダッシュでウォームアップ！",
        ],
        "bye": [
            "またな！ 私はいつでもここにいるよ。",
        ],
        "future": [
            "未来のこと？ 私は前を向くのが得意だよ。",
        ],
    },
}

# === 返答選択 ===
def pick_by_intent(persona: str, intent: str) -> str:
    book = PHRASES.get(persona, {})
    bucket = book.get(intent)
    if not bucket:
        bucket = book.get("generic", ["うんうん。"])
    return random.choice(bucket)

# === 返信生成（フェーズ3：意図×キャラ + デバッグタグ） ===
def generate_reply(text: str, persona: str, intent: str) -> str:
    # 最終テンプレ選択
    template = pick_by_intent(persona, intent)
    reply = template.format(user_text=text)

    return reply

# === Webhook ===
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
            low = text.lower().replace("：", ":").replace("　", " ").strip()

            # --- /debug on/off ハンドラ ---
            if low == "/debug on":
                DEBUG_BY_USER.add(user_id)
                await reply_message(ev["replyToken"], "debug: ON（意図タグを表示します）")
                return {"status": "ok"}

            if low == "/debug off":
                DEBUG_BY_USER.discard(user_id)
                await reply_message(ev["replyToken"], "debug: OFF")
                return {"status": "ok"}

            # --- コマンド（表記ゆれに少し強く） ---
            if low in ("/set piona", "set:piona", "/piona"):
                PERSONA_BY_USER[user_id] = "piona"
                await reply_message(ev["replyToken"], "（システム） ピオナに切り替えたよ！")
                return {"status": "ok"}

            if low in ("/set muryi", "set:muryi", "/muryi"):
                PERSONA_BY_USER[user_id] = "muryi"
                await reply_message(ev["replyToken"], "（システム） ミュリィに切り替えたよ！")
                return {"status": "ok"}

            if low in ("/who", "who?"):
                who = current_persona(user_id)
                jp = "ミュリィ" if who == "muryi" else "ピオナ"
                await reply_message(ev["replyToken"], f"（システム） 現在は「{jp}」です")
                return {"status": "ok"}

            # --- 通常応答 ---
            persona = current_persona(user_id)
            intent = detect_intent(text)
            reply = generate_reply(text, persona, intent)

            # デバッグONならタグを先頭に付ける
            if user_id in DEBUG_BY_USER:
                reply = f"[{persona} | {intent} | neutral] " + reply

            await reply_message(ev["replyToken"], reply)

    # イベントがテキストでないなど
    return {"status": "ok"}

# === ヘルスチェック ===
@app.get("/healthz")
def healthz():
    return {"ok": True}
