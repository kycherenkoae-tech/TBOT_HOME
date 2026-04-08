import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from flask import Flask, request

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
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

KYIV_TZ = ZoneInfo("Europe/Kyiv")


# ===== STORAGE =====
last_data = None
last_seen = None
history = []
users = set()


# ===== APP =====
app = Flask(__name__)
application = Application.builder().token(BOT_TOKEN).build()


# ===== ROUTES =====
@app.route("/")
def home():
    return "OK"


# 👉 ДАНІ З ПЛАТИ (ESP)
@app.route("/update")
def update_data():
    global last_data, last_seen, history

    try:
        t = round(float(request.args.get("t")), 1)
        h = round(float(request.args.get("h")), 1)
        p = round(float(request.args.get("p")), 1)
    except:
        return "BAD DATA", 400

    now = datetime.now(timezone.utc).astimezone(KYIV_TZ)

    data = {"time": now, "t": t, "h": h, "p": p}

    last_seen = now
    last_data = data
    history.append(data)

    cleanup_history()

    print("📡 DATA:", data)

    return "OK"


# 👉 TELEGRAM WEBHOOK
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
async def telegram_webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return "OK"


# ===== HELPERS =====
def cleanup_history():
    global history
    now = datetime.now(timezone.utc).astimezone(KYIV_TZ)
    history = [d for d in history if now - d["time"] < timedelta(hours=24)]


def midnight_cleaner():
    global history
    while True:
        now = datetime.now(timezone.utc).astimezone(KYIV_TZ)
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        time.sleep((next_midnight - now).total_seconds())
        history.clear()
        print("🧹 History cleared")


# ===== TELEGRAM =====
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
        f"🌡 {d['t']} °C\n"
        f"💧 {d['h']} %\n"
        f"📈 {d['p']} hPa\n"
        f"🕒 {d['time'].strftime('%H:%M:%S')}"
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
        await update.message.reply_text("Помилка погоди 😢")
        return

    await update.message.reply_text(
        f"🌡 {r['main']['temp']:.1f}°C\n"
        f"💧 {r['main']['humidity']}%\n"
        f"💨 {r['wind']['speed']} м/с\n"
        f"☁ {r['weather'][0]['description']}"
    )


async def weather_3days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Функція в розробці 😉")


# ===== REGISTER HANDLERS =====
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.Regex("Температура"), temperature))
application.add_handler(MessageHandler(filters.Regex("Історія"), history_day))
application.add_handler(MessageHandler(filters.Regex("Погода"), weather_menu))
application.add_handler(MessageHandler(filters.Regex("^Зараз$"), weather_now))
application.add_handler(MessageHandler(filters.Regex("Назад"), start))


# ===== MAIN =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))

    # 👉 запускаємо webhook
    application.initialize()
    application.bot.set_webhook(f"https://tbot-home.onrender.com/{BOT_TOKEN}")

    # 👉 фонові задачі
    import threading
    threading.Thread(target=midnight_cleaner, daemon=True).start()

    print("✅ SERVER STARTED")

    app.run(host="0.0.0.0", port=port)
