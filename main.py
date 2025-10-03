import os
import logging
import json
from telebot import TeleBot, types
from flask import Flask, request
from dotenv import load_dotenv

# --- Logging sozlamalari ---
logging.basicConfig(
    filename='kino_bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# --- Muhit o‘zgaruvchilari ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = TeleBot(BOT_TOKEN)
app = Flask(__name__)

# --- JSON fayllar ---
USERS_FILE = "users_data.json"  # Foydalanuvchilar ma'lumotlari
MOVIES_FILE = "movies.json"    # Kinolar ma'lumotlari
CHANNELS_FILE = "channels.json" # Kanallar ro'yxati

# --- JSON fayllarni yuklash/funksiyalar ---
def load_json(file_path, default):
    if not os.path.exists(file_path):
        with open(file_path, "w") as f:
            json.dump(default, f)
    with open(file_path, "r") as f:
        return json.load(f)

def save_json(file_path, data):
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)

# --- Foydalanuvchilar ---
def get_user(chat_id):
    users = load_json(USERS_FILE, {})
    if str(chat_id) not in users:
        users[str(chat_id)] = {"subscribed": False}
        save_json(USERS_FILE, users)
    return users[str(chat_id)]

def update_user(chat_id, user_data):
    users = load_json(USERS_FILE, {})
    users[str(chat_id)] = user_data
    save_json(USERS_FILE, users)

# --- Kinolar ---
def add_movie(movie_id, file_id, name):
    movies = load_json(MOVIES_FILE, [])
    movies.append({"id": movie_id, "file_id": file_id, "name": name})
    save_json(MOVIES_FILE, movies)

def delete_movie(movie_id):
    movies = load_json(MOVIES_FILE, [])
    movies = [m for m in movies if m['id'] != movie_id]
    save_json(MOVIES_FILE, movies)

def get_movie(movie_id):
    movies = load_json(MOVIES_FILE, [])
    for movie in movies:
        if movie['id'] == movie_id:
            return movie
    return None

# --- Kanallar ---
def get_channels():
    return load_json(CHANNELS_FILE, [])

def add_channel(channel):
    channels = get_channels()
    if channel not in channels:
        channels.append(channel)
        save_json(CHANNELS_FILE, channels)

def remove_channel(channel):
    channels = get_channels()
    if channel in channels:
        channels.remove(channel)
        save_json(CHANNELS_FILE, channels)

# --- Kanal a’zoligi tekshirish ---
def check_channel_membership(chat_id):
    channels = get_channels()
    for channel in channels:
        try:
            member = bot.get_chat_member(channel, chat_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except:
            return False
    return True

# --- Klaviaturalar ---
def main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🎬 Kino topish")
    return kb

def admin_panel():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ Kino qo‘shish", "❌ Kino o‘chirish")
    kb.add("➕ Kanal qo‘shish", "❌ Kanal o‘chirish")
    kb.add("🔙 Orqaga")
    return kb

# --- Obuna bo‘lish tugmalari ---
def force_subscribe(chat_id):
    channels = get_channels()
    if not channels:
        return False
    markup = types.InlineKeyboardMarkup()
    for ch in channels:
        markup.add(types.InlineKeyboardButton(
            text=f"🔗 {ch}",
            url=f"https://t.me/{ch[1:]}" if ch.startswith("@") else f"https://t.me/{ch}"
        ))
    markup.add(types.InlineKeyboardButton("✅ Tekshirish", callback_data="check_subs"))
    bot.send_message(chat_id, "👉 Kino ko‘rish uchun quyidagi kanallarga a’zo bo‘ling:", reply_markup=markup)
    return True

# --- /start komandasi ---
@bot.message_handler(commands=["start"])
def start(message):
    chat_id = message.chat.id
    user = get_user(chat_id)

    # --- Kanal tekshirish ---
    if not check_channel_membership(chat_id):
        force_subscribe(chat_id)
        user["subscribed"] = False
        update_user(chat_id, user)
        return

    user["subscribed"] = True
    update_user(chat_id, user)
    bot.send_message(chat_id, "Assalomu alaykum! Kino topish uchun menyuni ishlatishingiz mumkin:", reply_markup=main_menu())

# --- Inline tugma qayta tekshirish ---
@bot.callback_query_handler(func=lambda call: call.data == "check_subs")
def recheck_subscription(call):
    chat_id = call.from_user.id
    user = get_user(chat_id)
    if check_channel_membership(chat_id):
        bot.answer_callback_query(call.id, "✅ Obuna bo‘ldingiz!")
        user["subscribed"] = True
        update_user(chat_id, user)
        bot.send_message(call.message.chat.id, "Endi kino topishingiz mumkin ✅", reply_markup=main_menu())
    else:
        bot.answer_callback_query(call.id, "❌ Hali barcha kanallarga obuna bo‘lmadingiz.")
        force_subscribe(chat_id)

# --- Kino topish ---
@bot.message_handler(func=lambda m: m.text == "🎬 Kino topish")
def kino_topish(message):
    chat_id = message.chat.id
    user = get_user(chat_id)
    if not user["subscribed"] or not check_channel_membership(chat_id):
        force_subscribe(chat_id)
        return
    bot.send_message(chat_id, "🔢 Kino raqamini kiriting:")

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    chat_id = message.chat.id
    user = get_user(chat_id)
    if not user["subscribed"] or not check_channel_membership(chat_id):
        force_subscribe(chat_id)
        return
    try:
        movie_id = int(message.text)
        movie = get_movie(movie_id)
        if movie:
            bot.send_video(chat_id, movie['file_id'], caption=f"🎬 {movie['name']}")
            logging.info(f"Kino yuborildi: {chat_id} uchun ID {movie_id}")
        else:
            bot.send_message(chat_id, "🚫 Bunday kino topilmadi. Iltimos, raqamni tekshiring!")
    except ValueError:
        pass  # Faqat son bo‘lmasa o‘tkazib yuborish

# --- Admin panel ---
@bot.message_handler(func=lambda m: m.chat.id == ADMIN_ID)
def admin(message):
    if message.text == "/admin":
        bot.send_message(message.chat.id, "Admin panel:", reply_markup=admin_panel())
    elif message.text == "➕ Kino qo‘shish":
        msg = bot.send_message(message.chat.id, "Kino raqamini kiriting:", reply_markup=types.ForceReply(selective=False))
        bot.register_next_step_handler(msg, process_add_movie_id)
    elif message.text == "❌ Kino o‘chirish":
        msg = bot.send_message(message.chat.id, "O‘chiriladigan kino raqamini kiriting:", reply_markup=types.ForceReply(selective=False))
        bot.register_next_step_handler(msg, process_delete_movie)
    elif message.text == "➕ Kanal qo‘shish":
        msg = bot.send_message(message.chat.id, "Kanal username (@ bilan) kiriting:", reply_markup=types.ForceReply(selective=False))
        bot.register_next_step_handler(msg, lambda m: add_channel(m.text) or bot.send_message(message.chat.id, f"Kanal qo‘shildi: {m.text}"))
    elif message.text == "❌ Kanal o‘chirish":
        msg = bot.send_message(message.chat.id, "O‘chiriladigan kanal username (@ bilan) kiriting:", reply_markup=types.ForceReply(selective=False))
        bot.register_next_step_handler(msg, lambda m: remove_channel(m.text) or bot.send_message(message.chat.id, f"Kanal o‘chirildi: {m.text}"))
    elif message.text == "🔙 Orqaga":
        bot.send_message(message.chat.id, "Asosiy menyuga qaytildi", reply_markup=main_menu())

def process_add_movie_id(message):
    chat_id = message.chat.id
    try:
        movie_id = int(message.text)
        msg = bot.send_message(chat_id, "Kino nomini kiriting:", reply_markup=types.ForceReply(selective=False))
        bot.register_next_step_handler(msg, process_add_movie_name, movie_id)
    except ValueError:
        bot.send_message(chat_id, "❌ Faqat son kiriting!")

def process_add_movie_name(message, movie_id):
    chat_id = message.chat.id
    name = message.text
    msg = bot.send_message(chat_id, "Kino videoni yuboring (video fayl):")
    bot.register_next_step_handler(msg, process_add_movie_video, movie_id, name)

def process_add_movie_video(message, movie_id, name):
    chat_id = message.chat.id
    if message.video:
        file_id = message.video.file_id
        add_movie(movie_id, file_id, name)
        bot.send_message(chat_id, f"✅ Kino qo‘shildi: ID {movie_id}, Nomi: {name}")
    else:
        bot.send_message(chat_id, "❌ Iltimos, video fayl yuboring!")

def process_delete_movie(message):
    chat_id = message.chat.id
    try:
        movie_id = int(message.text)
        delete_movie(movie_id)
        bot.send_message(chat_id, f"✅ Kino o‘chirildi: ID {movie_id}")
    except ValueError:
        bot.send_message(chat_id, "❌ Faqat son kiriting!")

# --- Flask webhook ---
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    json_update = request.get_json(force=True)
    if json_update:
        update = types.Update.de_json(json_update)
        bot.process_new_updates([update])
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
