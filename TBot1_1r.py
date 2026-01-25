import os
import json
import asyncio
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import matplotlib.pyplot as plt
from flask import Flask, request

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ---------------- CONFIG ----------------

TOKEN = os.environ.get("BOT_TOKEN", "PUT_YOUR_TOKEN")
TZ = ZoneInfo("Europe/Kyiv")
HISTORY_FILE = "history.json"

LAT = 47.84      # Zaporizhzhia
LON = 35.14

ESP_STATUS = False
LAST_CHAT_ID = None

# ---------------- UTILS ----------------

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, "r") as f:
        return json.load(f)

def save_history(data):
    with open(HISTORY_FILE, "w") as f:
        json.dump(data, f)

def cleanup_history():
    data = load_history()
    now = datetime.now(TZ)
    cleaned = []
    for d in data:
        t = datetime.fromisoformat(d["time"])
        if now - t < timedelta(hours=24):
            cleaned.append(d)
    save_history(cleaned)

# ---------------- WEATHER ----------------

def get_weather():
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={LAT}&longitude={LON}"
        f"&current=temperature_2m,precipitation"
        f"&daily=precipitation_sum"
        f"&timezone=Europe/Kyiv"
    )

    r = requests.get(url, timeout=10)
    data = r.json()

    now_temp = data["current"]["temperature_2m"]
    now_rain = data["current"]["precipitation"]

    days = data["daily"]["time"][:3]
    rains = data["daily"]["precipitation_sum"][:3]

    text = f"🌤 Погода зараз:\n"
    text += f"Температура: {now_temp}°C\n"
    text += f"Опади: {now_rain} мм\n\n"
    text += "📅 Опади на 3 дні:\n"

    for d, r in zip(days, rains):
        text += f"{d}: {r} мм\n"

    return text

# ---------------- TELEGRAM ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LAST_CHAT_ID
    LAST_CHAT_ID = update.effective_chat.id
    await update.message.reply_text("✅ Бот запущений і чекає ESP32")

async def graph(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_history()
    if not data:
        await update.message.reply_text("Немає даних")
        return

    times = [datetime.fromisoformat(d["time"]) for d in data]
    temps = [d["t"] for d in data]

    plt.figure()
    plt.plot(times, temps)
    plt.xticks(rotation=30)
    plt.tight_layout()
    plt.savefig("graph.png")
    plt.close()

    await update.message.reply_photo(open("graph.png", "rb"))

async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = get_weather()
    await update.message.reply_text(text)

# ---------------- BACKGROUND LOOP ----------------

async def background_loop(app: Application):
    global ESP_STATUS, LAST_CHAT_ID

    while True:
        try:
            cleanup_history()
            data = load_history()

            if data:
                last_time = datetime.fromisoformat(data[-1]["time"])
                now = datetime.now(TZ)
                diff = (now - last_time).total_seconds()

                if diff < 420:
                    if not ESP_STATUS:
                        ESP_STATUS = True
                        if LAST_CHAT_ID:
                            await app.bot.send_message(LAST_CHAT_ID, "🟢 ESP32 ONLINE")
                else:
                    if ESP_STATUS:
                        ESP_STATUS = False
                        if LAST_CHAT_ID:
                            await app.bot.send_message(LAST_CHAT_ID, "🔴 ESP32 OFFLINE")

        except Exception as e:
            print("BG error:", e)

        await asyncio.sleep(60)

# ---------------- FLASK ----------------

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot works"

@app.route("/update")
def update_esp():
    t = round(float(request.args.get("t", 0)), 1)
    h = round(float(request.args.get("h", 0)), 1)
    p = round(float(request.args.get("p", 0)), 1)

    history = load_history()
    history.append({
        "time": datetime.now(TZ).isoformat(),
        "t": t,
        "h": h,
        "p": p
    })
    save_history(history)

    return "OK"

# ---------------- MAIN ----------------

async def run_bot():
    global application

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("graph", graph))
    application.add_handler(CommandHandler("weather", weather))

    asyncio.create_task(background_loop(application))

    await application.initialize()
    await application.start()
    await application.bot.initialize()

    # тримаємо цикл живим
    while True:
        await asyncio.sleep(3600)


def run():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_bot())


threading.Thread(target=run, daemon=True).start()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))


