"""
plugins/start.py — /start, /help, /about commands and menu callbacks.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from config import Config
from database import users as users_col
from fsub import is_subscribed, send_force_sub_message
from log_channel import log_new_user
from helpers.utils import safe_edit

# ─── Texts ───────────────────────────────────────────────────────────────────

HELP_TEXT = (
    "🤖 **Bot Guide**\n\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "📱 **Unlimited Usage:**\n"
    "① Paste any YouTube link\n"
    "② Choose **MP4** (video) or **MP3** (audio)\n"
    "③ Select your quality\n"
    "④ Get your file!\n\n"
    "✨ **Key Features:**\n"
    "• 🎬 Download YouTube videos\n"
    "• 🎵 Extract audio as MP3\n"
    "• 📺 Supports Shorts & full videos\n"
    "• ⚡ Multiple quality options\n"
    "• 🔍 Built-in YouTube search\n\n"
    "📝 **Main Commands:**\n"
    "• `/start` — 🚀 Launch bot\n"
    "• `/search <query>` — 🔍 Search YouTube\n"
    "• `/help` — ❓ Show this guide\n"
    "• `/about` — 🤖 Bot info\n\n"
    "⚠️ **Notes:**\n"
    "• Files > 2GB are sent as direct link\n"
    "• Sharing copyrighted content is not allowed\n"
    "━━━━━━━━━━━━━━━━━━"
)

ABOUT_TEXT = (
    "🤖 **Bot Information**\n\n"
    "╔━━━━━━━━━━━━━━━━━╗\n"
    "       **Bot Details**\n"
    "╚━━━━━━━━━━━━━━━━━╝\n"
    "📝 **Name:** AskBotz YT Downloader\n"
    "👨‍💻 **Developer:** @Master_xkid\n"
    "📢 **Updates:** @AskBotz\n"
    "💬 **Support:** @AskBotz\n\n"
    "╔━━━━━━━━━━━━━━━━━╗\n"
    "     **Technical Specs**\n"
    "╚━━━━━━━━━━━━━━━━━╝\n"
    "🐍 **Python:** 3.12\n"
    "⚙️ **Framework:** PyroFork\n"
    "🗄️ **Database:** MongoDB\n"
    "☁️ **Hosted on:** VPS\n\n"
    "⚡ **Built with ❤️ by AskBotz**"
)


def _start_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❤️ Channel", url=Config.CHANNEL_LINK),
            InlineKeyboardButton("💬 Group",   url=Config.GROUP_LINK),
        ],
        [
            InlineKeyboardButton("❓ Help",    callback_data="menu:help"),
            InlineKeyboardButton("🤖 About",   callback_data="menu:about"),
        ],
    ])


def _start_caption(name: str) -> str:
    return (
        f"👋 **Hello {name}!**\n\n"
        f"I'm **AskBotz YT Downloader** — your fast YouTube download bot.\n\n"
        f"**What I can do:**\n"
        f"• 🔗 Paste any YouTube link → pick MP4 or MP3\n"
        f"• 🔍 `/search <query>` → search & pick a video\n"
        f"• 🎬 Supports Shorts, full videos & embeds\n"
        f"• ⚡ Multiple quality options\n\n"
        f"Just paste a YouTube URL to get started! 🚀"
    )


# ─── fsub guard decorator ────────────────────────────────────────────────────

def fsub_required(func):
    async def wrapper(client: Client, msg: Message):
        user = msg.from_user
        if not user:
            return
        from database import ensure_user
        ensure_user({
            "id":         user.id,
            "first_name": user.first_name or "",
            "last_name":  user.last_name  or "",
            "username":   user.username   or "",
        })
        if not await is_subscribed(client, user.id):
            await send_force_sub_message(msg)
            return
        return await func(client, msg)
    return wrapper


# ─── /start ──────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("start"))
@fsub_required
async def cmd_start(client: Client, msg: Message):
    user   = msg.from_user
    is_new = users_col.find_one({"_id": user.id, "downloads": 0}) is not None
    if is_new:
        await log_new_user(client, user)

    markup  = _start_markup()
    caption = _start_caption(user.first_name or "User")

    try:
        await msg.reply_photo(
            photo=Config.START_IMAGE,
            caption=caption,
            reply_markup=markup,
            quote=True,
        )
    except Exception:
        await msg.reply(caption, reply_markup=markup, quote=True)


# ─── /help ───────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("help"))
@fsub_required
async def cmd_help(client: Client, msg: Message):
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="menu:home")],
    ])
    await msg.reply(HELP_TEXT, reply_markup=markup, quote=True)


# ─── /about ──────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("about"))
@fsub_required
async def cmd_about(client: Client, msg: Message):
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="menu:home")],
    ])
    await msg.reply(ABOUT_TEXT, reply_markup=markup, quote=True)


# ─── Menu callbacks ───────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^menu:(help|about|home)$"))
async def cb_menu(client: Client, cq: CallbackQuery):
    if not await is_subscribed(client, cq.from_user.id):
        await cq.answer("⚠️ Please join the channel first!", show_alert=True)
        return

    action = cq.data.split(":")[1]
    await cq.answer()

    if action == "help":
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Home", callback_data="menu:home")],
        ])
        try:
            await cq.message.edit_text(HELP_TEXT, reply_markup=markup)
        except Exception:
            await cq.message.reply(HELP_TEXT, reply_markup=markup)

    elif action == "about":
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Home", callback_data="menu:home")],
        ])
        try:
            await cq.message.edit_text(ABOUT_TEXT, reply_markup=markup)
        except Exception:
            await cq.message.reply(ABOUT_TEXT, reply_markup=markup)

    elif action == "home":
        name    = cq.from_user.first_name or "User"
        markup  = _start_markup()
        caption = _start_caption(name)
        try:
            await cq.message.edit_text(caption, reply_markup=markup)
        except Exception:
            pass


# ─── check_sub callback ───────────────────────────────────────────────────────

from fsub import handle_check_sub

@Client.on_callback_query(filters.regex(r"^check_sub$"))
async def cb_check_sub(client: Client, cq: CallbackQuery):
    await handle_check_sub(client, cq)
    
