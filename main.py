import os
import json
import random
import logging
import zipfile
import io
import requests
import pandas as pd
import asyncio
import urllib.parse
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
NOMERA_PATH = "nomera.txt"
LOCAL_IMAGE_DIR = os.path.join(DATA_DIR, "bug_images")

USERS_FILE = os.path.join(DATA_DIR, "Users.csv")
SULKI_FILE = os.path.join(DATA_DIR, "Sulki.csv")
EX_FILE = os.path.join(DATA_DIR, "ex.csv")
BUGS_LIST_FILE = os.path.join(DATA_DIR, "bugs_list.json")
ANALYTICS_FILE = os.path.join(DATA_DIR, "analytics.csv")

COOLDOWN_SECONDS = 5

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Скачивание файлов с Яндекс.Диска ---
def download_yandex_file(path, is_binary=True):
    meta_url = "https://cloud-api.yandex.net/v1/disk/resources"
    headers = {"Authorization": f"OAuth {YANDEX_TOKEN}"}
    params = {"path": path}
    
    try:
        resp = requests.get(meta_url, headers=headers, params=params)
        if resp.status_code == 404:
            print(f"⚠️ [ЛОГ] Файл {path} не найден на Диске.")
            return None
        resp.raise_for_status()
        meta = resp.json()
        download_href = meta.get("file")
        if not download_href:
            dl_resp = requests.get("https://cloud-api.yandex.net/v1/disk/resources/download", headers=headers, params=params)
            download_href = dl_resp.json().get("href")

        file_resp = requests.get(download_href)
        file_resp.raise_for_status()
        return file_resp.content if is_binary else file_resp.text
    except Exception as e:
        print(f"❌ [ЛОГ] Ошибка при скачивании {path}: {e}")
        return None

def load_nomera():
    """Скачивает и парсит nomera.txt (или ищет его внутри архива)."""
    mapping = {}
    
    # 1. Пробуем скачать с Яндекс.Диска как отдельный файл
    content = download_yandex_file(NOMERA_PATH, is_binary=False)
    
    # 2. Если не вышло, пробуем найти внутри архива
    if not content:
        print("🔍 [ЛОГ] Ищу nomera.txt внутри Bugs.zip...")
        zip_bytes = download_yandex_file(BUGS_ARCHIVE_PATH)
        if zip_bytes:
            try:
                with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
                    if NOMERA_PATH in z.namelist():
                        content = z.read(NOMERA_PATH).decode('utf-8')
                    elif NOMERA_PATH.replace('.txt', '.csv') in z.namelist():
                        content = z.read(NOMERA_PATH.replace('.txt', '.csv')).decode('utf-8')
            except Exception as e:
                print(f"Ошибка чтения архива: {e}")

    if not content:
        print("❌ [ЛОГ] Файл nomera.txt не найден ни на Диске, ни в архиве.")
        return {}

    # Парсим файл (формат: [1, Название] или [1, Название, 2, Название])
    # Используем регулярку для поиска пар "число" и "текст"
    import re
    # Ищем паттерн: цифра, запятая/пробел, текст до следующей цифры или конца
    matches = re.findall(r'(\d+)\s*[,:]\s*([^,\n]+)', content)
    for num, name in matches:
        mapping[num.strip()] = name.strip()
        
    return mapping

# --- Распаковка ---
def download_and_extract_bugs():
    print("\n" + "="*40 + "\n🚀 [ЛОГ] ЗАГРУЗКА ЖУКОВ\n" + "="*40)
    os.makedirs(LOCAL_IMAGE_DIR, exist_ok=True)
    
    zip_content = download_yandex_file(BUGS_ARCHIVE_PATH)
    if not zip_content:
        return False
        
    # Очищаем старую папку
    for root, dirs, files in os.walk(LOCAL_IMAGE_DIR, topdown=False):
        for name in files: os.remove(os.path.join(root, name))
        for name in dirs: os.rmdir(os.path.join(root, name))

    # Загружаем маппинг
    mapping = load_nomera()
    if not mapping:
        print("⚠️ [ЛОГ] Маппинг пуст! Будут использоваться имена файлов.")

    try:
        with zipfile.ZipFile(io.BytesIO(zip_content)) as z:
            for info in z.infolist():
                if info.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                    # Берем ID (имя файла без расширения)
                    file_id = os.path.splitext(info.filename)[0]
                    
                    # Ищем нормальное имя в маппинге
                    display_name = mapping.get(file_id, file_id)
                    
                    # Сохраняем файл
                    source = z.open(info.filename)
                    target_path = os.path.join(LOCAL_IMAGE_DIR, info.filename)
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with open(target_path, "wb") as target:
                        target.write(source.read())
                    
                    # Запоминаем связку Имя -> Имя файла
                    # Сохраняем в базу отдельно
                    with open(os.path.join(DATA_DIR, "mapping.json"), "a", encoding="utf-8") as map_file:
                         pass # Пока просто пишем файлы
        
        # Восстанавливаем правильный список имен
        # Проходимся по папке и смотрим, какие файлы есть
        bugs = []
        for file in os.listdir(LOCAL_IMAGE_DIR):
            if file.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                file_id = os.path.splitext(file)[0]
                display_name = mapping.get(file_id, file_id)
                bugs.append(display_name)
        
        bugs = list(set(bugs))
        
        # Сохраняем маппинг в глобальный файл, чтобы бот знал, какая картинка какому имени соответствует
        final_mapping = {}
        for file in os.listdir(LOCAL_IMAGE_DIR):
            if file.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                file_id = os.path.splitext(file)[0]
                display_name = mapping.get(file_id, file_id)
                final_mapping[display_name] = file
        
        with open(os.path.join(DATA_DIR, "mapping.json"), "w", encoding="utf-8") as f:
            json.dump(final_mapping, f, ensure_ascii=False)
            
        with open(BUGS_LIST_FILE, "w", encoding="utf-8") as f:
            json.dump(bugs, f, ensure_ascii=False)
            
        print(f"🎉 [ЛОГ] Найдено жуков: {len(bugs)}")
        print(f"🐞 Примеры названий: {bugs[:10]}")
        return True
    except Exception as e:
        print(f"❌ [ЛОГ] Ошибка: {e}")
        return False

def get_bug_list():
    if os.path.exists(BUGS_LIST_FILE):
        with open(BUGS_LIST_FILE, "r", encoding="utf-8") as f: return json.load(f)
    return []

def get_bug_image_path(bug_name):
    # Читаем маппинг
    map_file = os.path.join(DATA_DIR, "mapping.json")
    if os.path.exists(map_file):
        with open(map_file, "r", encoding="utf-8") as f:
            mapping = json.load(f)
            filename = mapping.get(bug_name)
            if filename:
                path = os.path.join(LOCAL_IMAGE_DIR, filename)
                if os.path.exists(path):
                    return path
    return None

# --- Работа с CSV ---
def init_csv_files():
    if not os.path.exists(USERS_FILE):
        pd.DataFrame(columns=["user_id", "username", "chat_id", "collection_json", "last_command_time", "reg_date"]).to_csv(USERS_FILE, index=False)
    if not os.path.exists(SULKI_FILE):
        pd.DataFrame(columns=["ref_link", "chat_id", "user_id", "invited_user_id", "created_at"]).to_csv(SULKI_FILE, index=False)
    if not os.path.exists(EX_FILE):
        pd.DataFrame(columns=["timestamp", "user_id", "chat_id", "action", "bug_name"]).to_csv(EX_FILE, index=False)
    if not os.path.exists(ANALYTICS_FILE):
        pd.DataFrame(columns=["date", "bugs_clicked", "new_users"]).to_csv(ANALYTICS_FILE, index=False)

def load_users(): return pd.read_csv(USERS_FILE)
def save_users(df): df.to_csv(USERS_FILE, index=False)
def load_sulki(): return pd.read_csv(SULKI_FILE)
def save_sulki(df): df.to_csv(SULKI_FILE, index=False)

def log_event(user_id, chat_id, action, bug_name=""):
    df = pd.read_csv(EX_FILE)
    new_row = {"timestamp": datetime.now().isoformat(), "user_id": user_id, "chat_id": chat_id, "action": action, "bug_name": bug_name}
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_csv(EX_FILE, index=False)

def update_daily_analytics(action_type):
    today = datetime.now().strftime("%Y-%m-%d")
    df = pd.read_csv(ANALYTICS_FILE)
    if today not in df['date'].values:
        new_row = {"date": today, "bugs_clicked": 0, "new_users": 0}
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    idx = df[df['date'] == today].index[0]
    if action_type == "bugs": df.at[idx, 'bugs_clicked'] += 1
    elif action_type == "new_user": df.at[idx, 'new_users'] += 1
    df.to_csv(ANALYTICS_FILE, index=False)

def add_bug_to_user(user_id, username, chat_id, bug_name):
    users = load_users()
    user_id, chat_id = int(user_id), int(chat_id)
    user_row = users[(users['user_id'] == user_id) & (users['chat_id'] == chat_id)]
    if user_row.empty:
        collection = {bug_name: 1}
        new_row = {"user_id": user_id, "username": username, "chat_id": chat_id, "collection_json": json.dumps(collection, ensure_ascii=False), "last_command_time": datetime.now().isoformat(), "reg_date": datetime.now().strftime("%Y-%m-%d")}
        users = pd.concat([users, pd.DataFrame([new_row])], ignore_index=True)
        update_daily_analytics("new_user")
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
        except: referrer_id = None
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
                msg = (f"🎁 <b>Реферальная программа!</b>\n\nПользователь {user.mention_html()} перешел по ссылке.\nПригласивший <a href='tg://user?id={referrer_id}'>{ref_username}</a> получает <b>3 бонусных жука</b>!\n⚡ У <b>всей группы</b> сброшен кулдаун!")
                try: await context.bot.send_message(chat_id=target_chat_id, text=msg, parse_mode=ParseMode.HTML)
                except: pass
            await update.message.reply_text(f"👋 Привет, {user.first_name}!\n\nТы перешёл по приглашению!\nДобавь меня в свою группу и начинай ловить жуков: /bugs")
            return
    if chat.type == 'private':
        text = (f"Привет! Я <b>Жук-Бот</b> — бот для чатов (групп)\n\nСмысл бота: бот работает только в чатах. Раз в {COOLDOWN_SECONDS} секунд (пока тестируем) игрок может прописать команду /bugs, где в ответ получит от бота случайного жука.\n\nЕсли у тебя есть вопросы — пиши команду: /help")
        keyboard = [[InlineKeyboardButton("➕ Добавить в группу", url=f"https://t.me/{context.bot.username}?startgroup=true")]]
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(f"👋 Привет, {user.first_name}! Я готов к работе.\nНапиши /bugs, чтобы начать ловить жуков!")

async def bugs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    user_id, chat_id = int(user.id), int(chat.id)
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
        await update.message.reply_text("База жуков пуста.")
        return
    random_bug = random.choice(bug_list)
    add_bug_to_user(user_id, user.username or user.first_name, chat_id, random_bug)
    log_event(user_id, chat_id, "bugs_command", random_bug)
    update_daily_analytics("bugs")
    image_path = get_bug_image_path(random_bug)
    caption = f"🎉 {user.mention_html()}, ты поймал <b>{random_bug}</b>!\n\nОн добавлен в твою коллекцию."
    if image_path and os.path.exists(image_path):
        try:
            with open(image_path, 'rb') as photo:
                await update.message.reply_photo(photo=photo, caption=caption, parse_mode=ParseMode.HTML)
        except: await update.message.reply_text(caption, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(caption, parse_mode=ParseMode.HTML)

async def new_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']: return
    await update.message.reply_text("👋 Привет! Я готов к работе. Напиши /bugs, чтобы начать ловить жуков!")

async def ref_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ref_link = f"https://t.me/{context.bot.username}?start={user.id}"
    text = (f"🎁 <b>Твоя реферальная ссылка:</b>\n\n<code>{ref_link}</code>\n\nОтправь её другу. Как только он перейдет по ней и запустит бота, ты <b>сразу получишь 3 бонусных жука</b>!")
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
        try: leaderboard.append((row['username'], sum(json.loads(row['collection_json']).values())))
        except: pass
    leaderboard.sort(key=lambda x: x[1], reverse=True)
    text = "🏆 <b>Топ охотников за жуками:</b>\n\n"
    for i, (username, total) in enumerate(leaderboard[:10], 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} @{username} — {total} жуков\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("🐞 <b>Охота на жуков — Справка</b>\n\n📜 <b>Доступные команды:</b>\n• /bugs — Поймать жука\n• /ref — Реферальная ссылка\n• /profile — Моя коллекция\n• /top — Топ игроков\n• /help — Помощь\n\n🎁 <b>Реферальная программа:</b>\nОтправь ссылку другу. Как только он перейдет по ней, ты сразу получишь <b>3 бонусных жука</b>!")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def adminhelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    text = ("👑 <b>Команды администратора</b>\n\n📊 <b>Статистика:</b>\n• /stats — Текстовая статистика\n• /ex — Графики за 7 дней\n• /exall — Графики за всё время\n\n🛠 <b>Управление:</b>\n• /an (ответом) — Рассылка\n• /do — Скачать базы данных\n• /deluser (ответом) — Удалить юзера из группы\n• /del — ОЧИСТИТЬ ВСЕ БАЗЫ\n• /fixbugs — Перекачать жуков")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    users_df = load_users()
    analytics_df = pd.read_csv(ANALYTICS_FILE)
    total_users = len(users_df)
    total_bugs = analytics_df['bugs_clicked'].sum() if not analytics_df.empty else 0
    last_7_days = analytics_df.tail(7)
    bugs_7d = last_7_days['bugs_clicked'].sum() if not last_7_days.empty else 0
    users_7d = last_7_days['new_users'].sum() if not last_7_days.empty else 0
    text = (f"📈 <b>Статистика бота</b>\n\n👥 Всего игроков в боте: <b>{total_users}</b>\n🐞 Всего нажатий /bugs: <b>{total_bugs}</b>\n\n<b>За последние 7 дней:</b>\n🐞 Нажатий /bugs: <b>{bugs_7d}</b>\n🆕 Пришло новых игроков: <b>{users_7d}</b>")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

def generate_chart_url(labels, data_bugs, data_users, title_bugs, title_users, chart_type_bugs="line", chart_type_users="bar"):
    config_bugs = {"type": chart_type_bugs, "data": {"labels": labels, "datasets": [{"label": "Нажатий /bugs", "data": data_bugs, "borderColor": "#36a64f", "backgroundColor": "rgba(54, 166, 79, 0.2)", "fill": True, "tension": 0.3}]}, "options": {"title": {"display": True, "text": title_bugs, "fontSize": 16}, "scales": {"yAxes": [{"ticks": {"beginAtZero": True}}]}}}
    config_users = {"type": chart_type_users, "data": {"labels": labels, "datasets": [{"label": "Новые игроки", "data": data_users, "backgroundColor": "#007bff"}]}, "options": {"title": {"display": True, "text": title_users, "fontSize": 16}, "scales": {"yAxes": [{"ticks": {"beginAtZero": True}}]}}}
    url_bugs = f"https://quickchart.io/chart?c={urllib.parse.quote(json.dumps(config_bugs))}&w=600&h=300&bkg=white"
    url_users = f"https://quickchart.io/chart?c={urllib.parse.quote(json.dumps(config_users))}&w=600&h=300&bkg=white"
    return url_bugs, url_users

async def ex_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    analytics_df = pd.read_csv(ANALYTICS_FILE)
    if analytics_df.empty:
        await update.message.reply_text("❌ Пока нет данных для графиков.")
        return
    df_plot = analytics_df.tail(7)
    labels = df_plot['date'].tolist()
    url_bugs, url_users = generate_chart_url(labels, df_plot['bugs_clicked'].tolist(), df_plot['new_users'].tolist(), "🐞 Нажатия /bugs (7 дней)", "👤 Прирост игроков (7 дней)")
    try:
        await update.message.reply_photo(photo=url_bugs, caption="📈 График активности (7 дней)")
        await asyncio.sleep(1)
        await update.message.reply_photo(photo=url_users, caption="📊 График прироста игроков (7 дней)")
    except Exception as e: await update.message.reply_text(f"❌ Ошибка: {e}")

async def exall_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    analytics_df = pd.read_csv(ANALYTICS_FILE)
    if analytics_df.empty:
        await update.message.reply_text("❌ Пока нет данных для графиков.")
        return
    if len(analytics_df) > 30:
        analytics_df['month'] = pd.to_datetime(analytics_df['date']).dt.strftime('%Y-%m')
        df_plot = analytics_df.groupby('month').sum().reset_index()
        labels = df_plot['month'].tolist()
        chart_type = "bar"
    else:
        df_plot = analytics_df
        labels = df_plot['date'].tolist()
        chart_type = "line"
    url_bugs, url_users = generate_chart_url(labels, df_plot['bugs_clicked'].tolist(), df_plot['new_users'].tolist(), "🐞 Нажатия /bugs (всё время)", "👤 Прирост игроков (всё время)", chart_type_bugs=chart_type, chart_type_users="bar")
    try:
        await update.message.reply_photo(photo=url_bugs, caption="📈 График активности (всё время)")
        await asyncio.sleep(1)
        await update.message.reply_photo(photo=url_users, caption="📊 График прироста игроков (всё время)")
    except Exception as e: await update.message.reply_text(f"❌ Ошибка: {e}")

async def del_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    keyboard = [[InlineKeyboardButton("🗑️ ДА, УДАЛИТЬ ВСЁ", callback_data="confirm_delete")], [InlineKeyboardButton("❌ Отмена", callback_data="cancel_delete")]]
    await update.message.reply_text("⚠️ <b>Вы уверены?</b> Это удалит всех пользователей и статистику.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID: return
    if query.data == "cancel_delete":
        await query.edit_message_text("✅ Удаление отменено.")
        return
    if query.data == "confirm_delete":
        await query.edit_message_text("⏳ Удаляю базы данных...")
        try:
            pd.DataFrame(columns=["user_id", "username", "chat_id", "collection_json", "last_command_time", "reg_date"]).to_csv(USERS_FILE, index=False)
            pd.DataFrame(columns=["ref_link", "chat_id", "user_id", "invited_user_id", "created_at"]).to_csv(SULKI_FILE, index=False)
            pd.DataFrame(columns=["timestamp", "user_id", "chat_id", "action", "bug_name"]).to_csv(EX_FILE, index=False)
            pd.DataFrame(columns=["date", "bugs_clicked", "new_users"]).to_csv(ANALYTICS_FILE, index=False)
            await query.edit_message_text("✅ <b>Все базы данных успешно очищены!</b>", parse_mode=ParseMode.HTML)
        except Exception as e: await query.edit_message_text(f"❌ Ошибка: {e}")

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
    files = [(USERS_FILE, "Users.csv"), (SULKI_FILE, "Sulki.csv"), (EX_FILE, "ex.csv"), (ANALYTICS_FILE, "analytics.csv"), (BUGS_LIST_FILE, "bugs_list.json")]
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
        await update.message.reply_text("⚠️ Ответьте на сообщение командой `/deluser`.", parse_mode=ParseMode.MARKDOWN)
        return
    if chat.type not in ['group', 'supergroup']: return
    chat_id = int(chat.id)
    users = load_users()
    user_row = users[(users['user_id'] == target_id) & (users['chat_id'] == chat_id)]
    if user_row.empty:
        await update.message.reply_text(f"❌ Пользователь не найден.")
        return
    users = users.drop(user_row.index)
    save_users(users)
    await update.message.reply_text(f"✅ <b>Пользователь удален.</b>", parse_mode=ParseMode.HTML)

# --- КОМАНДА /fixbugs ---
async def fixbugs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = await update.message.reply_text("🔄 Перекачиваю архив и файл nomera.txt...")
    success = download_and_extract_bugs()
    if success:
        bugs = get_bug_list()
        sample = ", ".join(bugs[:5]) if bugs else "пусто"
        await msg.edit_text(f"✅ <b>Успешно!</b>\nНайдено жуков: {len(bugs)}\nПримеры: {sample}", parse_mode=ParseMode.HTML)
    else:
        await msg.edit_text("❌ Ошибка при скачивании. Проверьте логи.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

async def post_init(application):
    commands = [BotCommand("bugs", "🐞 Поймать жука"), BotCommand("ref", "🔗 Моя реф. ссылка"), BotCommand("profile", "👤 Мой профиль"), BotCommand("top", "🏆 Топ игроков"), BotCommand("help", "📜 Помощь")]
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
    app.add_handler(CommandHandler("adminhelp", adminhelp_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("ex", ex_command))
    app.add_handler(CommandHandler("exall", exall_command))
    app.add_handler(CommandHandler("an", an_command))
    app.add_handler(CommandHandler("do", do_command))
    app.add_handler(CommandHandler("deluser", deluser_command))
    app.add_handler(CommandHandler("del", del_command))
    app.add_handler(CommandHandler("fixbugs", fixbugs_command))
    
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_member))
    app.add_handler(CallbackQueryHandler(delete_callback, pattern="^(confirm_delete|cancel_delete)$"))
    
    print("✅ Бот успешно запущен!\n")
    app.run_polling()

if __name__ == '__main__':
    main()
