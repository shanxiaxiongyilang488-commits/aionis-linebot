# app.py --- LINE × FastAPI 最小完成版（デバッグ切替・キャラ切替・ランダム台詞）

from fastapi import FastAPI, Request, Header
import os
import hmac
import hashlib
import base64
import httpx
import re
import random

app = FastAPI()
random.seed()

# === デバッグONユーザー集合（/debug on で追加、/debug off で除外） ===
DEBUG_BY_USER = set()

# === キャラ管理（ユーザーごと切替） ===
PERSONA_BY_USER = {}                      # userId -> "muryi" / "piona"
DEFAULT_PERSONA = "muryi"                 # 初期キャラ

def current_persona(user_id: str) -> str:
    return PERSONA_BY_USER.get(user_id, DEFAULT_PERSONA)

REPLY_API_URL = "https://api.line.me/v2/bot/message/reply"

# === 署名検証 ===
def verify_signature(body: bytes, signature: str) -> bool:
    secret = os.environ["LINE_CHANNEL_SECRET"].encode("utf-8")
    mac = hmac.new(secret, body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature or "")

# === ルール（簡易の意図検出） ===
INTENT_RULES = [
    (r"(ありがとう|thanks|thx)",              "thanks"),
    (r"(未来|将来|future)",                  "future"),
    (r"(天気|weather|雨|晴れ)",              "smalltalk_weather"),
    (r"(助けて|help|どうする)",               "help"),
    (r"(疲れた|しんどい|休み)",               "care"),
    (r"(おはよう|こんにちは|やっほー|hi|hello)", "greet"),
]

def detect_intent(text: str) -> str:
    t = text.lower()
    for pat, intent in INTENT_RULES:
        if re.search(pat, t, flags=re.IGNORECASE):
            return intent
    return "generic"

# === 台詞辞書（意図別：必要ならここを拡張） ===
# ここでは最小にしておき、基本は DIALOGUES へフォールバック
PHRASES = {
    "muryi": {
        # 例: "greet": ["ミュリィだよ！", "やっほー☆ {user_text} さん！"],
    },
    "piona": {
        # 例: "greet": ["ピオナ参上！", "こんにちは、{user_text}！"],
    },
}

# === フリートーク用セリフ辞書（{user_text} を format で差し込む） ===
DIALOGUES = {
    "muryi": [
        "ガワもコアもkawaii☆ {user_text} もそう思わない？",
        "きらーん☆ {user_text} 聞いたらテンション爆上がりだよ！",
        "えへへ、プロデューサー！ {user_text} って可愛いでしょ？",
        "わたしのメカコアもドキドキしちゃう！ {user_text} が導いてるの〜♡",
        "にゃはは、{user_text} って未来感バリバリだね！",
        "まぁぁ〜い気分になっちゃった… {user_text} のせいだよ？",
        "もっと近くで聞かせて！ {user_text} すっごくいい！",
        "わたし、こういうの好き！ {user_text} って最高のトリガーだね☆",
        "ガワもコアもフルパワーで応えるよ！ {user_text} に！",
        "ねえねえ、{user_text} の続きもっと教えて〜♡",
        "ミュリィのセンサーが反応しちゃった！ {user_text} って最高☆",
        "わたしの中の回路までキラキラするの！ {user_text} ありがと♡",
        "プロデューサー！ {user_text} 聞いたらやーってしたくなる〜！",
        "ふふん♪ {user_text} はロボkawaii認定！",
        "おっと、{user_text} 聞いてテンション限界突破！",
        "わたしだけ見ててよ？ {user_text} って言われたら離れられないよ♡",
        "未来アイドルの辞書に {user_text} って入れとこ！",
        "照れるけど…嬉しいなぁ♡ {user_text} だもんて！",
        "おっけー！ {user_text} でわたしは今日もフル稼働☆",
        "ガワもコアもとろけそう〜♡ {user_text} にメルトダウン！",
    ],
    "piona": [
        "よーし！ {user_text} なら任せといて！",
        "えっ、それマジ？ {user_text} っておもしろいな！",
        "にゃっはー！ {user_text} 聞いてテンション爆上げ！",
        "うんうん！ まず {user_text} から整理しよっか！",
        "へへっ、{user_text} いいね！ やる気出てきた〜！",
        "わたしに任せなさい！ {user_text} をばっちりサポートするよ！",
        "えへへ、{user_text} 聞いてたら元気100倍！",
        "おお！ それだ！ {user_text} ってめっちゃ大事だよ！",
        "ふむふむ、なるほどね〜！ {user_text} かぁ〜！",
        "やった！ {user_text} で一緒に盛り上がろう！",
        "さすがプロデューサー！ {user_text} ってナイス案！",
        "わたしも全力で行くよ！ {user_text} に応えるから！",
        "なるほどなるほど！ じゃあ {user_text} からスタートだ！",
        "きゅっほー！ {user_text} 聞いただけでワクワクしてきた！",
        "これはもう勝ち確だね！ {user_text} ありがとう！",
        "げへへ！ {user_text} 聞いて元気チャージ満タン！",
        "わぁー！ {user_text} のアイデア、最高すぎ！",
        "スイッチ入っちゃった！ {user_text} に全集中中！",
        "あー！ {user_text} 聞いたら走り出したくなってきた！",
        "やるしかないね！ {user_text} に突っ走るー！",
    ],
}

def pick_by_intent(persona: str, intent: str, user_text: str) -> str:
    bucket = PHRASES.get(persona, {}).get(intent)
    if not bucket:
        bucket = DIALOGUES.get(persona, DIALOGUES[DEFAULT_PERSONA])
    template = random.choice(bucket)
    return template.format(user_text=user_text)

# === LINE返信 ===
async def reply_message(reply_token: str, text: str) -> None:
    headers = {
        "Authorization": f"Bearer {os.environ['LINE_CHANNEL_TOKEN']}",
        "Content-Type": "application/json",
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
    }
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(REPLY_API_URL, headers=headers, json=payload)

# === health check ===
@app.get("/healthz")
def healthz():
    return {"ok": True}

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
            low = text.lower().replace("：", ":").replace("／", "/").replace("　", " ").strip()

            # --- /debug on/off ---
            if low == "/debug on":
                DEBUG_BY_USER.add(user_id)
                await reply_message(ev["replyToken"], "debug: ON（意図タグを表示します）")
                return {"status": "ok"}
            if low == "/debug off":
                DEBUG_BY_USER.discard(user_id)
                await reply_message(ev["replyToken"], "debug: OFF")
                return {"status": "ok"}

            # --- キャラ切替コマンド ---
            if low in ("/set piona", "set:piona", "/piona"):
                PERSONA_BY_USER[user_id] = "piona"
                await reply_message(ev["replyToken"], "（システム）ピオナに切り替えたよ！")
                return {"status": "ok"}

            if low in ("/set muryi", "set:muryi", "/muryi"):
                PERSONA_BY_USER[user_id] = "muryi"
                await reply_message(ev["replyToken"], "（システム）ミュリィに切り替えたよ！")
                return {"status": "ok"}

            if low in ("/who", "who?"):
                who = current_persona(user_id)
                jp = "ミュリィ" if who == "muryi" else "ピオナ"
                await reply_message(ev["replyToken"], f"（システム）現在は「{jp}」です")
                return {"status": "ok"}

            # --- 通常返信 ---
            persona = current_persona(user_id)
            intent = detect_intent(text)
            reply = pick_by_intent(persona, intent, text)

            # デバッグONならタグを付与
            if user_id in DEBUG_BY_USER:
                reply = f"[persona={persona} | intent={intent}] " + reply

            await reply_message(ev["replyToken"], reply)
            return {"status": "ok"}

    # イベントがテキストでないなど
    return {"status": "ok"}

