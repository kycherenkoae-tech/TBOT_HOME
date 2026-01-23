import os
import json
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Flask, request
import matplotlib.pyplot as plt

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, JobQueue

# ---------------- CONFIG ----------------
TOKEN = os.environ.get("BOT_TOKEN", "PUT_YOUR_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://tbot-home.onrender.com")
HISTORY_FILE = "history.json"
TZ = ZoneInfo("Europe/Kyiv")

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
    cleaned = [d for d in data if now - datetime.fromisoformat(d["time"]) < timedelta(hours=24)]
    save_history(cleaned)

# ---------------- TELEGRAM HANDLERS ----------------
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

async def check_esp(context: ContextTypes.DEFAULT_TYPE):
    global ESP_STATUS, LAST_CHAT_ID
    cleanup_history()
    data = load_history()
    if not data:
        return

    last_time = datetime.fromisoformat(data[-1]["time"])
    now = datetime.now(TZ)
    diff = (now - last_time).total_seconds()

    if diff < 420:
        if not ESP_STATUS:
            ESP_STATUS = True
            if LAST_CHAT_ID:
                await context.bot.send_message(LAST_CHAT_ID, "🟢 ESP32 ONLINE")
    else:
        if ESP_STATUS:
            ESP_STATUS = False
            if LAST_CHAT_ID:
                await context.bot.send_message(LAST_CHAT_ID, "🔴 ESP32 OFFLINE")

# ---------------- FLASK ----------------
app = Flask(__name__)
application = ApplicationBuilder().token(TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("graph", graph))

@app.route("/")
def home():
    return "Bot works"

@app.route("/update")
def update_esp():
    global ESP_STATUS

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

    ESP_STATUS = True
    return "OK"

@app.route(f"/webhook/{TOKEN}", methods=["POST"])
async def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, await application.bot)
    await application.process_update(update)
    return "OK"

# ---------------- MAIN ----------------
async def main():
    # Initialize application and set webhook
    await application.initialize()
    await application.bot.set_webhook(f"{WEBHOOK_URL}/webhook/{TOKEN}")

    # Start job queue
    if application.job_queue:
        application.job_queue.run_repeating(check_esp, interval=300, first=30)

    await application.start()
    print("Bot started on Render")

    # Keep alive
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    # Для запуску Flask + asyncio разом
    import nest_asyncio
    nest_asyncio.apply()

    asyncio.get_event_loop().create_task(main())
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
