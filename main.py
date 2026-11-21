
import os
import re
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")

LOCAL_TZ = ZoneInfo("Asia/Almaty")

# Результаты игр, полученные из Telegram
games = {}

def local_date(timestamp):
    return datetime.fromtimestamp(
        timestamp, timezone.utc
    ).astimezone(LOCAL_TZ).date().isoformat()

def parse_message(message):
    text = message.get("text", "")
    number = re.search(r"#N(\d+)", text, re.I)
    score = re.search(r"\((\d+)\s*:\s*(\d+)\)", text)

    if not number or not score:
        return

    game_id = int(number.group(1))
    a = int(score.group(1))
    b = int(score.group(2))

    if a > b:
        winner = "П1"
    elif b > a:
        winner = "П2"
    else:
        winner = None

    date = local_date(message.get("date", 0))

    games.setdefault(date, {})[game_id] = {
        "score": f"{a}:{b}",
        "winner": winner
    }

@app.route("/")
def home():
    return """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Game Signal</title>
<style>
body{background:#101827;color:white;font-family:Arial;padding:18px}
main{max-width:600px;margin:auto}
section{background:#1d293b;padding:16px;border-radius:12px;margin:14px 0}
input,button{width:100%;box-sizing:border-box;padding:13px;
margin:8px 0;border:0;border-radius:8px;font-size:16px}
button{background:#1684e8;color:white;font-weight:bold}
.result{text-align:center;font-size:30px;font-weight:bold;padding:20px}
.green{color:#39e58b}.red{color:#ff6262}
</style>
</head>
<body>
<main>
<h2>⚽ GAME SIGNAL P1 / P2</h2>
<section>
<label>Дата целевой игры</label>
<input id="date" type="date">
<label>Номер целевой игры</label>
<input id="target" type="number" value="212">
<button onclick="analyze()">ПРОВЕРИТЬ СИГНАЛ</button>
</section>
<section>
<div id="result" class="result">ОЖИДАНИЕ</div>
<div id="details">Ожидаем анализ.</div>
</section>
<section>
<h3>Шесть проверочных игр</h3>
<div id="six"></div>
<h3>Контрольные игры</h3>
<div id="control"></div>
</section>
<script>
document.getElementById("date").value =
  new Date().toLocaleDateString("en-CA");

async function analyze(){
 const date=document.getElementById("date").value;
 const target=Number(document.getElementById("target").value);
 const r=await fetch("/analyze",{
  method:"POST",
  headers:{"Content-Type":"application/json"},
  body:JSON.stringify({date,target})
 });
 const d=await r.json();
 const result=document.getElementById("result");
 result.textContent=d.signal;
 result.className="result "+(d.signal==="НЕТ СИГНАЛА"?"red":"green");
 document.getElementById("details").textContent=d.reason;
 document.getElementById("six").innerHTML=d.six.map(
  g=>`<p>Игра ${g.id}: ${g.score} — ${g.winner||"Нет победителя"}</p>`
 ).join("");
 document.getElementById("control").innerHTML=d.control.map(
  g=>`<p>Игра ${g.id}: ${g.score} — ${g.winner||"Нет победителя"}</p>`
 ).join("");
}
</script>
</main>
</body>
</html>
"""

@app.route("/health")
def health():
    return {"status": "ok"}

@app.route("/telegram/" + WEBHOOK_SECRET, methods=["POST"])
def telegram_webhook():
    update = request.get_json(silent=True) or {}
    message = update.get("message") or update.get("edited_message")

    if message:
        parse_message(message)

    return jsonify({"ok": True})

@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json(silent=True) or {}

    try:
        target = int(data["target"])
        target_date = datetime.strptime(
            data["date"], "%Y-%m-%d"
        ).date()
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "Проверь дату и номер игры"}), 400

    search_date = (target_date - timedelta(days=12)).isoformat()
    anchor = target - 47

    old_games = games.get(search_date, {})
    today_games = games.get(target_date.isoformat(), {})

    six = []
    for i in range(6):
        game_id = anchor - i
        g = old_games.get(game_id, {})
        six.append({
            "id": game_id,
            "score": g.get("score", "нет данных"),
            "winner": g.get("winner")
        })

    p1 = sum(g["winner"] == "П1" for g in six)
    p2 = sum(g["winner"] == "П2" for g in six)

    active = (p1 == 5 and p2 == 1) or (p2 == 5 and p1 == 1)

    control = []
    for game_id in (target - 2, target - 1):
        g = today_games.get(game_id, {})
        control.append({
            "id": game_id,
            "score": g.get("score", "нет данных"),
            "winner": g.get("winner")
        })

    signal = "НЕТ СИГНАЛА"

    if not active:
        reason = f"Условие 5:1 не выполнено. П1: {p1}, П2: {p2}."
    elif not control[0]["winner"] or not control[1]["winner"]:
        reason = "Нет двух завершённых контрольных игр."
    elif control[0]["winner"] != control[1]["winner"]:
        reason = "Контрольные победители разные."
    else:
        signal = "П2" if control[0]["winner"] == "П1" else "П1"
        reason = "Оба условия выполнены."

    return jsonify({
        "signal": signal,
        "reason": reason,
        "search_date": search_date,
        "search_start": anchor,
        "p1": p1,
        "p2": p2,
        "six": six,
        "control": control
    })

# Автоматически подключаем Telegram webhook
def setup_webhook():
    if not BOT_TOKEN or not WEBHOOK_SECRET or not RENDER_URL:
        print("Webhook ещё не настроен: проверь переменные окружения.")
        return

    url = f"{RENDER_URL}/telegram/{WEBHOOK_SECRET}"
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            json={"url": url},
            timeout=20
        )
        print("Telegram webhook:", response.text)
    except Exception as e:
        print("Webhook setup error:", str(e))

setup_webhook()


@app.route("/pulse-check")
def pulse_check():
    api_key = os.environ.get("PULSESCORE_API_KEY", "")

    if not api_key:
        return jsonify({"ok": False, "error": "API key не найден в Render"}), 503

    try:
        response = requests.get(
            "https://api.pulsescore.net/api/onexbet/results/leagues",
            headers={"X-Secret": api_key},
            params={"sport": "esports", "page": 1, "limit": 5},
            timeout=20
        )

        if response.status_code != 200:
            return jsonify({
                "ok": False,
                "http_status": response.status_code,
                "message": "Ошибка ответа PulseScore"
            }), 502

        return jsonify({
            "ok": True,
            "message": "PulseScore API отвечает",
            "data": response.json()
        })

    except requests.RequestException:
        return jsonify({
            "ok": False,
            "message": "Не удалось связаться с PulseScore"
        }), 502

