import os
import logging
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("smartotc-pocket-option")

SYMBOLS = ["EUR/USD OTC", "GBP/USD OTC", "USD/JPY OTC", "CHF/NOK OTC",
           "AUD/USD OTC", "EUR/JPY OTC", "GBP/JPY OTC"]
TIMEFRAMES = ["5s", "10s", "15s", "30s", "1m"]

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Отримати сигнал", callback_data="signal")],
        [InlineKeyboardButton("📋 Історія", callback_data="history"),
         InlineKeyboardButton("👤 Профіль", callback_data="profile")],
        [InlineKeyboardButton("⭐ Premium", callback_data="premium"),
         InlineKeyboardButton("🧠 AI-аналіз", callback_data="analysis")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚡ *SmartOTC AI · Pocket Option*\\n\\n"
        "Оберіть актив і таймфрейм, щоб запросити аналіз. "
        "Бот не видає вигадані сигнали: спочатку потрібно підключити перевірене джерело OTC-котирувань.",
        reply_markup=menu(), parse_mode="Markdown")

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    if d == "signal":
        kb = [[InlineKeyboardButton(s, callback_data="symbol:"+s)] for s in SYMBOLS]
        await q.edit_message_text("Оберіть OTC-пару Pocket Option:", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith("symbol:"):
        context.user_data["symbol"] = d.split(":",1)[1]
        kb = [[InlineKeyboardButton(t, callback_data="tf:"+t)] for t in TIMEFRAMES]
        await q.edit_message_text("Оберіть таймфрейм:", reply_markup=InlineKeyboardMarkup(kb))
    elif d.startswith("tf:"):
        context.user_data["timeframe"] = d.split(":",1)[1]
        await q.edit_message_text(
            f"Пара: {context.user_data.get('symbol')}\\nТаймфрейм: {context.user_data['timeframe']}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Аналізувати", callback_data="analyze")],
                [InlineKeyboardButton("⬅️ Меню", callback_data="menu")]
            ]))
    elif d == "analyze":
        symbol = context.user_data.get("symbol", "EUR/USD OTC")
        tf = context.user_data.get("timeframe", "15s")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(API_BASE_URL + "/pocket-option/analyze",
                    params={"symbol": symbol, "timeframe": tf})
                payload = response.json()
            planned = payload.get("planned_entry_at", "не визначено")
            msg = (
                "⚠️ *Сигнал не сформовано*\\n\\n"
                f"Платформа: Pocket Option OTC\\nПара: {symbol}\\nТаймфрейм: {tf}\\n"
                f"Запланований час входу (+5 с): `{planned}`\\n\\n"
                + payload.get("message", "Джерело котирувань не перевірене.")
            )
        except Exception:
            msg = "Не вдалося зв'язатися з API SmartOTC. Перевірте, чи запущений бекенд."
        await q.edit_message_text(msg, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="menu")]]))
    elif d == "history":
        await q.edit_message_text("Історія буде активована після додавання бази даних і запису перевірених результатів.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="menu")]]))
    elif d == "profile":
        await q.edit_message_text(f"Telegram ID: `{q.from_user.id}`\\nТариф: Free (демо)",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="menu")]]))
    elif d == "premium":
        await q.edit_message_text("Premium-оплата ще не підключена. Потрібно обрати платіжного провайдера.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="menu")]]))
    elif d == "analysis":
        await q.edit_message_text("AI-аналіз активується після підключення й перевірки Pocket Option OTC-котирувань.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="menu")]]))
    elif d == "menu":
        await q.edit_message_text("⚡ *SmartOTC AI · Pocket Option*\\nОберіть дію:", reply_markup=menu(), parse_mode="Markdown")

def main():
    if not TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in Render Environment Variables")
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(on_button))
    application.run_polling()

if __name__ == "__main__":
    main()
