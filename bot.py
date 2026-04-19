#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------- PATCHES for Python 3.13+ missing modules ----------
import sys

# 1. Patch for imghdr
try:
    import imghdr
except ImportError:
    from types import ModuleType
    imghdr = ModuleType('imghdr')
    def what(*args, **kwargs):
        return None
    imghdr.what = what
    sys.modules['imghdr'] = imghdr

# 2. Patch for pkg_resources (used by apscheduler)
try:
    import pkg_resources
except ImportError:
    from types import ModuleType
    pkg_resources = ModuleType('pkg_resources')
    def get_distribution(name):
        class Dist:
            version = "0.0.0"
        return Dist()
    def require(*args, **kwargs):
        pass
    pkg_resources.get_distribution = get_distribution
    pkg_resources.require = require
    pkg_resources.DistributionNotFound = Exception
    sys.modules['pkg_resources'] = pkg_resources
# --------------------------------------------------------------

import os
import json
import logging
import tempfile
import re
import shutil

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler

# Load environment variables
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_USER_ID = int(os.getenv("OWNER_ID", "7526047020"))
APPROVED_USERS_FILE = os.getenv("APPROVED_USERS_FILE", "/data/approved_users.json")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== AUTHORIZATION MANAGEMENT =====

def load_approved_users():
    try:
        with open(APPROVED_USERS_FILE, 'r') as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_approved_users(users_set):
    os.makedirs(os.path.dirname(APPROVED_USERS_FILE), exist_ok=True)
    with open(APPROVED_USERS_FILE, 'w') as f:
        json.dump(list(users_set), f)

authorized_users = load_approved_users()
authorized_users.add(OWNER_USER_ID)

def is_authorized(user_id: int) -> bool:
    return user_id in authorized_users

# ===== URL DETECTION =====

def detect_platform_and_url(text: str):
    """Return (platform, url) if valid Instagram or YouTube link."""
    ig_pattern = r'(https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[a-zA-Z0-9_-]+)'
    ig_match = re.search(ig_pattern, text)
    if ig_match:
        return ('instagram', ig_match.group(0))

    yt_patterns = [
        r'(https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+)',
        r'(https?://youtu\.be/[\w-]+)',
        r'(https?://(?:www\.)?youtube\.com/shorts/[\w-]+)'
    ]
    for pat in yt_patterns:
        yt_match = re.search(pat, text)
        if yt_match:
            return ('youtube', yt_match.group(0))

    return (None, None)

# ===== DOWNLOAD FUNCTION =====

def download_media(url: str, media_type: str) -> str:
    """Download audio (mp3) or video (mp4). Returns file path."""
    temp_dir = tempfile.mkdtemp()
    output_template = os.path.join(temp_dir, '%(title)s.%(ext)s')

    if media_type == 'audio':
        ydl_opts = {
            'outtmpl': output_template,
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }
    else:  # video
        ydl_opts = {
            'outtmpl': output_template,
            'format': 'best[ext=mp4]/best',
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4',
        }

    try:
        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if media_type == 'audio':
                for f in os.listdir(temp_dir):
                    if f.endswith('.mp3'):
                        return os.path.join(temp_dir, f)
            else:
                for f in os.listdir(temp_dir):
                    if f.endswith(('.mp4', '.mkv', '.webm')):
                        return os.path.join(temp_dir, f)
            raise FileNotFoundError(f"{media_type} file not created")
    except Exception as e:
        logger.error(f"Download failed: {e}")
        raise

# ===== TELEGRAM HANDLERS =====

def start(update: Update, context: CallbackContext):
    user = update.effective_user
    user_id = user.id

    if is_authorized(user_id):
        welcome_text = (
            "🎵 *Welcome to MrDownloading Bot*\n\n"
            "Hmu Available for Downloading Audio or Video\n\n"
            "Send me any Instagram or YouTube link and I'll send you both files automatically.\n\n"
            "Coded: @riyanshV"
        )
        update.message.reply_text(welcome_text, parse_mode='Markdown')
    else:
        update.message.reply_text("⏳ You are not yet authorized. Request sent to owner.")
        keyboard = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}"),
                InlineKeyboardButton("❌ Decline", callback_data=f"decline_{user_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        owner_msg = (
            f"🔔 *Approval Request*\n\n"
            f"User: {user.full_name} (@{user.username or 'no username'})\n"
            f"ID: `{user_id}`\n\n"
            f"Approve or decline:"
        )
        context.bot.send_message(
            chat_id=OWNER_USER_ID,
            text=owner_msg,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

def handle_message(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        start(update, context)
        return

    text = update.message.text
    if not text:
        return

    platform, url = detect_platform_and_url(text)
    if not url:
        update.message.reply_text("❌ Please send a valid Instagram or YouTube URL.")
        return

    status_msg = update.message.reply_text(f"🔍 Detected {platform.upper()} link.\n⏳ Downloading audio and video... Please wait.")

    temp_dir = None
    audio_path = None
    video_path = None

    try:
        audio_path = download_media(url, 'audio')
        temp_dir = os.path.dirname(audio_path)

        video_path = download_media(url, 'video')

        with open(audio_path, 'rb') as f:
            update.message.reply_audio(
                audio=f,
                caption=f"🎧 Audio from {platform.capitalize()}",
                parse_mode='Markdown'
            )

        with open(video_path, 'rb') as f:
            update.message.reply_video(
                video=f,
                caption=f"🎬 Video from {platform.capitalize()}",
                parse_mode='Markdown'
            )

        context.bot.delete_message(chat_id=update.effective_chat.id, message_id=status_msg.message_id)

    except Exception as e:
        error_text = f"❌ Failed: {str(e)}"
        logger.error(error_text)
        update.message.reply_text(error_text)
        try:
            context.bot.delete_message(chat_id=update.effective_chat.id, message_id=status_msg.message_id)
        except:
            pass
    finally:
        for f in [audio_path, video_path]:
            if f and os.path.exists(f):
                os.remove(f)
        if temp_dir and os.path.isdir(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass

def button_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data

    if data.startswith("approve_") or data.startswith("decline_"):
        if query.from_user.id != OWNER_USER_ID:
            query.edit_message_text("⛔ You are not authorized.")
            return

        user_id = int(data.split("_")[1])
        if data.startswith("approve_"):
            if user_id not in authorized_users:
                authorized_users.add(user_id)
                save_approved_users(authorized_users - {OWNER_USER_ID})
                query.edit_message_text(f"✅ User `{user_id}` approved.", parse_mode='Markdown')
                try:
                    context.bot.send_message(
                        chat_id=user_id,
                        text="🎉 *You have been approved!*\n\nSend me an Instagram or YouTube link to get both audio and video.",
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.warning(f"Could not notify user {user_id}: {e}")
            else:
                query.edit_message_text(f"ℹ️ User `{user_id}` already authorized.")
        else:
            query.edit_message_text(f"❌ User `{user_id}` declined.", parse_mode='Markdown')
            try:
                context.bot.send_message(
                    chat_id=user_id,
                    text="Sorry, your request was declined by the owner."
                )
            except:
                pass
        return

def error_handler(update: Update, context: CallbackContext):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dispatcher.add_handler(CallbackQueryHandler(button_callback))
    dispatcher.add_error_handler(error_handler)

    logger.info("Bot started polling...")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
