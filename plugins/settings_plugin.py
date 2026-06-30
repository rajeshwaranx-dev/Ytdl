"""
plugins/settings.py — /settings command for thumbnail and caption configuration.
Admin only.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from config import Config
from database import get_bot_settings, set_thumb_mode, set_custom_thumb, set_caption_template

# In-memory state for "waiting for custom thumbnail upload" / "waiting for caption text"
_awaiting_thumb:   set[int] = set()
_awaiting_caption: set[int] = set()


def is_admin(user_id: int) -> bool:
    return user_id in Config.ADMINS


def _settings_text(s: dict) -> str:
    mode_label = {"random": "Random", "youtube": "YouTube", "custom": "Custom"}.get(s["thumb_mode"], "Random")
    return (
        "⚙️ **AskBotz Settings**\n\n"
        f"🖼 **Thumbnail Mode:** `{mode_label}`\n"
        f"📝 **Caption Template:** `{s.get('caption_template', '**{title}**')}`\n\n"
        "❤️ Powered by @AskBotz"
    )


def _settings_markup(s: dict) -> InlineKeyboardMarkup:
    mode = s["thumb_mode"]
    def mark(label, m):
        return f"✅ {label}" if mode == m else label

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(mark("🎲 Random", "random"), callback_data="set:thumb:random"),
            InlineKeyboardButton(mark("📺 YouTube", "youtube"), callback_data="set:thumb:youtube"),
        ],
        [
            InlineKeyboardButton(mark("🖼 Custom", "custom"), callback_data="set:thumb:custom_prompt"),
        ],
        [
            InlineKeyboardButton("📝 Set Caption", callback_data="set:caption_prompt"),
        ],
        [
            InlineKeyboardButton("❌ Close", callback_data="set:close"),
        ],
    ])


# ─── /settings ───────────────────────────────────────────────────────────────

@Client.on_message(filters.command("settings") & filters.private)
async def cmd_settings(client: Client, msg: Message):
    if not is_admin(msg.from_user.id):
        return await msg.reply("❌ You are not authorized to use this command.", quote=True)

    s = get_bot_settings()
    await msg.reply(_settings_text(s), reply_markup=_settings_markup(s), quote=True)


# ─── Settings callbacks ────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^set:"))
async def cb_settings(client: Client, cq: CallbackQuery):
    if not is_admin(cq.from_user.id):
        return await cq.answer("❌ Not authorized.", show_alert=True)

    data = cq.data.split(":", 2)
    action = data[1]

    if action == "thumb":
        mode = data[2]
        if mode == "custom_prompt":
            _awaiting_thumb.add(cq.from_user.id)
            await cq.answer()
            await cq.message.edit_text(
                "🖼 **Send me the image** you want to use as the custom thumbnail.\n\n"
                "Send /cancel to abort.",
            )
            return
        else:
            set_thumb_mode(mode)
            s = get_bot_settings()
            await cq.answer(f"✅ Thumbnail mode set to {mode.title()}")
            await cq.message.edit_text(_settings_text(s), reply_markup=_settings_markup(s))
            return

    elif action == "caption_prompt":
        _awaiting_caption.add(cq.from_user.id)
        await cq.answer()
        await cq.message.edit_text(
            "📝 **Send your caption template.**\n\n"
            "Use `{title}` as placeholder for the video title.\n"
            "Example: `**{title}**\\n\\n❤️ Join » @AskBotz`\n\n"
            "Send /cancel to abort.",
        )
        return

    elif action == "close":
        await cq.answer()
        try:
            await cq.message.delete()
        except Exception:
            pass
        return


# ─── Capture custom thumbnail upload ──────────────────────────────────────────

@Client.on_message(filters.private & filters.photo)
async def receive_custom_thumb(client: Client, msg: Message):
    user_id = msg.from_user.id
    if user_id not in _awaiting_thumb:
        return
    if not is_admin(user_id):
        return

    _awaiting_thumb.discard(user_id)
    file_id = msg.photo.file_id
    set_custom_thumb(file_id)

    s = get_bot_settings()
    await msg.reply(
        "✅ **Custom thumbnail saved!**\n\nThumbnail mode set to Custom.",
        quote=True
    )
    await msg.reply(_settings_text(s), reply_markup=_settings_markup(s))


# ─── Capture caption template ─────────────────────────────────────────────────

@Client.on_message(filters.private & filters.text & filters.command("cancel"))
async def cancel_settings_input(client: Client, msg: Message):
    user_id = msg.from_user.id
    if user_id in _awaiting_thumb or user_id in _awaiting_caption:
        _awaiting_thumb.discard(user_id)
        _awaiting_caption.discard(user_id)
        await msg.reply("❌ Cancelled.", quote=True)


@Client.on_message(filters.private & filters.text & ~filters.command(["start", "help", "about", "search", "settings", "cancel", "stats", "broadcast", "delreq"]))
async def receive_caption_template(client: Client, msg: Message):
    user_id = msg.from_user.id
    if user_id not in _awaiting_caption:
        return  # let other handlers (like URL handler) process it
    if not is_admin(user_id):
        return

    _awaiting_caption.discard(user_id)
    set_caption_template(msg.text)

    s = get_bot_settings()
    await msg.reply("✅ **Caption template saved!**", quote=True)
    await msg.reply(_settings_text(s), reply_markup=_settings_markup(s))

