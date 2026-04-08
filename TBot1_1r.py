import os
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from flask import Flask, request

from telegram import Update, ReplyKeyboardMarkup, Bot
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ===== CONFIG =====
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEATHER_KEY = os.environ.get("WEATHER_KEY")
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")  # для keep-alive

KYIV_TZ = ZoneInfo("Europe/Kyiv")

# ===== STORAGE =====
last_data = None
history = []
users = set()

# ===== FLASK =====
app = Flask(__name__)
bot = Bot(BOT_TOKEN)
application = ApplicationBuilder().token(BOT_TOKEN).build()

# ===== FLASK ROUTES =====
@app.route("/")
def home():
    return "Bot + Web server running ✅"

@app.route("/update", methods=["POST"])
def update_sensor():
    global last_data, history

    try:
        t = round(float(request.args.get("t")), 1)
        h = round(float(request.args.get("h")), 1)
        p = round(float(request.args.get("p")), 1)
    except:
        return "BAD DATA", 400

    now = datetime.now(timezone.utc).astimezone(KYIV_TZ)
    data = {"time": now, "t": t, "h": h, "p": p}

    last_data = data
    history.append(data)

    # Очищення історії >24 годин
    cleanup_history()

    return "OK"

@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    update = Update.de_json(request.get_json(), bot)
    application.update_queue.put(update)
    return "OK"

# ===== HELPERS =====
def cleanup_history():
    global history
    now = datetime.now(timezone.utc).astimezone(KYIV_TZ)
    history = [d for d in history if now - d["time"] < timedelta(hours=24)]

def midnight_cleaner():
    while True:
        now = datetime.now(timezone.utc).astimezone(KYIV_TZ)
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        time.sleep((next_midnight - now).total_seconds())
        history.clear()
        print("🧹 History cleared at midnight")

def keep_alive():
    if not RENDER_URL:
        return
    while True:
        try:
            requests.get(RENDER_URL, timeout=10)
        except:
            pass
        time.sleep(300)

# ===== TELEGRAM HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users.add(update.effective_chat.id)
    keyboard = [
        ["🌡 Температура"],
        ["📈 Історія за день"],
        ["🌤 Погода в Запоріжжі"]
    ]
    await update.message.reply_text(
        "Привіт 👋",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )

async def temperature(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not last_data:
        await update.message.reply_text("Даних ще немає")
        return
    d = last_data
    await update.message.reply_text(
        f"🌡 {d['t']} °C\n💧 {d['h']} %\n📈 {d['p']} hPa\n🕒 {d['time'].strftime('%H:%M:%S')}"
    )

async def history_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_history()
    if not history:
        await update.message.reply_text("Історія порожня")
        return
    times = [d["time"] for d in history]
    temps = [d["t"] for d in history]

    plt.figure()
    plt.plot(times, temps, marker="o")
    plt.xticks(rotation=45)
    plt.title("Температура за день")
    plt.tight_layout()
    plt.savefig("temp_day.png")
    plt.close()
    await update.message.reply_photo(open("temp_day.png", "rb"))

async def weather_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["Зараз", "3 дні"], ["Назад"]]
    await update.message.reply_text(
        "Оберіть прогноз:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )

async def weather_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = f"https://api.openweathermap.org/data/2.5/weather?q=Zaporizhzhia,UA&appid={WEATHER_KEY}&units=metric&lang=ua"
    r = requests.get(url, timeout=10).json()
    if r.get("cod") != 200:
        await update.message.reply_text("Помилка отримання погоди 😢")
        return
    temp = r["main"]["temp"]
    feels = r["main"]["feels_like"]
    hum = r["main"]["humidity"]
    wind = r["wind"]["speed"]
    desc = r["weather"][0]["description"]
    rain = r.get("rain", {}).get("1h", 0)
    await update.message.reply_text(
        f"🌤 Погода зараз (Запоріжжя)\n\n🌡 {temp:.1f}°C\n🤍 Відчувається: {feels:.1f}°C\n💧 Вологість: {hum}%\n💨 Вітер: {wind} м/с\n🌧 Опади: {rain:.1f} мм\n☁ {desc}"
    )

async def weather_3days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = f"https://api.openweathermap.org/data/2.5/forecast?q=Zaporizhzhia,UA&appid={WEATHER_KEY}&units=metric&lang=ua"
    r = requests.get(url, timeout=10).json()
    if r.get("cod") != "200":
        await update.message.reply_text("Помилка отримання прогнозу 😢")
        return
    days = {}
    for item in r["list"]:
        date, time_str = item["dt_txt"].split(" ")
        temp = item["main"]["temp"]
        desc = item["weather"][0]["description"]
        rain = item.get("rain", {}).get("3h", 0)
        if date not in days:
            days[date] = {"temps": [], "rain": 0, "noon": None, "desc": desc}
        days[date]["temps"].append(temp)
        days[date]["rain"] += rain
        if time_str.startswith("12"):
            days[date]["noon"] = temp
    text = "🌤 Прогноз на 3 дні\n\n"
    for i, (date, info) in enumerate(days.items()):
        if i == 3: break
        temps = info["temps"]
        avg = sum(temps)/len(temps)
        text += f"📅 {date}\n🌡 Мін: {min(temps):.1f}°C\n🌡 Макс: {max(temps):.1f}°C\n🌞 День: {(info['noon'] or avg):.1f}°C\n🌧 Опади: {info['rain']:.1f} мм\n☁ {info['desc']}\n\n"
    await update.message.reply_text(text)

# ===== ADD HANDLERS =====
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.Regex("Температура"), temperature))
application.add_handler(MessageHandler(filters.Regex("Історія"), history_day))
application.add_handler(MessageHandler(filters.Regex("Погода в Запоріжжі"), weather_menu))
application.add_handler(MessageHandler(filters.Regex("^Зараз$"), weather_now))
application.add_handler(MessageHandler(filters.Regex("^3 дні$"), weather_3days))
application.add_handler(MessageHandler(filters.Regex("Назад"), start))

# ===== RUN =====
if __name__ == "__main__":
    threading.Thread(target=midnight_cleaner, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
