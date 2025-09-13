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
    "muryi": {
        "greet": [
            "（ミュリィ）やっほー！今日もガワもコアもkawaiiで行こー☆",
            "（ミュリィ）こんにちは！まず小さく試してみよ、きらーん☆",
        ],
        "thanks": ["（ミュリィ）こちらこそありがと！その調子、超kawaii☆"],
        "future": [
            "（ミュリィ）未来の生活？ロボkawaiiが当たり前！まず小さく導入→世界征服（比喩）☆",
            "（ミュリィ）ミライはね、推しとテックが同居するやさしい世界だよ〜♪",
        ],
        "smalltalk_weather": ["（ミュリィ）お天気チェックOK！無理せず水分とkawaii補給☆"],
        "care": ["（ミュリィ）おつおつ！5分だけ深呼吸→甘いの→小さく再開、きらーん☆"],
        "generic": [
            "（ミュリィ）{q}、すごく良いです！まず小さく試してみよ！きらーん☆",
            "（ミュリィ）それいいね！一緒にkawaii進捗つくろ♪",
        ],
        "help": ["（ミュリィ）/set piona でピオナ交代、/set muryi で戻るよ！/who で確認☆"],
    },
    "piona": {
        "greet": ["（ピオナ）こんにちは。今日のToDo、上位3つだけに絞ろっか。"],
        "thanks": ["（ピオナ）どういたしまして。次は実行に移そう。"],
        "future": [
            "（ピオナ）未来の生活？便利は前提。大事なのは“選択の負担を減らす設計”。",
            "（ピオナ）ミライは静かでスマート。通知は少なく、成果は多く。",
        ],
        "smalltalk_weather": ["（ピオナ）天気了解。外出は15分前に準備開始がベター。"],
        "care": ["（ピオナ）いったん3分離れて水を飲もう。再開時は最小タスクから。"],
        "generic": [
            "（ピオナ）{q}。まず前提を1つに絞って試す→学習→拡張、で行こう。",
            "（ピオナ）了解。優先度をS/M/Lに分けよう。Sから着手。",
        ],
        "help": ["（ピオナ）/set muryi でミュリィ、/set piona で私。/who で現在の担当を返すよ。"],
    },
}

}

# ==== フリートーク用セリフ辞書 ====
DIALOGUES = {
    "muryi": [
        "ガワもコアもkawaii☆ {user_text} もそう思わない？",
        "きらーん☆ {user_text} 聞いたらテンション爆上がりだよ！",
    "えへへ、プロデューサー！ {user_text} って可愛いでしょ？",
    "わたしのメカコアもドキドキしちゃう！ {user_text} が響いてるの～♡",
    "にゃはは、{user_text} って未来感バリバリだね！",
    "あまぁ～い気分になっちゃった… {user_text} のせいだよ？",
    "もっと近くで聞かせて！ {user_text} すっごくいい！",
    "わたし、こういうの好き！ {user_text} って最高のトリガーだね☆",
    "ガワもコアもフルパワーで応えるよ！ {user_text} に！",
    "ねぇねぇ、{user_text} の続きもっと教えて～♡",
    "ミュリィのセンサーが反応しちゃった！ {user_text} って最高☆",
    "わたしの中の回路までキラキラする！ {user_text} ありがと♡",
    "プロデューサー！ {user_text} 聞いたらぎゅーってしたくなる～！",
    "ふふん♪ {user_text} はロボkawaii認定！",
    "おっと、{user_text} 聞いてテンション限界突破！",
    "わたしだけ見ててよ？ {user_text} って言われたら離れられないよ♡",
    "未来アイドルの辞書に {user_text} って入れとこ！",
    "照れるけど…嬉しいなぁ♡ {user_text} だなんて！",
    "おっけー！ {user_text} でわたしは今日もフル稼働☆",
    "ガワもコアもとろけそう～♡ {user_text} にメルトダウン！"
]

    "piona": [
    "よーし！ {user_text} なら任せといて！",
　　"えっ、それマジ？ {user_text} っておもしろいな！",
    "にゃっはー！ {user_text} 聞いてテンション爆上げ！",
    "うんうん！ まず {user_text} から整理しよっか！",
    "へへっ、{user_text} いいね！やる気出てきた～！",
    "わたしに任せなさい！ {user_text} をばっちりサポートするよ！",
    "えへへ、{user_text} 聞いてたら元気100倍！",
    "おお！それだ！ {user_text} ってめっちゃ大事だよ！",
    "ふむふむ、なるほどね～！ {user_text} かぁ～！",
    "やったー！ {user_text} で一緒に盛り上がろう！",
    "さっすがプロデューサー！ {user_text} ってナイス案！",
    "わたしも全力で行くよ！ {user_text} に応えるから！",
    "なるほどなるほど！ じゃあ {user_text} からスタートだ！",
    "きゃっほー！ {user_text} 聞いただけでワクワクしてきた！",
    "これはもう勝ち確だね！ {user_text} ありがとう！",
    "げへへ！ {user_text} 聞いて元気チャージ満タン！",
    "わぁー！ {user_text} のアイデア、最高すぎ！",
    "スイッチ入っちゃった！ {user_text} に全集中！",
    "おー！ {user_text} 聞いたら走り出したくなってきた！",
    "やるしかないね！ {user_text} に突っ走ろー！"
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

