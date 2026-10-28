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
# Токен Яндекс.Диска теперь прямо в коде
YANDEX_TOKEN = "y0__wgBELWr7MIHGNuWAyCsvq7BGTDq4puDCH-DErd6M12ptPH6G-hTU0f8qayp"
ADMIN_ID = 6597229121

# Если переменная окружения не задана, принудительно используем папку для BotHost
DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except PermissionError:
    # Если вдруг запускаем локально и нет прав на /app, используем текущую папку
    DATA_DIR = "data"
    os.makedirs(DATA_DIR, exist_ok=True)

BUGS_ARCHIVE_PATH = "Bugs.zip" 
LOCAL_IMAGE_DIR = os.path.join(DATA_DIR, "bug_images")

# Пути к базам данных
USERS_FILE = os.path.join(DATA_DIR, "Users.csv")
SULKI_FILE = os.path.join(DATA_DIR, "Sulki.csv")
EX_FILE = os.path.join(DATA_DIR, "ex.csv")
BUGS_LIST_FILE = os.path.join(DATA_DIR, "bugs_list.json")

# Кулдаун (в часах)
COOLDOWN_HOURS = 2

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Работа с Яндекс.Диском и картинками ---
def download_and_extract_bugs():
    os.makedirs(LOCAL_IMAGE_DIR, exist_ok=True)
    meta_url = "https://cloud-api.yandex.net/v1/disk/resources"
    headers = {"Authorization": f"OAuth {YANDEX_TOKEN}"}
    params = {"path": BUGS_ARCHIVE_PATH}
    
    try:
        logger.info("Запрос к API Яндекс.Диска...")
        resp = requests.get(meta_url, headers=headers, params=params)
        resp.raise_for_status()
        meta = resp.json()
        
        download_href = meta.get("file")
        if not download_href:
            dl_url = "https://cloud-api.yandex.net/v1/disk/resources/download"
            dl_resp = requests.get(dl_url, headers=headers, params=params)
            dl_resp.raise_for_status()
            download_href = dl_resp.json().get("href")

        if not download_href:
            logger.error("Не удалось получить ссылку для скачивания Bugs.zip")
            return

        logger.info("Скачивание Bugs.zip...")
        file_resp = requests.get(download_href)
        file_resp.raise_for_status()
        
        with zipfile.ZipFile(io.BytesIO(file_resp.content)) as z:
            z.extractall(LOCAL_IMAGE_DIR)
        logger.info(f"Картинки жуков успешно распакованы в {LOCAL_IMAGE_DIR}")
        
        bugs = [f.split('.')[0] for f in os.listdir(LOCAL_IMAGE_DIR) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        with open(BUGS_LIST_FILE, "w", encoding="utf-8") as f:
            json.dump(bugs, f, ensure_ascii=False)
        logger.info(f"Сформирован список из {len(bugs)} жуков.")
            
    except Exception as e:
        logger.error(f"Ошибка при работе с Яндекс.Диском: {e}")

def get_bug_list():
    if os.path.exists(BUGS_LIST_FILE):
        with open(BUGS_LIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return ["Жук-пожарник", "Жук-носорог", "Жук-олень", "Колорадский жук"]

def get_bug_image_path(bug_name):
    for ext in ['.png', '.jpg', '.jpeg']:
        path = os.path.join(LOCAL_IMAGE_DIR, f"{bug_name}{ext}")
        if os.path.exists(path):
            return path
    return None

# --- Работа с CSV ---
def init_csv_files():
    if not os.path.exists(USERS_FILE):
        pd.DataFrame(columns=["user_id", "username", "chat_id", "collection_json", "last_command_time"]).to_csv(USERS_FILE, index=False)
    if not os.path.exists(SULKI_FILE):
        pd.DataFrame(columns=["ref_link", "chat_id", "user_id", "created_at"]).to_csv(SULKI_FILE, index=False)
    if not os.path.exists(EX_FILE):
        pd.DataFrame(columns=["timestamp", "user_id", "chat_id", "action", "bug_name"]).to_csv(EX_FILE, index=False)

def load_users(): return pd.read_csv(USERS_FILE)
def save_users(df): df.to_csv(USERS_FILE, index=False)
def load_sulki(): return pd.read_csv(SULKI_FILE)
def save_sulki(df): df.to_csv(SULKI_FILE, index=False)

def log_event(user_id, chat_id, action, bug_name=""):
    df = pd.read_csv(EX_FILE)
    new_row = {"timestamp": datetime.now().isoformat(), "user_id": user_id, "chat_id": chat_id, "action": action, "bug_name": bug_name}
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_csv(EX_FILE, index=False)

def add_bug_to_user(user_id, username, chat_id, bug_name):
    users = load_users()
    user_row = users[(users['user_id'] == user_id) & (users['chat_id'] == chat_id)]
    
    if user_row.empty:
        collection = {bug_name: 1}
        new_row = {"user_id": user_id, "username": username, "chat_id": chat_id, "collection_json": json.dumps(collection, ensure_ascii=False), "last_command_time": datetime.now().isoformat()}
        users = pd.concat([users, pd.DataFrame([new_row])], ignore_index=True)
    else:
        idx = user_row.index[0]
        current_collection = json.loads(users.at[idx, 'collection_json'])
        current_collection[bug_name] = current_collection.get(bug_name, 0) + 1
        users.at[idx, 'collection_json'] = json.dumps(current_collection, ensure_ascii=False)
        users.at[idx, 'last_command_time'] = datetime.now().isoformat()
    save_users(users)

# --- Логика игры ---
async def bugs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    user_id = user.id
    chat_id = chat.id
    
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("Эта команда работает только в группах! Добавьте меня в группу и попробуйте снова.")
        return

    users = load_users()
    user_row = users[(users['user_id'] == user_id) & (users['chat_id'] == chat_id)]
    
    if not user_row.empty:
        last_time_str = user_row.iloc[0]['last_command_time']
        if pd.notna(last_time_str):
            last_time = datetime.fromisoformat(last_time_str)
            if datetime.now() - last_time < timedelta(hours=COOLDOWN_HOURS):
                remaining = timedelta(hours=COOLDOWN_HOURS) - (datetime.now() - last_time)
                await update.message.reply_text(f"⏳ Кулдаун! Следующий жук через {remaining.seconds // 3600} ч. { (remaining.seconds // 60) % 60 } мин.")
                return

    bug_list = get_bug_list()
    if not bug_list:
        await update.message.reply_text("База жуков пуста. Обратитесь к администратору.")
        return
    
    random_bug = random.choice(bug_list)
    add_bug_to_user(user_id, user.username or user.first_name, chat_id, random_bug)
    log_event(user_id, chat_id, "bugs_command", random_bug)
    
    image_path = get_bug_image_path(random_bug)
    caption = f"🎉 {user.mention_html()}, ты поймал **{random_bug}**!\n\nОн добавлен в твою коллекцию."
    
    if image_path and os.path.exists(image_path):
        with open(image_path, 'rb') as photo:
            await update.message.reply_photo(photo=photo, caption=caption, parse_mode='HTML')
    else:
        await update.message.reply_text(caption, parse_mode='HTML')
    
    ref_link = f"https://t.me/{context.bot.username}?start={user_id}"
    keyboard = [[InlineKeyboardButton("📤 Поделиться ссылкой", url=f"https://t.me/share/url?url={ref_link}&text=Присоединяйся к охоте на жуков!")]]
    await update.message.reply_text("Приглашай друзей и получай бонусных жуков!", reply_markup=InlineKeyboardMarkup(keyboard))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    if context.args and chat.type == 'private':
        referrer_id = context.args[0]
        try: referrer_id = int(referrer_id)
        except ValueError: referrer_id = None
        
        if referrer_id and referrer_id != user.id:
            sulki = load_sulki()
            if not ((sulki['user_id'] == referrer_id) & (sulki['ref_link'] == str(referrer_id))).any():
                new_row = {"ref_link": str(referrer_id), "chat_id": 0, "user_id": referrer_id, "created_at": datetime.now().isoformat()}
                sulki = pd.concat([sulki, pd.DataFrame([new_row])], ignore_index=True)
                save_sulki(sulki)
            await update.message.reply_text(f"👋 Привет, {user.first_name}!\nТы пришёл по приглашению. Добавь меня в группу, и твой друг получит бонус!")
            return
    
    await update.message.reply_text(f"👋 Привет, {user.first_name}!\nЯ бот для коллекционирования жуков.\nДобавь меня в группу и используй /bugs, чтобы поймать жука!")

async def new_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']: return
    
    sulki = load_sulki()
    pending = sulki[sulki['chat_id'] == 0]
    
    if not pending.empty:
        for idx, row in pending.iterrows():
            referrer_id = row['user_id']
            users = load_users()
            ref_row = users[(users['user_id'] == referrer_id) & (users['chat_id'] == chat.id)]
            if not ref_row.empty:
                bug_list = get_bug_list()
                for _ in range(3):
                    add_bug_to_user(referrer_id, "referrer", chat.id, random.choice(bug_list))
                
                group_users = users[users['chat_id'] == chat.id]
                for g_idx in group_users.index:
                    users.at[g_idx, 'last_command_time'] = (datetime.now() - timedelta(hours=COOLDOWN_HOURS + 1)).isoformat()
                save_users(users)
            
            sulki.at[idx, 'chat_id'] = chat.id
        save_sulki(sulki)
        await update.message.reply_text("🎁 Реферальная программа активирована! Пригласивший получил бонусных жуков, а кулдаун в группе сброшен.")

async def ex_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ У вас нет прав для этой команды.")
        return
    
    ex_df = pd.read_csv(EX_FILE)
    users_df = load_users()
    text = (
        f"📊 **Аналитика бота**\n\n"
        f"🔹 Всего нажатий /bugs: {len(ex_df[ex_df['action'] == 'bugs_command'])}\n"
        f"🔹 Уникальных пользователей: {ex_df[ex_df['action'] == 'bugs_command']['user_id'].nunique()}\n"
        f"🔹 Уникальных групп: {ex_df[ex_df['action'] == 'bugs_command']['chat_id'].nunique()}\n"
        f"🔹 Всего записей в Users: {len(users_df)}\n"
        f"🔹 Записей в Sulki: {len(load_sulki())}\n"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

def main():
    if not BOT_TOKEN:
        print("ОШИБКА: Переменная BOT_TOKEN не найдена!")
        return
    
    init_csv_files()
    download_and_extract_bugs()
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bugs", bugs_command))
    app.add_handler(CommandHandler("ex", ex_command))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_member))
    
    print("Бот запущен...")
    app.run_polling()

if __name__ == '__main__':
    main()
