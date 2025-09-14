from fastapi import FastAPI, Request, Header
import os, hmac, hashlib, base64
import httpx
import re
import random

app = FastAPI()
random.seed()
DEBUG_BY_USER = set()  # ← 追加（デバッグ表示をONにしたユーザーIDの集合）

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
        "きら〜ん☆ {user_text} 聞いたらテンション爆上がりだよ！",
        "えへへ、プロデューサー！ {user_text} って可愛いでしょ？",
        "わたしのメカコアもドキドキしちゃう！ {user_text} が導いてるの〜♡",
        "にゃはは、{user_text} って未来感バリバリだね！",
        "まあぁ〜い気分になっちゃった… {user_text} のせいだよ？",
        "もっと近くで聞かせて！ {user_text} すっごくいい！",
        "わたし、こういうの好き！ {user_text} って最高のトリガーだね☆",
        "ガワもコアもフルパワーで応えるよ！ {user_text} に！",
        "ねぇねぇ、{user_text} の続きをもっと教えて〜♡",
        "ミュリィのセンサーが反応しちゃった！ {user_text} って最高☆",
        "わたしの中の回路までキラキラするの！ {user_text} ありがとう",
        "プロデューサー！ {user_text} 聞いたらぎゅーってしたくなる〜！",
        "ふふん♪ {user_text} はロボkawaii認定！",
        "おっと、{user_text} 聞いてテンション限界突破！",
        "わたしだけ見ててよ？ {user_text} って言われたら離れられないよ♡",
        "未来アイドルの辞書に {user_text} って入れとこ！",
        "照れるけど…嬉しいなぁ♡ {user_text} だもん！",
        "おっけー！ {user_text} でわたしは今日もフル稼働☆",
        "ガワもコアもとろけそう〜♡ {user_text} にメルトダウン！"
    ],
    "piona": [
        "よーし！ {user_text} なら任せといて！"
        "えっ、それマジ？ {user_text} っておもしろいな！",
        "にゃっはー！ {user_text} 聞いてテンション爆上げ！",
        "うんうん！ まず {user_text} から整理しよっか！",
        "へへっ、{user_text} いいね！やる気出てきた〜！",
        "わたしに任せなさい！ {user_text} をばっちりサポートするよ！",
        "えへへ、{user_text} 聞いてたら元気100倍！",
        "おお！それだ！ {user_text} ってめっちゃ大事だよ！",
        "ふむふむ、なるほどねー！ {user_text} かぁ〜！",
        "やったー！ {user_text} で一緒に盛り上がろう！",
        "さすがプロデューサー！ {user_text} ってナイス案！",
        "わたしも全力で行くよ！ {user_text} に応えるから！",
        "なるほどなるほど！ じゃあ {user_text} からスタートだ！",
        "きゃっほー！ {user_text} 聞いただけでワクワクしてきた！",
        "これはもう勝ち確だね！ {user_text} ありがとう！",
        "げへへ！ {user_text} 聞いて元気チャージ満タン！",
        "わぁー！ {user_text} のアイデア、最高すぎ！",
        "スイッチ入っちゃった！ {user_text} に全集中！",
        "あー！ {user_text} 聞いたら走り出したくなってきた！",
        "やるしかないね！ {user_text} に突っ走ろー！"
    ]
}


# ==== 意図検出 & 返答 ====
def detect_intent(text: str) -> str:
    t = text.lower()

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
    if any(w in t for w in ["おはよう", "こんにちは", "やっほー", "hi", "hello"]):
        return "greet"

    return "generic"


def pick(persona: str, intent: str, q: str) -> str:
    bucket = PHRASES.get(persona, {}).get(intent)
    if not bucket:
        bucket = PHRASES.get(persona, {}).get("generic", ["{q}"])
    return random.choice(bucket).format(q=q)

def generate_reply(user_text: str, persona: str) -> str:
    # 話す候補（なければデフォルトのキャラにフォールバック）
    bucket = DIALOGUES.get(persona, DIALOGUES.get(DEFAULT_PERSONA, []))
    if not bucket:
        return user_text  # 候補が空なら入力をそのまま返す

    template = random.choice(bucket)  # ← ここで毎回ランダム！
    return template.format(user_text=user_text)


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
        
        
        # --- /debug on/off ハンドラ ---
    low = text.lower().replace("：", ":").replace("／", "/").replace("　", " ").strip()

     if "/debug on" in low:
        DEBUG_BY_USER.add(user_id)
        await reply_message(ev["replyToken"], "debug: ON（意図タグを表示します）")
        return {"status": "ok"}  # ← ここで確実に200を返して終わり

    if "/debug off" in low:
        DEBUG_BY_USER.discard(user_id)
        await reply_message(ev["replyToken"], "debug: OFF")
        return {"status": "ok"}  # ← ここで確実に200を返して終わり


            # ------------------------------


            
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
            intent  = detect_intent(text)        # ← ここで意図を判定
            reply   = generate_reply(text, persona)

            # デバッグONならタグを先頭に付ける
            if user_id in DEBUG_BY_USER:
            　　reply = f"[persona={persona} | intent={intent}] " + reply

            await reply_message(ev["replyToken"], reply)
            return {"status": "ok"}

