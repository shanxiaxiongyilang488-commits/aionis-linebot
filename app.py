1  from fastapi import FastAPI, Request, Header
2  import os, hmac, hashlib, base64
3  import httpx
4  import re
5  import random
6
7  app = FastAPI()
8  random.seed()
9
10 # ==== キャラ管理（ユーザーごと切替）====
11 PERSONA_BY_USER = {}              # userId -> "muryi" / "piona"
12 DEFAULT_PERSONA = "muryi"         # 初期キャラ
13
14 def current_persona(user_id: str) -> str:
15     return PERSONA_BY_USER.get(user_id, DEFAULT_PERSONA)
16
17 REPLY_API_URL = "https://api.line.me/v2/bot/message/reply"
18
19 # ==== 署名検証 ====
20 def verify_signature(body: bytes, signature: str) -> bool:
21     secret = os.environ["LINE_CHANNEL_SECRET"].encode("utf-8")
22     mac = hmac.new(secret, body, hashlib.sha256).digest()
23     expected = base64.b64encode(mac).decode("utf-8")
24     return hmac.compare_digest(expected, signature or "")
25
26 # ==== セリフ辞書 & ルール ====
27 INTENT_RULES = [
28     (r"^/?help|ヘルプ|使い方", "help"),
29     (r"おは|こん(にち|ばん)は|やっほ|hi|hello", "greet"),
30     (r"ありがと|感謝|thx", "thanks"),
31     (r"未来|将来|ミライ|将来的|204|20[3-9][0-9]", "future"),
32     (r"天気|天候|暑い|寒い", "smalltalk_weather"),
33     (r"疲れ|しんど|つかれ", "care"),
34 ]
35
36 PHRASES = {
37     "muryi": {
38         "greet": [
39             "（ミュリィ）やっほー！今日もガワもコアもkawaiiで行こー☆",
40             "（ミュリィ）こんにちは！まず小さく試してみよ、きらーん☆",
41         ],
42         "thanks": ["（ミュリィ）こちらこそありがと！その調子、超kawaii☆"],
43         "future": [
44             "（ミュリィ）未来の生活？ロボkawaiiが当たり前！まず小さく導入→世界征服（比喩）☆",
45             "（ミュリィ）ミライはね、推しとテックが同居するやさしい世界だよ〜♪",
46         ],
47         "smalltalk_weather": ["（ミュリィ）お天気チェックOK！無理せず水分とkawaii補給☆"],
48         "care": ["（ミュリィ）おつおつ！5分だけ深呼吸→甘いの→小さく再開、きらーん☆"],
49         "generic": [
50             "（ミュリィ）{q}、すごく良いです！まず小さく試してみよ！きらーん☆",
51             "（ミュリィ）それいいね！一緒にkawaii進捗つくろ♪",
52         ],
53         "help": ["（ミュリィ）/set piona でピオナ交代、/set muryi で戻るよ！/who で確認☆"],
54     },
55     "piona": {
56         "greet": ["（ピオナ）こんにちは。今日のToDo、上位3つだけに絞ろっか。"],
57         "thanks": ["（ピオナ）どういたしまして。次は実行に移そう。"],
58         "future": [
59             "（ピオナ）未来の生活？便利は前提。大事なのは“選択の負担を減らす設計”。",
60             "（ピオナ）ミライは静かでスマート。通知は少なく、成果は多く。",
61         ],
62         "smalltalk_weather": ["（ピオナ）天気了解。外出は15分前に準備開始がベター。"],
63         "care": ["（ピオナ）いったん3分離れて水を飲もう。再開時は最小タスクから。"],
64         "generic": [
65             "（ピオナ）{q}。まず前提を1つに絞って試す→学習→拡張、で行こう。",
66             "（ピオナ）了解。優先度をS/M/Lに分けよう。Sから着手。",
67         ],
68         "help": ["（ピオナ）/set muryi でミュリィ、/set piona で私。/who で現在の担当を返すよ。"],
69     },
70 }
71
72 # ==== 意図検出 & 返答 ====
73 def detect_intent(text: str) -> str:
74     for pat, intent in INTENT_RULES:
75         if re.search(pat, text, flags=re.IGNORECASE):
76             return intent
77     return "generic"
78
79 def pick(persona: str, intent: str, q: str) -> str:
80     bucket = PHRASES.get(persona, {}).get(intent)
81     if not bucket:
82         bucket = PHRASES.get(persona, {}).get("generic", ["{q}"])
83     return random.choice(bucket).format(q=q)
84
85 def generate_reply(user_text: str, persona: str) -> str:
86     intent = detect_intent(user_text)
87     return pick(persona, intent, user_text)
88
89 # ==== LINE返信 ====
90 async def reply_message(reply_token: str, text: str):
91     headers = {
92         "Authorization": f"Bearer {os.environ['LINE_CHANNEL_TOKEN']}",
93         "Content-Type": "application/json"
94     }
95     payload = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
96     async with httpx.AsyncClient(timeout=10) as client:
97         await client.post(REPLY_API_URL, headers=headers, json=payload)
98
99 # ==== ヘルスチェック ====
100 @app.get("/healthz")
101 def healthz():
102     return {"ok": True}
103
104 # ==== Webhook ====
105 @app.post("/webhook")
106 async def webhook(request: Request, x_line_signature: str = Header(None)):
107     body = await request.body()
108     if not verify_signature(body, x_line_signature):
109         return {"status": "signature_error"}
110
111     data = await request.json()
112     for ev in data.get("events", []):
113         if ev.get("type") == "message" and ev["message"].get("type") == "text":
114             text = ev["message"]["text"].strip()
115             user_id = ev.get("source", {}).get("userId", "unknown")
116
117             # --- コマンド（表記ゆれに少し強く）---
118             low = text.lower().replace("：", ":").replace("　", " ").strip()
119             if low in ("/set piona", "set:piona", "/piona"):
120                 PERSONA_BY_USER[user_id] = "piona"
121                 await reply_message(ev["replyToken"], "（システム）ピオナに切り替えたよ！")
122                 continue
123             if low in ("/set muryi", "set:muryi", "/muryi"):
124                 PERSONA_BY_USER[user_id] = "muryi"
125                 await reply_message(ev["replyToken"], "（システム）ミュリィに切り替えたよ！")
126                 continue
127             if low in ("/who", "who?"):
128                 who = current_persona(user_id)
129                 jp = "ミュリィ" if who == "muryi" else "ピオナ"
130                 await reply_message(ev["replyToken"], f"（システム）現在は {jp} です")
131                 continue
132
133             # --- 通常返信 ---
134             persona = current_persona(user_id)
135             reply = generate_reply(text, persona)
136             await reply_message(ev["replyToken"], reply)
137
138     return {"status": "ok"}
