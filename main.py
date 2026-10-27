import os
from telegram.ext import ApplicationBuilder, CommandHandler

async def start(update, ctx):
    await update.message.reply_text("Привет! Я работаю на VPS. 🟢")

# Токен берём из переменной окружения (безопасный способ)
app = ApplicationBuilder().token(os.environ["8681162989:AAH-4ADZYt2kNQZxRiz4N5-_6_kxJjPd5JI"]).build()
app.add_handler(CommandHandler("start", start))
app.run_polling()
