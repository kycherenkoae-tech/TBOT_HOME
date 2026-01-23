import os
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Flask, request
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ===== CONFIG =====
BOT_TOKEN = os.environ.get("BOT_TOKEN")
RENDER_URL = os.environ.get("RENDER_URL")  # https://tbot-home.onrender.com
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{RENDER_URL}{WEBHOOK_PATH}"

WEATHER_KEY = os.environ.get("WEATHER_KEY")
OFFLINE_SECONDS = 620
CHECK_INTERVAL = 300
KYIV = ZoneInfo("Europe/Kyiv")

# ===== STATE =====
last_esp_time = None
is_offline = True
history = []
users = set()

app = Flask(__name__)
application = ApplicationBuilder().token(BOT_TOKEN).build()

# ===== HELPERS =====
def kyiv_now():
    return datetime.now(KYIV)

def cleanup_history():
    """очищаємо старі дані >24 годин"""
    global history
    cutoff = kyiv_now() - timedelta(hours=24)
    history = [d for d in history if d["time"] >= cutoff]

async def notify_all(text: str):
    for chat_id in application.bot_data.get("users", set()):
        try:
            await application.bot.send_message(chat_id, text)
        except:
            pass

async def esp_checker():
    global is_offline
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        if last_esp_time:
            delta = (kyiv_now() - last_esp_time).total_seconds()
            if delta > OFFLINE_SECONDS and not is_offline:
                is_offline = True
                await notify_all("🔴 ESP32 offline")
            elif delta <= OFFLINE_SECONDS and is_offline:
                is_offline = False
                await notify_all("🟢 ESP32 online")

# ===== FLASK: ESP UPDATE =====
@app.route("/update")
def esp_update():
    global last_esp_time, is_offline

    try:
        t = round(float(request.args.get("t")), 1)
        h = round(float(request.args.get("h")), 1)
        p = round(float(request.args.get("p")), 1)
    except:
        return "BAD DATA", 400

    now = kyiv_now()

    if is_offline and users:
        is_offline = False
        asyncio.create_task(notify_all("🟢 ESP32 online"))

    history.append({"time": now, "t": t, "h": h, "p": p})
    cleanup_history()
    last_esp_time = now

    return "OK"

@app.route(WEBHOOK_PATH, methods=["POST"])
async def webhook_handler():
    update = Update.de_json(request.get_json(force=True), application.bot)
    await application.process_update(update)
    return "OK"

@app.route("/")
def root():
    return "Bot is running"

# ===== TELEGRAM HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users.add(update.effective_chat.id)
    context.application.bot_data.setdefault("users", set()).add(update.effective_chat.id)
    kb = [["🌡 Показники ESP32"], ["📈 Графік за добу"], ["🌤 Погода Запоріжжя"]]
    await update.message.reply_text("Привіт 👋", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

async def show_esp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not history:
        await update.message.reply_text("Даних ще немає")
        return
    last = history[-1]
    await update.message.reply_text(
        f"🕒 {last['time'].strftime('%H:%M:%S')}\n"
        f"🌡 {last['t']} °C\n"
        f"💧 {last['h']} %\n"
        f"📈 {last['p']} hPa"
    )

async def graph_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not history:
        await update.message.reply_text("Немає даних для графіка")
        return

    # обрати дані сьогодні з 00:00
    now = kyiv_now()
    start_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = [d for d in history if d["time"] >= start_day]
    if not today:
        await update.message.reply_text("Немає даних за сьогодні")
        return

    times = [d["time"] for d in today]
    temps = [d["t"] for d in today]

    plt.figure()
    plt.plot(times, temps, marker="o")
    plt.xticks(rotation=45)
    plt.title("Температура ESP32 за сьогодні")
    plt.tight_layout()
    plt.savefig("esp_graph.png")
    plt.close()

    await update.message.reply_photo(open("esp_graph.png", "rb"))

async def weather_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [["Зараз", "3 дні"], ["Назад"]]
    await update.message.reply_text("Оберіть:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

async def weather_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = f"https://api.openweathermap.org/data/2.5/weather?q=Zaporizhzhia,UA&appid={WEATHER_KEY}&units=metric&lang=ua"
    r = requests.get(url, timeout=10).json()
    if r.get("cod") != 200:
        await update.message.reply_text("Не вдалось отримати погоду")
        return
    await update.message.reply_text(
        f"🌤 Погода зараз:\n"
        f"🌡 {r['main']['temp']:.1f}°C\n"
        f"💧 {r['main']['humidity']}%\n"
        f"💨 {r['wind']['speed']} м/с\n"
        f"☁ {r['weather'][0]['description']}"
    )

async def weather_3days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = f"https://api.openweathermap.org/data/2.5/forecast?q=Zaporizhzhia,UA&appid={WEATHER_KEY}&units=metric&lang=ua"
    r = requests.get(url, timeout=10).json()
    if r.get("cod") != "200":
        await update.message.reply_text("Не вдалось отримати прогноз")
        return

    days = {}
    for item in r["list"]:
        date, time = item["dt_txt"].split(" ")
        temp = item["main"]["temp"]
        rain = item.get("rain", {}).get("3h", 0)
        desc = item["weather"][0]["description"]
        if date not in days:
            days[date] = {"temps": [], "rain": 0, "desc": desc}
        days[date]["temps"].append(temp)
        days[date]["rain"] += rain

    text = "🌤 Прогноз 3 дні:\n\n"
    for i, (date, info) in enumerate(days.items()):
        if i == 3: break
        text += (
            f"{date}\n"
            f"🌡 Мін: {min(info['temps']):.1f}°C  Макс: {max(info['temps']):.1f}°C\n"
            f"🌧 Опади: {info['rain']:.1f}мм\n"
            f"☁ {info['desc']}\n\n"
        )
    await update.message.reply_text(text)

# ===== REGISTER HANDLERS =====

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("esp", show_esp))
application.add_handler(CommandHandler("graph", graph_day))
application.add_handler(CommandHandler("weather", weather_menu))
application.add_handler(MessageHandler(filters.Regex("🌡 Показники ESP32"), show_esp))
application.add_handler(MessageHandler(filters.Regex("📈 Графік за добу"), graph_day))
application.add_handler(MessageHandler(filters.Regex("🌤 Погода Запоріжжя"), weather_menu))
application.add_handler(MessageHandler(filters.Regex("^Зараз$"), weather_now))
application.add_handler(MessageHandler(filters.Regex("^3 дні$"), weather_3days))

# ===== START WEBHOOK & BOT =====

async def setup_bot():
    await application.initialize()
    await application.bot.set_webhook(WEBHOOK_URL)
    await application.start()
    application.create_task(esp_checker())

asyncio.get_event_loop().run_until_complete(setup_bot())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
