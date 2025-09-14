# app.py --- LINE × FastAPI 最小完成版（デバッグ切替・キャラ切替・ランダム台詞）

from fastapi import FastAPI, Request, Header
import os
import hmac
import hashlib
import base64
import httpx
import re
import random
from collections import deque, defaultdict

# === キャラ別セリフ集 ===
DIALOGUES = {
    "muryi": {
        "greet": [
            "おっはよ！ 今日の{user_text}、聞いてテンション爆上がり〜！",
            "やっほー！来てくれてうれし〜！{user_text} から始めよっ！",
            "こんにちは！ まずは深呼吸…よしっ、{user_text} からいこう！",
        ],
        "generic": [
            "{user_text} 了解っ！ミュリイのセンサーが反応したよ〜♪",
            "メモったよ！ 次は何する？",
        ],
    },
    "piona": {
        "greet": [
            "よーし！{user_text} なら任せて！",
            "こんにちは！ サクサク進めよう。{user_text} からスタート！",
            "おつかれさま！リズム良くいくよ。まずは {user_text}！",
        ],
        "generic": [
            "{user_text} 了解。いったん整理して動くね！",
            "把握！一緒に片付けよう！",
        ],
    },
}
from collections import deque, defaultdict

app = FastAPI()
random.seed()

# === デバッグONユーザー集合（/debug on で追加、/debug off で除外） ===
DEBUG_BY_USER = set()

# === ユーザー状態と重複抑止 ===
USER_STATE = defaultdict(lambda: {"mood": "normal", "style": "default"})
LAST_SENT = defaultdict(lambda: deque(maxlen=5))  # 直近5件のテンプレを記録

# ==== 感情（mood）管理 =====================================

# -2 ～ +2 の数値を内部スコアとして持ち、文字ラベルにマップする
MOOD_MIN, MOOD_MAX = -2, 2
MOOD_NAMES = {
    -2: "very_sad",
    -1: "sad",
     0: "normal",
     1: "happy",
     2: "excited",
}

# 意図ごとの感情への影響。なければ 0（ニュートラル）
MOOD_EFFECT = {
    "thanks": +1,
    "greet":  +1,
    "love":   +1,
    "cheer":  +1,
    "joke":   +1,

    "help":   -1,
    "care":   -1,
    "angry":  -1,
    "bye":    -1,
    # 他の意図は 0
}

def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))

def update_mood(user_id: str, intent: str) -> None:
    """
    1) 意図による加算/減算
    2) 直後にほんの少し減衰（0 に近づける）
    3) -2..+2 にクランプし、ラベルを USER_STATE に反映
    """
    st = USER_STATE[user_id]                     # defaultdict なので自動生成される
    score = int(st.get("mood_score", 0))

    score += MOOD_EFFECT.get(intent, 0)          # ①影響
    # ②減衰（強すぎ防止） — 0 に一歩近づける
    if score > 0:
        score -= 1
    elif score < 0:
        score += 1

    score = _clamp(score, MOOD_MIN, MOOD_MAX)    # ③クランプ
    st["mood_score"] = score
    st["mood"] = MOOD_NAMES[score]

def tone_wrap(text: str, mood: str) -> str:
    """
    返答テキストに情緒の“味付け”を付与（最小限）
    - happy/excited : ちょいキラキラ
    - sad/very_sad  : 語尾を少し落とす
    - normal        : そのまま
    """
    if mood in ("excited", "happy"):
        return f"{text} ✨"
    if mood in ("sad", "very_sad"):
        return f"{text}…"
    return text


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


def detect_intent(t: str) -> str:
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
    if re.search(r"(おはよう|こんにちは|こんにちわ|こんちゃ|やっほー|hi|hello)", t):
        return "greet"   # ← 半角スペース4つ分インデント
        
    return "generic"


# === 台詞辞書（意図別：必要ならここを拡張） ===
# ここでは最小にしておき、基本は DIALOGUES へフォールバック
PHRASES = {
    "muryi": {
        # ...（既存の thanks / greet / generic などは残す）
        "joke": [
            "ふふっ、笑わせてほしいの？じゃあ…ダジャレいっちゃおうかな〜！",
            "ミュリィの必殺☆ミュリィジョーク！…今のは前フリだからね？",
            "にゃはは！笑顔はプロデューサーの最強バフだよ！"
        ],
        "love": [
            "えっ…/// そんなこと言われたら照れちゃうよ…♡",
            "ミュリィ、今とっても幸せ…{user_text} のせいだよ？",
            "だいすきって言われたら…お返しにぎゅー！"
        ],
        "angry": [
            "むむっ…ミュリィ、ぷんすこ！でも深呼吸しよ？いっしょに〜すぅ…はぁ…",
            "怒ってるの？よし、ミュリィがなでなでして落ち着こ！",
            "気持ちわかるよ。いっしょにちょっとずつ整えてこ？"
        ],
        "study": [
            "がんばってる {user_text} は超クール！ミュリィが全力応援だよ📚✨",
            "休憩→再開のループで効率UP！3分だけストレッチしよっ？",
            "ミッション：25分集中→5分休憩！タイマーセットいくよ〜！"
        ],
        "bye": [
            "またね！ミュリィ、ここでずっと待ってるからね♡",
            "おやすみ〜！いい夢見ようね。お休み前に深呼吸〜♪",
            "ばいばい！次はもっと楽しいことしよっ！"
        ],
    },
    "piona": {
        # ...（既存は残す）
        "joke": [
            "ふふ、笑顔は判断力も上げる。よし、一発…いや二発いく？",
            "そんなに笑いたい？じゃ、効率よく笑えるやつ選んどくね。",
            "クスっと来た？OK、次は腹筋に効くやつ出す。"
        ],
        "love": [
            "…そう言われると、悪くない気分。ありがとう。",
            "照れるね。でも、ちゃんと受け取ったよ。その気持ち。",
            "大事にする。言葉も、あなたも。"
        ],
        "angry": [
            "深呼吸→水→少し歩く。まずは体から鎮めよう。話はそれから。",
            "原因を分解しよう。事実／解釈／感情。書き出せる？手伝うよ。",
            "無理しない。距離を置くのも戦略。戻る時は私が呼ぶ。"
        ],
        "study": [
            "タイムボックス25分、行こう。終わったら報告、ね？",
            "優先度はS/M/Lで切る。Sの一手だけに集中しよう。",
            "完璧より完了。まずは粗くでも出す→直す。伴走するよ。"
        ],
        "bye": [
            "またね。ちゃんと休むこと、タスクだよ。",
            "おやすみ。デバイスは遠くへ。私はここにいる。",
            "ログオフ、いい判断。戻ったら続きからやろう。"
        ],
    }
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
            reply  = generate_reply(text, persona, intent)   # ← こちらに統一
            # デバッグONならタグを付与
            if user_id in DEBUG_BY_USER:
                reply = f"[persona={persona} | intent={intent}] " + reply

            await reply_message(ev["replyToken"], reply)
            return {"status": "ok"}

    # イベントがテキストでないなど
    return {"status": "ok"}
# === 応答生成 ===
def generate_reply(text: str, persona: str, intent: str, emotion: str = "neutral") -> str:
    # 1) キャラ別の意図バケットを取得
    bucket = DIALOGUES.get(persona, {}).get(intent)

    # 2) 無ければキャラ別 generic、さらに無ければ最後の保険
    if not bucket:
        bucket = DIALOGUES.get(persona, {}).get("generic", ["{user_text}"])

    # 3) ランダムにテンプレを選んで差し込み
    template = random.choice(bucket)
    return template.format(user_text=text)
