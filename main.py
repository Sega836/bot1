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
YANDEX_TOKEN = "y0__wgBELWr7MIHGNuWAyCsvq7BGTDq4puDCH-DErd6M12ptPH6G-hTU0f8qayp"
ADMIN_ID = 6597229121

DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except PermissionError:
    DATA_DIR = "data"
    os.makedirs(DATA_DIR, exist_ok=True)

BUGS_ARCHIVE_PATH = "Bugs.zip" 
LOCAL_IMAGE_DIR = os.path.join(DATA_DIR, "bug_images")

USERS_FILE = os.path.join(DATA_DIR, "Users.csv")
SULKI_FILE = os.path.join(DATA_DIR, "Sulki.csv")
EX_FILE = os.path.join(DATA_DIR, "ex.csv")
BUGS_LIST_FILE = os.path.join(DATA_DIR, "bugs_list.json")

COOLDOWN_HOURS = 2

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Работа с Яндекс.Диском и картинками ---
def download_and_extract_bugs():
    print("\n" + "="*40)
    print("🚀 [ЛОГ] ЗАПУСК ЗАГРУЗКИ ЖУКОВ С ЯНДЕКС.ДИСКА")
    print("="*40)
    
    os.makedirs(LOCAL_IMAGE_DIR, exist_ok=True)
    meta_url = "https://cloud-api.yandex.net/v1/disk/resources"
    headers = {"Authorization": f"OAuth {YANDEX_TOKEN}"}
    params = {"path": BUGS_ARCHIVE_PATH}
    
    try:
        print(f"🔍 [ЛОГ] Запрос метаданных файла '{BUGS_ARCHIVE_PATH}'...")
        resp = requests.get(meta_url, headers=headers, params=params)
        
        if resp.status_code != 200:
            print(f"❌ [ЛОГ ОШИБКА] Яндекс.Диск вернул код {resp.status_code}. Ответ: {resp.text}")
            return
            
        meta = resp.json()
        download_href = meta.get("file")
        
        if not download_href:
            print("🔄 [ЛОГ] Ссылка 'file' не найдена, запрашиваем через endpoint /download...")
            dl_url = "https://cloud-api.yandex.net/v1/disk/resources/download"
            dl_resp = requests.get(dl_url, headers=headers, params=params)
            dl_resp.raise_for_status()
            download_href = dl_resp.json().get("href")

        if not download_href:
            print("❌ [ЛОГ ОШИБКА] Не удалось получить ссылку для скачивания архива.")
            return

        print("📥 [ЛОГ] Скачивание архива Bugs.zip...")
        file_resp = requests.get(download_href)
        file_resp.raise_for_status()
        print(f"✅ [ЛОГ] Архив скачан. Размер: {len(file_resp.content)} байт.")
        
        print(f"🧹 [ЛОГ] Очистка старой папки {LOCAL_IMAGE_DIR}...")
        for root, dirs, files in os.walk(LOCAL_IMAGE_DIR, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))

        print("📦 [ЛОГ] Распаковка архива...")
        with zipfile.ZipFile(io.BytesIO(file_resp.content)) as z:
            z.extractall(LOCAL_IMAGE_DIR)
        
        print("🔎 [ЛОГ] Поиск картинок во всех папках...")
        bugs = []
        for root, dirs, files in os.walk(LOCAL_IMAGE_DIR):
            for file in files:
                if file.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    bug_name = os.path.splitext(file)[0]
                    bugs.append(bug_name)
                    
        bugs = list(set(bugs))
        
        with open(BUGS_LIST_FILE, "w", encoding="utf-8") as f:
            json.dump(bugs, f, ensure_ascii=False)
            
        print(f"🎉 [ЛОГ] УСПЕХ! Найдено уникальных жуков: {len(bugs)}")
        if len(bugs) > 0:
            print(f"🐞 [ЛОГ] Примеры названий: {bugs[:5]}")
        else:
            print("⚠️ [ЛОГ ВНИМАНИЕ] Картинок не найдено! Возможно, архив пуст или внутри нет файлов .png/.jpg")
        print("="*40 + "\n")
            
    except Exception as e:
        print(f"❌ [ЛОГ ОШИБКА] Исключение при работе с Яндекс.Диском: {e}")
        print("="*40 + "\n")

def get_bug_list():
    if os.path.exists(BUGS_LIST_FILE):
        with open(BUGS_LIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def get_bug_image_path(bug_name):
    for root, dirs, files in os.walk(LOCAL_IMAGE_DIR):
        for file in files:
            if os.path.splitext(file)[0] == bug_name and file.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                return os.path.join(root, file)
    return None

# --- Работа с CSV ---
def init_csv_files():
    print(f"📂 [ЛОГ] Проверка баз данных в папке: {DATA_DIR}")
    if not os.path.exists(USERS_FILE):
        print("📝 [ЛОГ] Создание Users.csv...")
        pd.DataFrame(columns=["user_id", "username", "chat_id", "collection_json", "last_command_time"]).to_csv(USERS_FILE, index=False)
    if not os.path.exists(SULKI_FILE):
        print("📝 [ЛОГ] Создание Sulki.csv...")
        pd.DataFrame(columns=["ref_link", "chat_id", "user_id", "created_at"]).to_csv(SULKI_FILE, index=False)
    if not os.path.exists(EX_FILE):
        print("📝 [ЛОГ] Создание ex.csv...")
        pd.DataFrame(columns=["timestamp", "user_id", "chat_id", "action", "bug_name"]).to_csv(EX_FILE, index=False)

# (Функции load_users, save_users, load_sulki, save_sulki, log_event, add_bug_to_user остаются без изменений)
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
    
    print(f"👉 [ЛОГ] Получена команда /bugs от {user.first_name} (@{user.username}) в чате {chat.title or chat.type} ({chat_id})")
    
    if chat.type not in ['group', 'supergroup']:
        print("⚠️ [ЛОГ] Команда вызвана не в группе. Отклонено.")
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
                print(f"⏳ [ЛОГ] У пользователя {user_id} кулдаун. Осталось: {remaining}")
                await update.message.reply_text(f"⏳ Кулдаун! Следующий жук через {remaining.seconds // 3600} ч. { (remaining.seconds // 60) % 60 } мин.")
                return

    bug_list = get_bug_list()
    if not bug_list:
        print("❌ [ЛОГ] База жуков пуста, нечего выдавать!")
        await update.message.reply_text("База жуков пуста. Обратитесь к администратору.")
        return
    
    random_bug = random.choice(bug_list)
    print(f"🎲 [ЛОГ] Пользователю {user_id} выпал жук: {random_bug}")
    add_bug_to_user(user_id, user.username or user.first_name, chat_id, random_bug)
    log_event(user_id, chat_id, "bugs_command", random_bug)
    
    image_path = get_bug_image_path(random_bug)
    caption = f"🎉 {user.mention_html()}, ты поймал **{random_bug}**!\n\nОн добавлен в твою коллекцию."
    
    if image_path and os.path.exists(image_path):
        print(f"🖼️ [ЛОГ] Отправка картинки: {image_path}")
        try:
            with open(image_path, 'rb') as photo:
                await update.message.reply_photo(photo=photo, caption=caption, parse_mode='HTML')
        except Exception as e:
            print(f"❌ [ЛОГ ОШИБКА] Ошибка при отправке фото: {e}")
            await update.message.reply_text(caption + "\n(Не удалось загрузить фото жука)", parse_mode='HTML')
    else:
        print(f"⚠️ [ЛОГ] Картинка для '{random_bug}' не найдена на диске.")
        await update.message.reply_text(caption, parse_mode='HTML')
    
    ref_link = f"https://t.me/{context.bot.username}?start={user_id}"
    keyboard = [[InlineKeyboardButton("📤 Поделиться ссылкой", url=f"https://t.me/share/url?url={ref_link}&text=Присоединяйся к охоте на жуков!")]]
    await update.message.reply_text("Приглашай друзей и получай бонусных жуков!", reply_markup=InlineKeyboardMarkup(keyboard))

# (Остальные обработчики start, new_chat_member, ex_command остаются без изменений логики)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    print(f"👉 [ЛОГ] Команда /start от {user.first_name} (ID: {user.id}) в {chat.type}")
    
    if context.args and chat.type == 'private':
        referrer_id = context.args[0]
        try: referrer_id = int(referrer_id)
        except ValueError: referrer_id = None
        
        if referrer_id and referrer_id != user.id:
            print(f"🔗 [ЛОГ] Переход по реферальной ссылке от {referrer_id}")
            sulki = load_sulki()
            if not ((sulki['user_id'] == referrer_id) & (sulki['ref_link'] == str(referrer_id))).any():
                new_row = {"ref_link": str(referrer_id), "chat_id": 0, "user_id": referrer_id, "created_at": datetime.now().isoformat()}
                sulki = pd.concat([sulki, pd.DataFrame([new_row])], ignore_index=True)
                save_sulki(sulki)
                print(f"💾 [ЛОГ] Реферальная ссылка от {referrer_id} сохранена в Sulki.csv")
            await update.message.reply_text(f"👋 Привет, {user.first_name}!\nТы пришёл по приглашению. Добавь меня в группу, и твой друг получит бонус!")
            return
    
    await update.message.reply_text(f"👋 Привет, {user.first_name}!\nЯ бот для коллекционирования жуков.\nДобавь меня в группу и используй /bugs, чтобы поймать жука!")

async def new_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']: return
    print(f"👉 [ЛОГ] Бота добавили в группу {chat.title} ({chat.id})")
    
    sulki = load_sulki()
    pending = sulki[sulki['chat_id'] == 0]
    
    if not pending.empty:
        print(f"🎁 [ЛОГ] Найдено {len(pending)} ожидающих реферальных наград для этой группы.")
        # ... (логика наград) ...

async def ex_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        print(f"⛔ [ЛОГ] Попытка вызова /ex пользователем {update.effective_user.id} (не админ)")
        await update.message.reply_text("⛔ У вас нет прав для этой команды.")
        return
    
    print(f"📊 [ЛОГ] Админ запросил аналитику.")
    # ... (логика аналитики) ...
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
        print("❌ ОШИБКА: Переменная BOT_TOKEN не найдена!")
        return
    
    print("\n" + "="*40)
    print("🤖 ЗАПУСК БОТА...")
    print("="*40)
    
    init_csv_files()
    download_and_extract_bugs()
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bugs", bugs_command))
    app.add_handler(CommandHandler("ex", ex_command))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_member))
    
    print("✅ Бот успешно запущен и готов к работе! Ожидание команд...\n")
    app.run_polling()

if __name__ == '__main__':
    main()
