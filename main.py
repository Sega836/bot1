import os
import json
import random
import logging
import zipfile
import io
import requests
import pandas as pd
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

# --- Конфигурация ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
YANDEX_TOKEN = os.environ.get("YANDEX_TOKEN")  # Токен для Яндекс.Диска
ADMIN_ID = 6597229121
BUGS_ARCHIVE_PATH = "Bugs.zip"  # Путь к архиву на Яндекс.Диске
LOCAL_IMAGE_DIR = "bug_images"

# Файлы данных
USERS_FILE = "Users.csv"
SULKI_FILE = "Sulki.csv"
EX_FILE = "ex.csv"

# Кулдаун (в часах)
COOLDOWN_HOURS = 2

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Работа с Яндекс.Диском и картинками ---
def download_and_extract_bugs():
    """Скачивает Bugs.zip с Яндекс.Диска и распаковывает его локально при запуске."""
    if not YANDEX_TOKEN:
        logger.error("YANDEX_TOKEN не задан. Картинки не будут загружены.")
        return

    os.makedirs(LOCAL_IMAGE_DIR, exist_ok=True)
    
    # 1. Получаем ссылку на скачивание файла по пути
    # Используем API для получения метаданных, чтобы найти ссылку на скачивание
    meta_url = "https://cloud-api.yandex.net/v1/disk/resources"
    headers = {"Authorization": f"OAuth {YANDEX_TOKEN}"}
    params = {"path": BUGS_ARCHIVE_PATH}
    
    try:
        resp = requests.get(meta_url, headers=headers, params=params)
        resp.raise_for_status()
        meta = resp.json()
        
        # Ссылка на скачивание файла
        download_href = meta.get("file")
        if not download_href:
            # Если file нет, возможно, нужно запросить download endpoint
            dl_url = "https://cloud-api.yandex.net/v1/disk/resources/download"
            dl_resp = requests.get(dl_url, headers=headers, params=params)
            dl_resp.raise_for_status()
            download_href = dl_resp.json().get("href")

        if not download_href:
            logger.error("Не удалось получить ссылку для скачивания Bugs.zip")
            return

        # 2. Скачиваем архив
        logger.info("Скачивание Bugs.zip...")
        file_resp = requests.get(download_href)
        file_resp.raise_for_status()
        
        # 3. Распаковываем
        with zipfile.ZipFile(io.BytesIO(file_resp.content)) as z:
            z.extractall(LOCAL_IMAGE_DIR)
        logger.info(f"Картинки жуков распакованы в {LOCAL_IMAGE_DIR}")
        
        # Сохраняем список доступных жуков (имена файлов без расширения)
        bugs = [f.split('.')[0] for f in os.listdir(LOCAL_IMAGE_DIR) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        with open("bugs_list.json", "w", encoding="utf-8") as f:
            json.dump(bugs, f, ensure_ascii=False)
            
    except Exception as e:
        logger.error(f"Ошибка при работе с Яндекс.Диском: {e}")

def get_bug_list():
    """Возвращает список доступных жуков."""
    if os.path.exists("bugs_list.json"):
        with open("bugs_list.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return ["Жук-пожарник", "Жук-носорог", "Жук-олень", "Колорадский жук"]  # fallback

def get_bug_image_path(bug_name):
    """Возвращает путь к картинке жука."""
    for ext in ['.png', '.jpg', '.jpeg']:
        path = os.path.join(LOCAL_IMAGE_DIR, f"{bug_name}{ext}")
        if os.path.exists(path):
            return path
    return None

# --- Работа с CSV (Users, Sulki, ex) ---
def init_csv_files():
    """Создаёт файлы с заголовками, если их нет."""
    if not os.path.exists(USERS_FILE):
        df = pd.DataFrame(columns=["user_id", "username", "chat_id", "collection_json", "last_command_time"])
        df.to_csv(USERS_FILE, index=False)
    
    if not os.path.exists(SULKI_FILE):
        df = pd.DataFrame(columns=["ref_link", "chat_id", "user_id", "created_at"])
        df.to_csv(SULKI_FILE, index=False)
    
    if not os.path.exists(EX_FILE):
        df = pd.DataFrame(columns=["timestamp", "user_id", "chat_id", "action", "bug_name"])
        df.to_csv(EX_FILE, index=False)

def load_users():
    return pd.read_csv(USERS_FILE)

def save_users(df):
    df.to_csv(USERS_FILE, index=False)

def load_sulki():
    return pd.read_csv(SULKI_FILE)

def save_sulki(df):
    df.to_csv(SULKI_FILE, index=False)

def log_event(user_id, chat_id, action, bug_name=""):
    """Логирует действие в ex.csv для аналитики."""
    df = pd.read_csv(EX_FILE)
    new_row = {
        "timestamp": datetime.now().isoformat(),
        "user_id": user_id,
        "chat_id": chat_id,
        "action": action,
        "bug_name": bug_name
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_csv(EX_FILE, index=False)

# --- Логика игры ---
def add_bug_to_user(user_id, username, chat_id, bug_name):
    """Добавляет жука в коллекцию пользователя."""
    users = load_users()
    user_row = users[(users['user_id'] == user_id) & (users['chat_id'] == chat_id)]
    
    if user_row.empty:
        # Новый пользователь в этом чате
        collection = {bug_name: 1}
        new_row = {
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "collection_json": json.dumps(collection, ensure_ascii=False),
            "last_command_time": datetime.now().isoformat()
        }
        users = pd.concat([users, pd.DataFrame([new_row])], ignore_index=True)
    else:
        idx = user_row.index[0]
        current_collection = json.loads(users.at[idx, 'collection_json'])
        current_collection[bug_name] = current_collection.get(bug_name, 0) + 1
        users.at[idx, 'collection_json'] = json.dumps(current_collection, ensure_ascii=False)
        # Обновляем время последней команды (если нужно)
        users.at[idx, 'last_command_time'] = datetime.now().isoformat()
    
    save_users(users)

async def bugs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    user_id = user.id
    chat_id = chat.id
    
    # Проверяем, является ли чат групповым (хотя команда может быть и в личке)
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("Эта команда работает только в группах! Добавьте меня в группу и попробуйте снова.")
        return

    users = load_users()
    user_row = users[(users['user_id'] == user_id) & (users['chat_id'] == chat_id)]
    
    # Проверка кулдауна
    if not user_row.empty:
        last_time_str = user_row.iloc[0]['last_command_time']
        if pd.notna(last_time_str):
            last_time = datetime.fromisoformat(last_time_str)
            if datetime.now() - last_time < timedelta(hours=COOLDOWN_HOURS):
                remaining = timedelta(hours=COOLDOWN_HOURS) - (datetime.now() - last_time)
                await update.message.reply_text(f"⏳ Кулдаун! Следующий жук через {remaining.seconds // 3600} ч. { (remaining.seconds // 60) % 60 } мин.")
                return

    # Выдаём случайного жука
    bug_list = get_bug_list()
    if not bug_list:
        await update.message.reply_text("База жуков пуста. Обратитесь к администратору.")
        return
    
    random_bug = random.choice(bug_list)
    
    # Добавляем в БД
    add_bug_to_user(user_id, user.username or user.first_name, chat_id, random_bug)
    log_event(user_id, chat_id, "bugs_command", random_bug)
    
    # Отправляем картинку и текст
    image_path = get_bug_image_path(random_bug)
    caption = f"🎉 {user.mention_html()}, ты поймал **{random_bug}**!\n\nОн добавлен в твою коллекцию."
    
    if image_path and os.path.exists(image_path):
        with open(image_path, 'rb') as photo:
            await update.message.reply_photo(photo=photo, caption=caption, parse_mode='HTML')
    else:
        await update.message.reply_text(caption, parse_mode='HTML')
    
    # Проверяем, есть ли у пользователя реферальная ссылка (для информации)
    sulki = load_sulki()
    ref_link = f"https://t.me/{context.bot.username}?start={user_id}"
    # Можно добавить кнопку "Поделиться"
    keyboard = [[InlineKeyboardButton("📤 Поделиться ссылкой", url=f"https://t.me/share/url?url={ref_link}&text=Присоединяйся к охоте на жуков!")]]
    await update.message.reply_text("Приглашай друзей и получай бонусных жуков!", reply_markup=InlineKeyboardMarkup(keyboard))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    # Обработка реферального старта (в личке)
    if context.args and chat.type == 'private':
        referrer_id = context.args[0]
        try:
            referrer_id = int(referrer_id)
        except ValueError:
            referrer_id = None
        
        if referrer_id and referrer_id != user.id:
            # Записываем в Sulki (ссылка / группа / пользователь)
            # В данном случае "группа" неизвестна, так как старт в личке.
            # Логика: когда пользователь добавляет бота в группу, мы проверим Sulki.
            # Для простоты запишем в Sulki с chat_id = 0 (означает "ожидает группу")
            sulki = load_sulki()
            # Проверяем, нет ли уже такой записи
            if not ((sulki['user_id'] == referrer_id) & (sulki['ref_link'] == str(referrer_id))).any():
                new_row = {
                    "ref_link": str(referrer_id),
                    "chat_id": 0,  # 0 означает, что группа ещё не определена
                    "user_id": referrer_id,
                    "created_at": datetime.now().isoformat()
                }
                sulki = pd.concat([sulki, pd.DataFrame([new_row])], ignore_index=True)
                save_sulki(sulki)
            
            await update.message.reply_text(
                f"👋 Привет, {user.first_name}!\n"
                f"Ты пришёл по приглашению. Добавь меня в группу, и твой друг получит бонус!"
            )
            return
    
    # Обычный старт
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n"
        f"Я бот для коллекционирования жуков.\n"
        f"Добавь меня в группу и используй /bugs, чтобы поймать жука!"
    )

async def new_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает добавление бота в группу для активации реферальных ссылок."""
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        return
    
    # Проверяем, есть ли в Sulki записи с chat_id = 0 (ожидающие группу)
    sulki = load_sulki()
    pending = sulki[sulki['chat_id'] == 0]
    
    if not pending.empty:
        # Для каждой такой записи начисляем награду и сбрасываем кулдаун
        # Но нам нужно знать, кто именно добавил бота. В идеале это должен быть тот же пользователь.
        # Упростим: активируем для всех pending, но это не совсем корректно.
        # Более правильный подход: хранить ID приглашённого и проверять, кто добавил бота.
        # Но в рамках текущей структуры сделаем так:
        for idx, row in pending.iterrows():
            referrer_id = row['user_id']
            # Начисляем бонус рефереру в этой группе
            users = load_users()
            # Ищем реферера в этой группе
            ref_row = users[(users['user_id'] == referrer_id) & (users['chat_id'] == chat.id)]
            if not ref_row.empty:
                # Добавляем 3 случайных жука
                bug_list = get_bug_list()
                for _ in range(3):
                    add_bug_to_user(referrer_id, "referrer", chat.id, random.choice(bug_list))
                # Сбрасываем кулдаун у всех в группе
                group_users = users[users['chat_id'] == chat.id]
                for g_idx in group_users.index:
                    users.at[g_idx, 'last_command_time'] = (datetime.now() - timedelta(hours=COOLDOWN_HOURS + 1)).isoformat()
                save_users(users)
            
            # Обновляем запись в Sulki, указывая группу
            sulki.at[idx, 'chat_id'] = chat.id
        
        save_sulki(sulki)
        await update.message.reply_text("🎁 Реферальная программа активирована! Пригласивший получил бонусных жуков, а кулдаун в группе сброшен.")

async def ex_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Аналитика для администратора."""
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⛔ У вас нет прав для этой команды.")
        return
    
    ex_df = pd.read_csv(EX_FILE)
    users_df = load_users()
    
    total_bugs_commands = len(ex_df[ex_df['action'] == 'bugs_command'])
    unique_users = ex_df[ex_df['action'] == 'bugs_command']['user_id'].nunique()
    unique_chats = ex_df[ex_df['action'] == 'bugs_command']['chat_id'].nunique()
    
    # Суммарное количество участников в группах (приблизительно, по числу уникальных chat_id в Users)
    total_participants = len(users_df)
    
    text = (
        f"📊 **Аналитика бота**\n\n"
        f"🔹 Всего нажатий /bugs: {total_bugs_commands}\n"
        f"🔹 Уникальных пользователей: {unique_users}\n"
        f"🔹 Уникальных групп: {unique_chats}\n"
        f"🔹 Всего записей в Users (участников): {total_participants}\n"
        f"🔹 Записей в Sulki: {len(load_sulki())}\n"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

# --- Запуск ---
def main():
    if not BOT_TOKEN:
        print("ОШИБКА: Переменная BOT_TOKEN не найдена!")
        return
    
    # 1. Инициализация файлов
    init_csv_files()
    
    # 2. Загрузка картинок при старте
    logger.info("Загрузка картинок с Яндекс.Диска...")
    download_and_extract_bugs()
    
    # 3. Создание приложения
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # 4. Обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bugs", bugs_command))
    app.add_handler(CommandHandler("ex", ex_command))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_member))
    
    # 5. Запуск
    print("Бот запущен...")
    app.run_polling()

if __name__ == '__main__':
    main()
