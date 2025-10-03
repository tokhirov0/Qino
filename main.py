import os
import json
import logging
from datetime import datetime
from threading import Lock
from flask import Flask, request
from telebot import TeleBot, types
from telebot.types import Update
from dotenv import load_dotenv
import requests

# --- Logging sozlamalari ---
logging.basicConfig(
    filename='kino_bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# --- Muhit o‘zgaruvchilari ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

if not all([BOT_TOKEN, ADMIN_ID]):
    logging.error("Muhit o‘zgaruvchilari yetishmayapti!")
    raise ValueError("BOT_TOKEN yoki ADMIN_ID aniqlanmagan!")

try:
    ADMIN_ID = int(ADMIN_ID)
except ValueError:
    logging.error("ADMIN_ID butun son bo‘lishi kerak!")
    raise ValueError("ADMIN_ID butun son bo‘lishi kerak!")

# Render URL ni aniqlash
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", f"https://{os.getenv('RENDER_SERVICE_NAME', 'kino-bot')}.onrender.com")
if not RENDER_URL:
    logging.error("Render URL aniqlanmadi!")
    raise ValueError("Render URL aniqlanmadi!")

bot = TeleBot(BOT_TOKEN)
app = Flask(__name__)

# --- Fayllar va sinxronizatsiya ---
MOVIES_FILE = "movies.json"
CHANNELS_FILE = "channels.json"
USERS_FILE = "users.json"
PENDING_REQUESTS_FILE = "pending_requests.json"
file_lock = Lock()

# --- JSON fayl funksiyalari ---
def load_json(file):
    with file_lock:
        try:
            if not os.path.exists(file):
                default_data = {} if "users" in file or "pending" in file else []
                with open(file, "w") as f:
                    json.dump(default_data, f)
            with open(file, "r") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logging.error(f"JSON faylni o‘qishda xato: {file}, {str(e)}")
            return {} if "users" in file or "pending" in file else []
        except Exception as e:
            logging.error(f"Faylni o‘qishda xato: {file}, {str(e)}")
            raise

def save_json(file, data):
    with file_lock:
        try:
            with open(file, "w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logging.error(f"Faylni saqlashda xato: {file}, {str(e)}")
            raise

# --- Foydalanuvchi ma’lumotlari ---
def get_user(user_id):
    users = load_json(USERS_FILE)
    user_id_str = str(user_id)
    if user_id_str not in users:
        users[user_id_str] = {
            "joined_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_json(USERS_FILE, users)
    return users[user_id_str]

def update_user(user_id, user_data):
    users = load_json(USERS_FILE)
    users[str(user_id)] = user_data
    save_json(USERS_FILE, users)

# --- Kino ma’lumotlari ---
def add_movie(name, file_id):
    movies = load_json(MOVIES_FILE)
    movie_id = len(movies) + 1  # Avtomatik ID generatsiya
    movies.append({"id": movie_id, "name": name, "file_id": file_id})
    save_json(MOVIES_FILE, movies)
    return movie_id

def delete_movie(movie_id):
    movies = load_json(MOVIES_FILE)
    movies = [m for m in movies if m['id'] != movie_id]
    save_json(MOVIES_FILE, movies)

def get_movies():
    return [(m['id'], m['name']) for m in load_json(MOVIES_FILE)]

def find_movie(movie_id):
    movies = load_json(MOVIES_FILE)
    for m in movies:
        if m['id'] == movie_id:
            return m
    return None

# --- Kanal ma’lumotlari ---
def add_channel(channel_id):
    channels = load_json(CHANNELS_FILE)
    if channel_id not in channels:
        channels.append(channel_id)
        save_json(CHANNELS_FILE, channels)

def delete_channel(channel_id):
    channels = load_json(CHANNELS_FILE)
    if channel_id in channels:
        channels.remove(channel_id)
        save_json(CHANNELS_FILE, channels)

# --- Kanal so‘rov va a’zolik tekshiruvi ---
def check_subscription(user_id, channel_id):
    try:
        member = bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logging.error(f"Kanal a’zoligini tekshirishda xato: {channel_id}, {str(e)}")
        return False

def has_pending_request(user_id, channel_id):
    pending = load_json(PENDING_REQUESTS_FILE)
    user_id_str = str(user_id)
    return channel_id in pending and user_id_str in pending[channel_id]

def is_subscribed_or_pending(user_id):
    channels = load_json(CHANNELS_FILE)
    if not channels:
        return True
    return all(check_subscription(user_id, ch) or has_pending_request(user_id, ch) for ch in channels)

def add_pending_request(user_id, channel):
    pending = load_json(PENDING_REQUESTS_FILE)
    user_id_str = str(user_id)
    if channel not in pending:
        pending[channel] = []
    if user_id_str not in pending[channel]:
        pending[channel].append(user_id_str)
        save_json(PENDING_REQUESTS_FILE, pending)
        logging.info(f"So‘rov qo‘shildi: {user_id} uchun {channel}")

# --- Kanal nomlarini 1-kanal, 2-kanal shaklida t.me bilan ko‘rsatish ---
def format_channels():
    channels = load_json(CHANNELS_FILE)
    if not channels:
        return "Kanal yo‘q."
    return "\n".join([f"{i+1}-kanal: t.me/{ch[1:] if ch.startswith('@') else ch}" for i, ch in enumerate(channels)])

# --- Klaviaturalar ---
def admin_panel():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("➕ Kino qo‘shish", "❌ Kino o‘chirish")
    markup.add("📋 Kinolar ro‘yxati", "➕ Kanal qo‘shish", "❌ Kanal o‘chirish")
    markup.add("📊 Statistika", "🔙 Orqaga")
    return markup

def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🎥 Kino topish")
    return markup

# --- Bot handlerlari ---
@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.chat.id
    get_user(user_id)  # Foydalanuvchini ro‘yxatga qo‘shish
    if user_id == ADMIN_ID:
        bot.send_message(user_id, "Admin panelga xush kelibsiz!", reply_markup=admin_panel())
    else:
        if not is_subscribed_or_pending(user_id):
            bot.send_message(user_id, f"Botdan foydalanish uchun quyidagi kanallarga a’zo bo‘ling yoki so‘rov yuboring:\n{format_channels()}")
            return
        bot.send_message(user_id, "Salom! Kino raqamini yozing va kinoni oling.", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "🎥 Kino topish")
def kino_topish(message):
    user_id = message.chat.id
    if not is_subscribed_or_pending(user_id):
        bot.send_message(user_id, f"Iltimos, avval kanallarga a’zo bo‘ling yoki so‘rov yuboring:\n{format_channels()}")
        return
    bot.send_message(user_id, "Kino raqamini kiriting:")

@bot.message_handler(content_types=['video'])
def handle_video(message):
    user_id = message.chat.id
    if user_id != ADMIN_ID:
        bot.send_message(user_id, "Faqat admin kino yuklay oladi!")
        return
    # Forward qilingan yoki oddiy video bo‘lishi mumkin
    file_id = message.video.file_id
    bot.send_message(user_id, "Kino nomini kiriting:", reply_markup=types.ForceReply())
    bot.register_next_step_handler(message, lambda m: add_movie_name(m, file_id))

def add_movie_name(message, file_id):
    name = message.text
    movie_id = add_movie(name, file_id)  # Avtomatik ID
    bot.send_message(message.chat.id, f"Kino qo‘shildi: ID {movie_id} - {name}")
    logging.info(f"Kino qo‘shildi: ID {movie_id}, {name}")

@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID)
def admin_commands(message):
    if message.text == "➕ Kino qo‘shish":
        bot.send_message(message.chat.id, "Video faylni yuboring yoki boshqa chatdan uzating:")
    elif message.text == "❌ Kino o‘chirish":
        msg = bot.send_message(message.chat.id, "O‘chiriladigan kino raqamini kiriting:", reply_markup=types.ForceReply())
        bot.register_next_step_handler(msg, delete_movie_step)
    elif message.text == "📋 Kinolar ro‘yxati":
        movies = get_movies()
        text = "Kinolar ro‘yxati:\n" + "\n".join([f"{id}: {name}" for id, name in movies]) if movies else "Kinolar yo‘q."
        bot.send_message(message.chat.id, text)
    elif message.text == "➕ Kanal qo‘shish":
        msg = bot.send_message(message.chat.id, "Kanal username’ini kiriting (@ bilan yoki chat ID):", reply_markup=types.ForceReply())
        bot.register_next_step_handler(msg, add_channel_step)
    elif message.text == "❌ Kanal o‘chirish":
        msg = bot.send_message(message.chat.id, "O‘chiriladigan kanal raqamini kiriting (masalan, 1 yoki 2):", reply_markup=types.ForceReply())
        bot.register_next_step_handler(msg, remove_channel)
    elif message.text == "📊 Statistika":
        users = load_json(USERS_FILE)
        bot.send_message(message.chat.id, f"Foydalanuvchilar soni: {len(users)}")
    elif message.text == "🔙 Orqaga":
        bot.send_message(message.chat.id, "Asosiy menyuga qaytildi", reply_markup=main_menu())

def delete_movie_step(message):
    try:
        movie_id = int(message.text)
        delete_movie(movie_id)
        bot.send_message(message.chat.id, f"Kino {movie_id} o‘chirildi.")
        logging.info(f"Kino o‘chirildi: ID {movie_id}")
    except ValueError:
        bot.send_message(message.chat.id, "Faqat raqam kiriting!")
        logging.warning(f"Noto‘g‘ri kino raqami: {message.text}")

def add_channel_step(message):
    channel = message.text
    add_channel(channel)
    bot.send_message(message.chat.id, f"Kanal qo‘shildi: {channel}")
    logging.info(f"Kanal qo‘shildi: {channel}")

def remove_channel(message):
    try:
        channel_index = int(message.text) - 1
        channels = load_json(CHANNELS_FILE)
        if 0 <= channel_index < len(channels):
            channel = channels[channel_index]
            delete_channel(channel)
            bot.send_message(message.chat.id, f"{channel_index + 1}-kanal o‘chirildi.")
            logging.info(f"Kanal o‘chirildi: {channel}")
        else:
            bot.send_message(message.chat.id, "Bunday kanal raqami yo‘q!")
    except ValueError:
        bot.send_message(message.chat.id, "Faqat raqam kiriting (masalan, 1 yoki 2)!")
        logging.warning(f"Noto‘g‘ri kanal raqami: {message.text}")

# --- Oddiy xabarlar (kino raqami) ---
@bot.message_handler(func=lambda m: True)
def handle_message(message):
    user_id = message.chat.id
    if user_id == ADMIN_ID:
        return  # Admin buyruqlari yuqorida ishlaydi
    if not is_subscribed_or_pending(user_id):
        bot.send_message(user_id, f"Iltimos, avval kanallarga a’zo bo‘ling yoki so‘rov yuboring:\n{format_channels()}")
        return
    try:
        movie_id = int(message.text)
        movie = find_movie(movie_id)
        if movie:
            bot.send_video(user_id, movie['file_id'], caption=f"{movie['name']}")  # Faqat kino nomi caption sifatida
            logging.info(f"Kino yuborildi: {user_id} uchun ID {movie_id}")
        else:
            bot.send_message(user_id, "Bunday kino topilmadi.")
    except ValueError:
        bot.send_message(user_id, "Iltimos, faqat kino raqamini kiriting!")

# --- Kanalga so‘rov handleri ---
@bot.chat_join_request_handler()
def handle_join_request(request):
    user_id = request.from_user.id
    channel = '@' + request.chat.username if request.chat.username else str(request.chat.id)
    add_pending_request(user_id, channel)
    bot.send_message(user_id, f"{channel} kanaliga so‘rovingiz qabul qilindi. Admin tasdiqlashini kuting yoki a’zo bo‘lsangiz, botdan foydalanishingiz mumkin.")

# --- Webhook o‘rnatish ---
def setup_webhook():
    webhook_url = f"{RENDER_URL}/{BOT_TOKEN}"
    try:
        bot.remove_webhook()
        bot.set_webhook(url=webhook_url)
        response = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo").json()
        if response.get("ok") and response.get("result").get("url") == webhook_url:
            logging.info(f"Vebhook muvaffaqiyatli o‘rnatildi: {webhook_url}")
        else:
            logging.error(f"Vebhook o‘rnatishda xato: {response}")
    except Exception as e:
        logging.error(f"Vebhook o‘rnatishda xato: {str(e)}")
        raise

# --- Flask webhook ---
@app.route(f"/{BOT_TOKEN}", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return "Kino bot ishlayapti! Webhook faol."
    try:
        json_str = request.get_data().decode("utf-8")
        update = Update.de_json(json_str)
        if update:
            bot.process_new_updates([update])
        return "OK", 200
    except Exception as e:
        logging.error(f"Vebhook xatosi: {str(e)}")
        return "ERROR", 500

@app.route("/")
def index():
    return "Kino bot ishlayapti! Webhook faol."

# --- Botni ishga tushirish ---
if __name__ == "__main__":
    try:
        setup_webhook()  # Webhook avtomatik o‘rnatiladi
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
    except Exception as e:
        logging.error(f"Botni ishga tushirishda xato: {str(e)}")
        raise
