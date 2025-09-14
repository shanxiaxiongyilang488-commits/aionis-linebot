# app.py --- LINE × FastAPI フェーズ3（フル動作ベース：意図判定 + キャラ切替 + 口調合成 + 安全網）

from fastapi import FastAPI, Request, Header
import os
import hmac
import hashlib
import base64
import httpx
import re
import random
from collections import defaultdict, deque

# -------------------------------------------------
# 基本セットアップ
# -------------------------------------------------
app = FastAPI()
random.seed()

REPLY_API_URL = "https://api.line.me/v2/bot/message/reply"

# デバッグONユーザー（/debug on で追加、/debug off で除外）
DEBUG_BY_USER = set()

# 担当キャラ（ユーザーごと）
PERSONA_BY_USER = {}            # user_id -> "muryi" | "piona"
DEFAULT_PERSONA = "muryi"

def current_persona(user_id: str) -> str:
    return PERSONA_BY_USER.get(user_id, DEFAULT_PERSONA)

# -------------------------------------------------
# LINE 署名検証 & 返信
# -------------------------------------------------
def verify_signature(body: bytes, signature: str) -> bool:
    secret = os.environ["LINE_CHANNEL_SECRET"].encode("utf-8")
    mac = hmac.new(secret, body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature or "")

async def reply_message(reply_token: str, text: str):
    headers = {
        "Authorization": f"Bearer {os.environ['LINE_CHANNEL_ACCESS_TOKEN']}",
        "Content-Type": "application/json",
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text[:1000]}],  # 念のため1000文字で切る
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(REPLY_API_URL, headers=headers, json=payload)
        # 送信失敗もログに出す
        if r.status_code >= 400:
            print(f"[ERR] LINE reply {r.status_code}: {r.text}")

# -------------------------------------------------
# 意図判定（2.5相当：表記ゆれに強め）
# -------------------------------------------------
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
    if any(w in t for w in ["ばいばい", "またね", "おやすみ", "さようなら", "ﾊﾞｲ", "バイ", "see you"]):
        return "bye"
    if any(w in t for w in ["ジョーク", "冗談", "笑わせ", "笑って"]):
        return "joke"
    if any(w in t for w in ["がんばれ", "応援", "疲れた", "しんどい", "つらい"]):
        return "cheer"
    if any(w in t for w in ["好き", "大好き", "すき", "love"]):
        return "love"

    # あいさつ（句読点・波線付きにも対応）
    if re.search(r"(おはよう|こんにちは|こんにちわ|こんちゃ|こんちは|やっほー|hi|hello)[!！〜～、。]*", t, re.IGNORECASE):
        return "greet"

    return "generic"

# -------------------------------------------------
# フェーズ3：口調テーブル & 台詞辞書
# -------------------------------------------------
PERSONA_TONE = {
    "muryi": {
        "you": "わたし",
        "ender": {
            "default": "！",
            "greet":   "〜！",
            "thanks":  "、ありがとっ☆",
            "angry":   "（ぷん）",
            "cheer":   "、いっしょにがんばろっ！",
        },
    },
    "piona": {  # ← 一人称は「私」で統一（僕っ娘回避）
        "you": "私",
        "ender": {
            "default": "！",
            "greet":   "！",
            "thanks":  "、サンキュ！",
            "angry":   "（むぅ）",
            "cheer":   "、フルパワーで応援だ！",
        },
    },
}

PHRASES = {
    "muryi": {
        "greet": [
            "こんにちは〜",
            "やっほ〜！ 会いに来てくれてうれしい！",
        ],
        "thanks": [
            "助かった〜！ありがとっ☆",
        ],
        "joke": [
            "ふふっ、笑わせてほしいの？ じゃあ…ダジャレいっちゃおうかな〜！",
            "ミュリィの必殺☆ミュリィジョーク！…今のは前フリだからね？",
        ],
        "love": [
            "えへ…/// そんなこと言われたら照れちゃうよ…♡",
            "だいすきって言われたら…お返しにぎゅー！",
        ],
        "angry": [
            "むむっ…ぷんぷん！でも深呼吸しよ？ いっしょに〜すぅ…はぁ…",
        ],
        "cheer": [
            "任せて！ いっしょにがんばろっ！",
        ],
        "smalltalk_weather": [
            "お天気の話？ 今日の空、けっこう好きかも！",
        ],
        "help": [
            "状況教えて？ いっしょに考えよう！",
        ],
        "study": [
            "勉強タイム！ まずは5分、集中ダッシュ☆",
        ],
        "bye": [
            "またね！ ここでずっと待ってるからね♡",
        ],
        "future": [
            "未来かぁ…ワクワクが止まらないね！",
        ],
        "generic": [
            "うん、聞いてるよ！",
            "なるほどなるほど〜！",
        ],
    },
    "piona": {
        "greet": [
            "こんちは！",
            "やっほー！準備オーケー？",
        ],
        "thanks": [
            "ありがと！助かった！",
        ],
        "joke": [
            "私にジョーク任せなって！…笑った？ …ねぇ笑ったでしょ？",
        ],
        "love": [
            "好きって言われると…ちょっと照れるな…でも、ありがと！",
        ],
        "angry": [
            "むか…でも大丈夫。私がクールに収めるよ。",
        ],
        "cheer": [
            "フルパワーで応援だ！",
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
        "generic": [
            "了解、次いこっ！",
            "ふむ…なるほど。",
        ],
    },
}

# -------------------------------------------------
# フェーズ3：口調合成ユーティリティ
# -------------------------------------------------
def _tone_for(persona: str, intent: str) -> tuple[str, str]:
    tone = PERSONA_TONE.get(persona, {})
    you = tone.get("you", "")
    enders = tone.get("ender", {}) or {}
    ender = enders.get(intent, enders.get("default", ""))
    return you, ender

def _pick_phrase(persona: str, intent: str, q_text: str) -> str:
    p = PHRASES.get(persona, {})
    bucket = p.get(intent) or p.get("generic") or []
    if not bucket:
        return q_text
    tmpl = random.choice(bucket)
    # {user_text} / {q} のプレースホルダに入力を差し込める
    return tmpl.replace("{user_text}", q_text).replace("{q}", q_text)

def apply_tone(persona: str, intent: str, text: str) -> str:
    you, ender = _tone_for(persona, intent)
    base = f"{you} {text}" if you else text
    return f"{base}{ender}"

# 応答生成（フェーズ3：セリフ×口調合成）
def generate_reply(text: str, persona: str, intent: str) -> str:
    phrase = _pick_phrase(persona, intent, text)
    reply  = apply_tone(persona, intent, phrase)
    return reply

# -------------------------------------------------
# ヘルスチェック
# -------------------------------------------------
@app.get("/healthz")
def healthz():
    return {"ok": True}

# -------------------------------------------------
# Webhook 本体
# -------------------------------------------------
@app.post("/webhook")
async def webhook(request: Request, x_line_signature: str = Header(None)):
    body = await request.body()
    if not verify_signature(body, x_line_signature):
        print("[ERR] signature_error: header=", x_line_signature)
        return {"status": "signature_error"}

    data = await request.json()
    for ev in data.get("events", []):
        if ev.get("type") == "message" and ev["message"].get("type") == "text":
            text = ev["message"]["text"].strip()
            user_id = ev.get("source", {}).get("userId", "unknown")
            reply_token = ev["replyToken"]

            # コマンドの正規化
            low = text.lower().replace("：", ":").replace("　", " ").strip()

            # --- 生死判定コマンド（往復確認用） ---
            if low in ("/ping", "ping"):
                await reply_message(reply_token, "pong")
                continue

            # --- /debug on/off ---
            if low == "/debug on":
                DEBUG_BY_USER.add(user_id)
                await reply_message(reply_token, "debug: ON（意図タグを表示します）")
                continue
            if low == "/debug off":
                DEBUG_BY_USER.discard(user_id)
                await reply_message(reply_token, "debug: OFF")
                continue

            # --- キャラ切替 ---
            if low in ("/set piona", "set:piona", "/piona"):
                PERSONA_BY_USER[user_id] = "piona"
                await reply_message(reply_token, "（システム）ピオナに切り替えたよ！")
                continue
            if low in ("/set muryi", "set:muryi", "/muryi"):
                PERSONA_BY_USER[user_id] = "muryi"
                await reply_message(reply_token, "（システム）ミュリィに切り替えたよ！")
                continue
            if low in ("/who", "who?"):
                who = current_persona(user_id)
                jp = "ミュリィ" if who == "muryi" else "ピオナ"
                await reply_message(reply_token, f"（システム）現在は「{jp}」です")
                continue

            # --- 通常応答（安全網つき）---
            try:
                persona = current_persona(user_id)
                intent  = detect_intent(text)
                reply   = generate_reply(text, persona, intent)

                if user_id in DEBUG_BY_USER:
                    reply = f"[{persona} | {intent} | neutral] " + reply

            except Exception as e:
                # ここで落ちても“必ず返す”保険
                print(f"[ERR] reply flow failed: {e} | text={repr(text)} | uid={user_id}")
                reply = f"(safe mode) 受け取ったよ → {text}"

            await reply_message(reply_token, reply)

    return {"status": "ok"}
