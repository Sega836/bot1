import os
import json
import random
import logging
import zipfile
import io
import requests
import pandas as pd
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode

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

# --- Работа с Яндекс.Диском и картинками (без изменений) ---
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

# --- Работа с CSV (без изменений) ---
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

# --- НОВАЯ ФУНКЦИЯ: Сброс кулдауна у ВСЕХ ---
def reset_all_cooldowns():
    """Сбрасывает кулдаун абсолютно у всех игроков во всех группах."""
    users = load_users()
    if users.empty:
        return 0
    # Ставим время так, чтобы кулдаун точно прошел
    past_time = (datetime.now() - timedelta(hours=COOLDOWN_HOURS + 1)).isoformat()
    users['last_command_time'] = past_time
    save_users(users)
    return len(users)

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
    caption = f"🎉 {user.mention_html()}, ты поймал <b>{random_bug}</b>!\n\nОн добавлен в твою коллекцию."
    
    if image_path and os.path.exists(image_path):
        try:
            with open(image_path, 'rb') as photo:
                await update.message.reply_photo(photo=photo, caption=caption, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Ошибка при отправке фото: {e}")
            await update.message.reply_text(caption + "\n(Не удалось загрузить фото жука)", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(caption, parse_mode=ParseMode.HTML)
    
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
    
    await update.message.reply_text(f"👋 Привет, {user.first_name}!\nЯ бот для коллекционирования жуков.\nДобавь меня в группу и используй /bugs, чтобы поймать жука!\n\nПосмотреть все команды: /help")

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

# --- НОВАЯ КОМАНДА: HELP ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    text = (
        "🐞 <b>Охота на жуков — Справка</b>\n\n"
        "Добро пожаловать в игру! Собирай забавных жуков, соревнуйся с друзьями и приглашай новых участников.\n\n"
        "📜 <b>Доступные команды:</b>\n"
        "• /bugs — Поймать случайного жука (доступно раз в 2 часа)\n"
        "• /help — Показать это сообщение\n"
        "• /start — Перезапустить бота\n\n"
        "🎁 <b>Реферальная программа:</b>\n"
        "Используй кнопку «Поделиться ссылкой» после ловли жука. Когда твой друг перейдет по ссылке и добавит бота в <b>свою группу</b>:\n"
        "1. Ты получишь <b>3 бонусных жука</b> в коллекцию.\n"
        "2. У <b>всей группы</b> сбросится кулдаун.\n\n"
        "👑 <b>Для администратора:</b>\n"
        "• /ex — Аналитика бота\n"
        "• /ad [текст] — Сделать рассылку во все группы и сбросить кулдаун у всех\n"
    )
    
    # Если админ, можно сделать красивую кнопку для проверки аналитики
    if user.id == ADMIN_ID:
        keyboard = [[InlineKeyboardButton("📊 Открыть аналитику", callback_data="admin_ex")]]
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# --- НОВАЯ КОМАНДА: AD (Реклама) ---
async def ad_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        return
        
    ad_text = " ".join(context.args)
    if not ad_text:
        await update.message.reply_text(
            "⚠️ <b>Как использовать:</b>\n"
            "Отправь команду: <code>/ad Текст вашей рекламы</code>\n\n"
            "Бот разошлет это сообщение во все группы, где он есть, и <b>сбросит кулдаун у всех игроков</b>.",
            parse_mode=ParseMode.HTML
        )
        return

    # Получаем список уникальных chat_id из базы
    users_df = load_users()
    if users_df.empty:
        await update.message.reply_text("❌ База пользователей пуста, некого оповещать.")
        return
        
    unique_chats = users_df['chat_id'].dropna().unique()
    
    # Сбрасываем кулдаун у всех
    count_users = reset_all_cooldowns()
    
    await update.message.reply_text(f"🚀 Начинаю рассылку в {len(unique_chats)} чатов. Кулдаун сброшен у {count_users} записей пользователей.")
    
    success_count = 0
    error_count = 0
    
    ad_message = f"📢 <b>Объявление:</b>\n\n{ad_text}\n\n🎉 <i>Кулдаун на ловлю жуков сброшен у всех игроков! Скорее пишите /bugs!</i>"
    
    for chat_id in unique_chats:
        try:
            # Отправляем рекламное сообщение в чат
            await context.bot.send_message(chat_id=int(chat_id), text=ad_message, parse_mode=ParseMode.HTML)
            success_count += 1
            # Небольшая пауза, чтобы Telegram не забанил бота за спам (лимит 30 сообщений в секунду)
            await asyncio.sleep(0.1) 
        except Exception as e:
            # Если бота удалили из группы или он заблокирован
            error_count += 1
            logger.error(f"Ошибка рассылки в чат {chat_id}: {e}")
            
    await update.message.reply_text(
        f"✅ <b>Рассылка завершена!</b>\n"
        f"Успешно отправлено: {success_count}\n"
        f"Ошибок (бот удален/заблокирован): {error_count}",
        parse_mode=ParseMode.HTML
    )

# --- Аналитика (/ex) ---
async def ex_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ У вас нет прав для этой команды.")
        return
    
    ex_df = pd.read_csv(EX_FILE)
    users_df = load_users()
    text = (
        f"📊 <b>Аналитика бота</b>\n\n"
        f"🔹 Всего нажатий /bugs: {len(ex_df[ex_df['action'] == 'bugs_command'])}\n"
        f"🔹 Уникальных пользователей: {ex_df[ex_df['action'] == 'bugs_command']['user_id'].nunique()}\n"
        f"🔹 Уникальных групп: {ex_df[ex_df['action'] == 'bugs_command']['chat_id'].nunique()}\n"
        f"🔹 Всего записей в Users: {len(users_df)}\n"
        f"🔹 Записей в Sulki: {len(load_sulki())}\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# --- Обработчик инлайн кнопки для админа ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "admin_ex" and update.effective_user.id == ADMIN_ID:
        # Перенаправляем на логику ex_command
        update.message = query.message
        await ex_command(update, context)

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
    
    # Регистрация команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bugs", bugs_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ex", ex_command))
    app.add_handler(CommandHandler("ad", ad_command)) # Новая команда
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_member))
    
    # Обработчик кнопок
    from telegram.ext import CallbackQueryHandler
    app.add_handler(CallbackQueryHandler(button_callback))
    
    print("✅ Бот успешно запущен и готов к работе! Ожидание команд...\n")
    app.run_polling()

if __name__ == '__main__':
    main()
