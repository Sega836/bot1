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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
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

COOLDOWN_SECONDS = 5

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
        resp = requests.get(meta_url, headers=headers, params=params)
        if resp.status_code != 200:
            print(f"❌ [ЛОГ ОШИБКА] Яндекс.Диск вернул код {resp.status_code}. Ответ: {resp.text}")
            return
            
        meta = resp.json()
        download_href = meta.get("file")
        
        if not download_href:
            dl_url = "https://cloud-api.yandex.net/v1/disk/resources/download"
            dl_resp = requests.get(dl_url, headers=headers, params=params)
            dl_resp.raise_for_status()
            download_href = dl_resp.json().get("href")

        if not download_href:
            print("❌ [ЛОГ ОШИБКА] Не удалось получить ссылку для скачивания архива.")
            return

        file_resp = requests.get(download_href)
        file_resp.raise_for_status()
        
        for root, dirs, files in os.walk(LOCAL_IMAGE_DIR, topdown=False):
            for name in files: os.remove(os.path.join(root, name))
            for name in dirs: os.rmdir(os.path.join(root, name))

        with zipfile.ZipFile(io.BytesIO(file_resp.content)) as z:
            z.extractall(LOCAL_IMAGE_DIR)
        
        bugs = []
        for root, dirs, files in os.walk(LOCAL_IMAGE_DIR):
            for file in files:
                if file.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    bugs.append(os.path.splitext(file)[0])
                    
        bugs = list(set(bugs))
        with open(BUGS_LIST_FILE, "w", encoding="utf-8") as f:
            json.dump(bugs, f, ensure_ascii=False)
        print(f"🎉 [ЛОГ] УСПЕХ! Найдено уникальных жуков: {len(bugs)}")
            
    except Exception as e:
        print(f"❌ [ЛОГ ОШИБКА] Исключение: {e}")

def get_bug_list():
    if os.path.exists(BUGS_LIST_FILE):
        with open(BUGS_LIST_FILE, "r", encoding="utf-8") as f: return json.load(f)
    return []

def get_bug_image_path(bug_name):
    for root, dirs, files in os.walk(LOCAL_IMAGE_DIR):
        for file in files:
            if os.path.splitext(file)[0] == bug_name and file.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                return os.path.join(root, file)
    return None

# --- Работа с CSV ---
def init_csv_files():
    if not os.path.exists(USERS_FILE):
        pd.DataFrame(columns=["user_id", "username", "chat_id", "collection_json", "last_command_time"]).to_csv(USERS_FILE, index=False)
    if not os.path.exists(SULKI_FILE):
        pd.DataFrame(columns=["ref_link", "chat_id", "user_id", "invited_user_id", "created_at"]).to_csv(SULKI_FILE, index=False)
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
    user_id, chat_id = int(user_id), int(chat_id)
    
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

def reset_cooldown_in_chat(chat_id):
    chat_id = int(chat_id)
    users = load_users()
    group_users = users[users['chat_id'] == chat_id]
    if group_users.empty: return
    past_time = (datetime.now() - timedelta(seconds=COOLDOWN_SECONDS + 5)).isoformat()
    for idx in group_users.index:
        users.at[idx, 'last_command_time'] = past_time
    save_users(users)

# --- Логика игры ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    if context.args and chat.type == 'private':
        referrer_id = context.args[0]
        try: referrer_id = int(referrer_id)
        except ValueError: referrer_id = None
        
        if referrer_id and referrer_id != user.id:
            users_df = load_users()
            ref_groups = users_df[users_df['user_id'] == referrer_id]
            
            if not ref_groups.empty:
                ref_groups = ref_groups.sort_values(by='last_command_time', ascending=False)
                target_chat_id = int(ref_groups.iloc[0]['chat_id'])
                
                bug_list = get_bug_list()
                if bug_list:
                    for _ in range(3):
                        add_bug_to_user(referrer_id, "referrer", target_chat_id, random.choice(bug_list))
                
                reset_cooldown_in_chat(target_chat_id)
                log_event(referrer_id, target_chat_id, "ref_success", "3 bugs")
                
                ref_username = ref_groups.iloc[0]['username']
                msg = (
                    f"🎁 <b>Реферальная программа!</b>\n\n"
                    f"Пользователь {user.mention_html()} перешел по реферальной ссылке.\n"
                    f"Пригласивший <a href='tg://user?id={referrer_id}'>{ref_username}</a> получает <b>3 бонусных жука</b> в коллекцию!\n"
                    f"⚡ У <b>всей группы</b> сброшен кулдаун!"
                )
                try:
                    await context.bot.send_message(chat_id=target_chat_id, text=msg, parse_mode=ParseMode.HTML)
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление: {e}")

            await update.message.reply_text(
                f"👋 Привет, {user.first_name}!\n\n"
                f"Ты перешёл по приглашению. Пригласивший уже получил своих жуков!\n"
                f"Добавь меня в свою группу и начинай ловить жуков: /bugs"
            )
            return
    
    if chat.type == 'private':
        text = (
            f"Привет! Я <b>Жук-Бот</b> — бот для чатов (групп)\n\n"
            f"Смысл бота: бот работает только в чатах. Раз в {COOLDOWN_SECONDS} секунд (пока тестируем) игрок может прописать команду /bugs, где в ответ получит от бота случайного жука.\n\n"
            f"Если у тебя есть вопросы — пиши команду: /help"
        )
        keyboard = [[InlineKeyboardButton("➕ Добавить в группу", url=f"https://t.me/{context.bot.username}?startgroup=true")]]
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(f"👋 Привет, {user.first_name}! Я готов к работе.\nНапиши /bugs, чтобы начать ловить жуков!")

async def bugs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    user_id = int(user.id)
    chat_id = int(chat.id)
    
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("Эта команда работает только в группах!")
        return

    users = load_users()
    user_row = users[(users['user_id'] == user_id) & (users['chat_id'] == chat_id)]
    
    if not user_row.empty:
        last_time_str = user_row.iloc[0]['last_command_time']
        if pd.notna(last_time_str):
            last_time = datetime.fromisoformat(last_time_str)
            if datetime.now() - last_time < timedelta(seconds=COOLDOWN_SECONDS):
                remaining = timedelta(seconds=COOLDOWN_SECONDS) - (datetime.now() - last_time)
                await update.message.reply_text(f"⏳ Подожди еще {remaining.seconds} сек.!")
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
            await update.message.reply_text(caption, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(caption, parse_mode=ParseMode.HTML)

async def new_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']: return
    await update.message.reply_text("👋 Привет! Я готов к работе. Напиши /bugs, чтобы начать ловить жуков!")

async def ref_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ref_link = f"https://t.me/{context.bot.username}?start={user.id}"
    
    text = (
        "🎁 <b>Твоя реферальная ссылка:</b>\n\n"
        f"<code>{ref_link}</code>\n\n"
        "Отправь её другу. Как только он перейдет по ней и запустит бота, ты <b>сразу получишь 3 бонусных жука</b>, а кулдаун твоей последней активной группы сбросится!"
    )
    keyboard = [[InlineKeyboardButton("📤 Поделиться ссылкой", url=f"https://t.me/share/url?url={ref_link}&text=Присоединяйся к охоте на жуков!")]]
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']: return
        
    users = load_users()
    user_id, chat_id = int(user.id), int(chat.id)
    user_row = users[(users['user_id'] == user_id) & (users['chat_id'] == chat_id)]
    
    if user_row.empty:
        await update.message.reply_text("У тебя пока нет пойманных жуков. Напиши /bugs!")
        return
        
    collection = json.loads(user_row.iloc[0]['collection_json'])
    total_bugs = sum(collection.values())
    
    text = f"👤 <b>Профиль {user.first_name}</b>\n\n🐞 Всего собрано: <b>{total_bugs}</b>\n📦 Уникальных видов: <b>{len(collection)}</b>\n\n<b>Твоя коллекция:</b>\n"
    for bug, count in sorted(collection.items(), key=lambda x: x[1], reverse=True)[:10]:
        text += f"• {bug} — {count} шт.\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']: return
    
    chat_id = int(chat.id)
    users = load_users()
    group_users = users[users['chat_id'] == chat_id]
    if group_users.empty: return
        
    leaderboard = []
    for _, row in group_users.iterrows():
        try:
            collection = json.loads(row['collection_json'])
            leaderboard.append((row['username'], sum(collection.values())))
        except: pass
            
    leaderboard.sort(key=lambda x: x[1], reverse=True)
    
    text = "🏆 <b>Топ охотников за жуками:</b>\n\n"
    for i, (username, total) in enumerate(leaderboard[:10], 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} @{username} — {total} жуков\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        "🐞 <b>Охота на жуков — Справка</b>\n\n"
        "📜 <b>Доступные команды:</b>\n"
        "• /bugs — Поймать случайного жука\n"
        "• /ref — Получить реферальную ссылку\n"
        "• /profile — Посмотреть свою коллекцию\n"
        "• /top — Топ игроков в группе\n"
        "• /help — Показать это сообщение\n\n"
        "🎁 <b>Реферальная программа:</b>\n"
        "Отправь ссылку другу. Как только он перейдет по ней, ты сразу получишь <b>3 бонусных жука</b>!"
    )
    if user.id == ADMIN_ID:
        text += (
            "\n\n👑 <b>Для администратора:</b>\n"
            "• /ex — Аналитика\n"
            "• /an (ответом) — Рассылка\n"
            "• /do — Скачать базы\n"
            "• /deluser (ответом) — Удалить юзера из БД группы\n"
            "• /del — <b>ПОЛНОСТЬЮ ОЧИСТИТЬ ВСЕ БАЗЫ</b>"
        )
        keyboard = [[InlineKeyboardButton("📊 Открыть аналитику", callback_data="admin_ex")]]
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# --- АДМИНСКИЕ КОМАНДЫ ---
async def del_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    # Отправляем сообщение с кнопкой подтверждения
    keyboard = [
        [InlineKeyboardButton("🗑️ ДА, УДАЛИТЬ ВСЁ", callback_data="confirm_delete")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_delete")]
    ]
    await update.message.reply_text(
        "⚠️ <b>ВНИМАНИЕ!</b>\n\n"
        "Вы собираетесь <b>полностью удалить</b> все базы данных:\n"
        "• Коллекции всех игроков (Users.csv)\n"
        "• Историю рефералов (Sulki.csv)\n"
        "• Всю аналитику (ex.csv)\n\n"
        "Это действие <b>невозможно отменить</b>. Вы уверены?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID: return
    
    if query.data == "cancel_delete":
        await query.edit_message_text("✅ Удаление отменено. Базы данных в безопасности.")
        return
        
    if query.data == "confirm_delete":
        await query.edit_message_text("⏳ Удаляю базы данных...")
        
        try:
            # Перезаписываем файлы пустыми данными
            pd.DataFrame(columns=["user_id", "username", "chat_id", "collection_json", "last_command_time"]).to_csv(USERS_FILE, index=False)
            pd.DataFrame(columns=["ref_link", "chat_id", "user_id", "invited_user_id", "created_at"]).to_csv(SULKI_FILE, index=False)
            pd.DataFrame(columns=["timestamp", "user_id", "chat_id", "action", "bug_name"]).to_csv(EX_FILE, index=False)
            
            # Опционально: можно удалить и файл bugs_list.json, но он перезапишется при следующем запуске
            # os.remove(BUGS_LIST_FILE) 
            
            await query.edit_message_text("✅ <b>Все базы данных успешно очищены!</b>\n\nТеперь бот как новый.", parse_mode=ParseMode.HTML)
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка при удалении: {e}")

async def an_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ Ответьте (Reply) на сообщение и напишите <code>/an</code>.", parse_mode=ParseMode.HTML)
        return

    replied_msg = update.message.reply_to_message
    users_df = load_users()
    if users_df.empty: return
    unique_chats = users_df['chat_id'].dropna().unique()
    
    past_time = (datetime.now() - timedelta(seconds=COOLDOWN_SECONDS + 5)).isoformat()
    users_df['last_command_time'] = past_time
    save_users(users_df)
    
    status_msg = await update.message.reply_text(f"🚀 Рассылка в {len(unique_chats)} чатов...")
    success, error = 0, 0
    ad_postfix = "🎉 <b>Только благодаря этой рекламе кулдаун на ловлю жуков был сброшен!</b> Скорее пишите /bugs!"
    
    for chat_id in unique_chats:
        try:
            await replied_msg.copy(chat_id=int(chat_id))
            await context.bot.send_message(chat_id=int(chat_id), text=ad_postfix, parse_mode=ParseMode.HTML)
            success += 1
            await asyncio.sleep(0.1) 
        except: error += 1
            
    await status_msg.edit_text(f"✅ <b>Готово!</b> Успешно: {success}, Ошибок: {error}", parse_mode=ParseMode.HTML)

async def do_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    await update.message.reply_text("📦 Собираю базы данных...")
    files = [(USERS_FILE, "Users.csv"), (SULKI_FILE, "Sulki.csv"), (EX_FILE, "ex.csv"), (BUGS_LIST_FILE, "bugs_list.json")]
    for path, name in files:
        if os.path.exists(path):
            try:
                with open(path, 'rb') as f: await update.message.reply_document(document=f, filename=name)
                await asyncio.sleep(0.5)
            except Exception as e: await update.message.reply_text(f"❌ Ошибка: {e}")

async def deluser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    if user.id != ADMIN_ID: return
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        target_id = int(target_user.id)
    else:
        await update.message.reply_text("⚠️ Чтобы удалить пользователя, ответьте (Reply) на его сообщение командой `/deluser`.", parse_mode=ParseMode.MARKDOWN)
        return
        
    if chat.type not in ['group', 'supergroup']: return
    chat_id = int(chat.id)
    
    users = load_users()
    user_row = users[(users['user_id'] == target_id) & (users['chat_id'] == chat_id)]
    
    if user_row.empty:
        await update.message.reply_text(f"❌ Пользователь {target_user.first_name} не найден в базе этой группы.")
        return
        
    users = users.drop(user_row.index)
    save_users(users)
    
    await update.message.reply_text(f"✅ <b>Пользователь {target_user.first_name} (ID: {target_id}) удален.</b>", parse_mode=ParseMode.HTML)

async def ex_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    ex_df = pd.read_csv(EX_FILE)
    users_df = load_users()
    
    ref_success = len(ex_df[ex_df['action'] == 'ref_success']) if not ex_df.empty else 0
    text = (
        f"📊 <b>Аналитика бота</b>\n\n"
        f"🔹 Всего нажатий /bugs: {len(ex_df[ex_df['action'] == 'bugs_command']) if not ex_df.empty else 0}\n"
        f"🔹 Успешных рефералов: {ref_success}\n"
        f"🔹 Уникальных пользователей: {ex_df[ex_df['action'] == 'bugs_command']['user_id'].nunique() if not ex_df.empty else 0}\n"
        f"🔹 Всего записей в Users: {len(users_df)}\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "admin_ex" and update.effective_user.id == ADMIN_ID:
        update.message = query.message
        await ex_command(update, context)

async def post_init(application):
    commands = [
        BotCommand("bugs", "🐞 Поймать жука"),
        BotCommand("ref", "🔗 Моя реф. ссылка"),
        BotCommand("profile", "👤 Мой профиль"),
        BotCommand("top", "🏆 Топ игроков"),
        BotCommand("help", "📜 Помощь"),
    ]
    await application.bot.set_my_commands(commands)

def main():
    if not BOT_TOKEN: return
    print("\n" + "="*40 + "\n🤖 ЗАПУСК БОТА...\n" + "="*40)
    init_csv_files()
    download_and_extract_bugs()
    
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bugs", bugs_command))
    app.add_handler(CommandHandler("ref", ref_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("top", top_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ex", ex_command))
    app.add_handler(CommandHandler("an", an_command))
    app.add_handler(CommandHandler("do", do_command))
    app.add_handler(CommandHandler("deluser", deluser_command))
    app.add_handler(CommandHandler("del", del_command)) # Новая команда
    
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_member))
    
    # Обработчик кнопок (добавлен отлов confirm_delete и cancel_delete)
    from telegram.ext import CallbackQueryHandler
    app.add_handler(CallbackQueryHandler(delete_callback, pattern="^(confirm_delete|cancel_delete)$"))
    app.add_handler(CallbackQueryHandler(button_callback)) # Для остальных кнопок
    
    print("✅ Бот успешно запущен!\n")
    app.run_polling()

if __name__ == '__main__':
    main()
