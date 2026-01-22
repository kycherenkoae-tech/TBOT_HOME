import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import asyncio

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

OFFLINE_SECONDS = 310  # 5хв
CHECK_INTERVAL = 300   # 5 хв
TIMEZONE = ZoneInfo("Europe/Kiev")

# ===== STORAGE =====
last_data = None
last_seen = None
history = []
users = set()
is_offline = True

# ===== FLASK =====
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running ✅"

@app.route("/update")
def update():
    global last_data, last_seen
    try:
        t = round(float(request.args.get("t")), 1)
        h = round(float(request.args.get("h")), 1)
        p = round(float(request.args.get("p")), 1)
    except:
        return "BAD DATA", 400

    now = datetime.now(TIMEZONE)

    first_online = False
    if is_offline and users:
        first_online = True

    last_seen = now
    last_data = {"time": now, "t": t, "h": h, "p": p}
    history.append(last_data)

    # Очистка старих записів >24 год
    cutoff = now - timedelta(hours=24)
    history[:] = [d for d in history if d["time"] >= cutoff]

    if first_online:
        asyncio.get_event_loop().create_task(notify_all("🟢 ESP зʼявився онлайн"))

    return "OK"

# ===== HELPERS =====
async def notify_all(text):
    for uid in users:
        try:
            await application.bot.send_message(chat_id=uid, text=text, timeout=20)
        except:
            pass

async def esp_checker():
    global is_offline
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        if not last_seen:
            continue
        delta = datetime.now(TIMEZONE) - last_seen
        if delta.total_seconds() > OFFLINE_SECONDS and not is_offline:
            is_offline = True
            await notify_all("🔴 ESP зник (offline)")
        elif delta.total_seconds() <= OFFLINE_SECONDS and is_offline:
            is_offline = False
            await notify_all("🟢 ESP зʼявився онлайн")

# ===== TELEGRAM HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users.add(update.effective_chat.id)
    keyboard = [["🌡 Температура"], ["📈 Історія за день"], ["🌤 Погода в Запоріжжі"]]
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
        f"🕒 {d['time'].strftime('%H:%M:%S')}\n"
        f"🌡 {d['t']} °C\n"
        f"💧 {d['h']} %\n"
        f"📈 {d['p']} hPa"
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
    r = requests.get(url, timeout=15).json()
    if r.get("cod") != 200:
        await update.message.reply_text("Помилка отримання погоди 😢")
        return
    temp = r["main"]["temp"]
    feels = r["main"]["feels_like"]
    hum = r["main"]["humidity"]
    wind = r["wind"]["speed"]
    desc = r["weather"][0]["description"]
    text = (
        f"🌤 Погода зараз (Запоріжжя)\n\n"
        f"🌡 {temp:.1f}°C\n"
        f"🤍 Відчувається: {feels:.1f}°C\n"
        f"💧 Вологість: {hum}%\n"
        f"💨 Вітер: {wind} м/с\n"
        f"☁ {desc}"
    )
    await update.message.reply_text(text)

async def weather_3days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = f"https://api.openweathermap.org/data/2.5/forecast?q=Zaporizhzhia,UA&appid={WEATHER_KEY}&units=metric&lang=ua"
    r = requests.get(url, timeout=15).json()
    if r.get("cod") != "200":
        await update.message.reply_text("Помилка отримання прогнозу 😢")
        return
    days = {}
    for item in r["list"]:
        date, time = item["dt_txt"].split(" ")
        temp = item["main"]["temp"]
        desc = item["weather"][0]["description"]
        rain = item.get("rain", {}).get("3h", 0)
        if date not in days:
            days[date] = {"temps": [], "rain": 0, "noon": None, "desc": desc}
        days[date]["temps"].append(temp)
        days[date]["rain"] += rain
        if time.startswith("12"):
            days[date]["noon"] = temp
    text = "🌤 Прогноз на 3 дні\n\n"
    for i, (date, info) in enumerate(days.items()):
        if i == 3: break
        temps = info["temps"]
        avg = sum(temps) / len(temps)
        text += (
            f"📅 {date}\n"
            f"🌡 Мін: {min(temps):.1f}°C\n"
            f"🌡 Макс: {max(temps):.1f}°C\n"
            f"🌞 День: {(info['noon'] or avg):.1f}°C\n"
            f"🌧 Опади: {info['rain']:.1f} мм\n"
            f"☁ {info['desc']}\n\n"
        )
    await update.message.reply_text(text)

# ===== RUN =====
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    import threading
    threading.Thread(target=run_flask, daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).read_timeout(30).write_timeout(30).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Regex("Температура"), temperature))
    application.add_handler(MessageHandler(filters.Regex("Історія"), history_day))
    application.add_handler(MessageHandler(filters.Regex("Погода в Запоріжжі"), weather_menu))
    application.add_handler(MessageHandler(filters.Regex("^Зараз$"), weather_now))
    application.add_handler(MessageHandler(filters.Regex("^3 дні$"), weather_3days))
    application.add_handler(MessageHandler(filters.Regex("Назад"), start))

    # Старт фонової задачі перевірки ESP
    async def start_jobs():
        application.create_task(esp_checker())

    print("✅ Bot started")
    application.run_polling(on_startup=start_jobs)
