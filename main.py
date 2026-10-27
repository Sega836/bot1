import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Настройка логирования (чтобы видеть ошибки в логах BotHost)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋\n"
        f"Я тестовый бот. Напиши мне что-нибудь, и я повторю это."
    )

# Команда /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Доступные команды:\n/start - Приветствие\n/help - Помощь")

# Эхо-функция (отвечает на любой текст)
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Ты написал: {update.message.text}")

def main():
    # Получаем токен из переменной окружения BOT_TOKEN (BotHost передает его туда)
    token = os.environ.get("BOT_TOKEN")
    
    if not token:
        print("ОШИБКА: Переменная окружения BOT_TOKEN не найдена!")
        print("Убедитесь, что вы указали токен в настройках бота на BotHost.")
        return

    # Создаем приложение
    app = ApplicationBuilder().token(token).build()

    # Добавляем обработчики команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    
    # Обработчик всех текстовых сообщений (кроме команд)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    # Запускаем бота
    print("Бот запущен и готов к работе...")
    app.run_polling()

if __name__ == '__main__':
    main()
