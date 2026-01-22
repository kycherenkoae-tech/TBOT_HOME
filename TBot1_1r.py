import os
import time
import threading
from datetime import datetime, timedelta, timezone

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
RENDER_URL = os.environ.get("RENDER_URL")  # https://tbot-home.onrender.com

UA_TZ = timezone(timedelta(hours=2))


# ===== STORAGE =====
last_data = None
history = []
users = set()

last_seen = None
ESP_TIMEOUT = 600  # 10 хв


# ===== FLASK =====
app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is alive"


@app.route("/update")
def update_from_esp():
    global last_data, last_seen

    t = round(float(request.args.get("t")), 1)
    h = round(float(request.args.get("h")), 1)
    p = round(float(request.args.get("p")), 1)

    now = datetime.now(UA_TZ)

    data = {"time": now, "t": t, "h": h, "p": p}

    if last_seen is None:
        notify_all("🟢 ESP зʼявився онлайн")

    last_seen = time.time()
    last_data = data
    history.append(data)

    return "OK"


# ===== TELEGRAM =====
async def notify_all(text):
    for u in users:
        try:
            await application.bot.send_message(u, text)
        except:
            pass


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
    r = requests.get(url).json()

    if r.get("cod") != 200:
        await update.message.reply_text("Помилка погоди")
        return

    text = (
        f"🌤 Погода Запоріжжя\n\n"
        f"🌡 {r['main']['temp']}°C\n"
        f"💧 {r['main']['humidity']}%\n"
        f"💨 {r['wind']['speed']} м/с\n"
        f"{r['weather'][0]['description']}"
    )

    await update.message.reply_text(text)


async def weather_3days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = f"https://api.openweathermap.org/data/2.5/forecast?q=Zaporizhzhia,UA&appid={WEATHER_KEY}&units=metric&lang=ua"
    r = requests.get(url).json()

    if r.get("cod") != "200":
        await update.message.reply_text("Помилка прогнозу")
        return

    days = {}

    for item in r["list"]:
        date, time_s = item["dt_txt"].split(" ")
        temp = item["main"]["temp"]

        if date not in days:
            days[date] = []

        days[date].append(temp)

    text = "🌤 Прогноз 3 дні\n\n"

    for i, (d, temps) in enumerate(days.items()):
        if i == 3:
            break

        text += f"{d}\n🌡 {min(temps):.1f} — {max(temps):.1f}\n\n"

    await update.message.reply_text(text)


# ===== WATCHDOG =====
def watchdog():
    global last_seen
    while True:
        if last_seen and time.time() - last_seen > ESP_TIMEOUT:
            last_seen = None
            try:
                application.create_task(notify_all("🔴 ESP зник офлайн"))
            except:
                pass
        time.sleep(30)


# ===== WEBHOOK =====
@app.post(f"/{BOT_TOKEN}")
def telegram_webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.create_task(application.process_update(update))
    return "OK"


# ===== MAIN =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Regex("Температура"), temperature))
    application.add_handler(MessageHandler(filters.Regex("Історія"), history_day))
    application.add_handler(MessageHandler(filters.Regex("Погода в Запоріжжі"), weather_menu))
    application.add_handler(MessageHandler(filters.Regex("^Зараз$"), weather_now))
    application.add_handler(MessageHandler(filters.Regex("^3 дні$"), weather_3days))
    application.add_handler(MessageHandler(filters.Regex("Назад"), start))

    application.bot.set_webhook(f"{RENDER_URL}/{BOT_TOKEN}")

    threading.Thread(target=watchdog, daemon=True).start()

    print("✅ Webhook bot started")
    app.run(host="0.0.0.0", port=port)
