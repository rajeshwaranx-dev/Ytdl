"""
fsub.py — Force Subscribe for YouTube Downloader Bot
Checked only when user requests a download.
No DB flags — live membership check every time.
No fake bypass possible.
"""

import asyncio
import logging
from pyrogram import Client, filters, enums
from pyrogram.errors import UserNotParticipant, ChatAdminRequired
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from config import Config

logger = logging.getLogger(__name__)

# Cache for invite link (avoids creating new one every check)
_invite_cache: str | None = None


# ─── Core check ──────────────────────────────────────────────────────────────

async def check_fsub(bot: Client, user_id: int) -> InlineKeyboardButton | None:
    """
    Check if user has joined the fsub channel.
    Returns an InlineKeyboardButton (join button) if not joined, else None.
    """
    global _invite_cache

    try:
        member = await bot.get_chat_member(Config.FSUB_CHANNEL_ID, user_id)
        if member.status == enums.ChatMemberStatus.BANNED:
            raise UserNotParticipant
        return None  # ✅ User is a member

    except UserNotParticipant:
        try:
            chat = await bot.get_chat(Config.FSUB_CHANNEL_ID)

            # Use cached invite link or create new one
            if not _invite_cache:
                invite = await bot.create_chat_invite_link(
                    Config.FSUB_CHANNEL_ID,
                    creates_join_request=True  # supports approval-required channels
                )
                _invite_cache = invite.invite_link

            return InlineKeyboardButton(
                f"📢 Join {chat.title}",
                url=_invite_cache
            )
        except ChatAdminRequired:
            # Bot not admin — fall back to config link
            logger.warning("fsub: bot is not admin in FSUB_CHANNEL_ID, using config link")
            return InlineKeyboardButton("📢 Join Channel", url=Config.FSUB_CHANNEL_LINK)
        except Exception as e:
            logger.warning("fsub: could not create invite link: %s", e)
            return InlineKeyboardButton("📢 Join Channel", url=Config.FSUB_CHANNEL_LINK)

    except Exception as e:
        logger.exception("fsub: unexpected error for user %s: %s", user_id, e)
        return None


async def get_fsub_buttons(bot: Client, user_id: int) -> list:
    """
    Returns list of button rows if user hasn't joined.
    Empty list [] means user passed fsub check.
    """
    btn = await check_fsub(bot, user_id)
    if btn:
        return [[btn]]
    return []


# ─── Decorator ───────────────────────────────────────────────────────────────

def fsub_required(func):
    """
    Decorator — checks fsub before running any download handler.
    Only blocks if user hasn't joined the channel.

    Usage:
        @Client.on_message(filters.text)
        @fsub_required
        async def handle_url(bot, message):
            ...
    """
    async def wrapper(bot: Client, message: Message):
        user_id = message.from_user.id if message.from_user else None
        if not user_id:
            return

        buttons = await get_fsub_buttons(bot, user_id)

        if buttons:
            buttons.append([
                InlineKeyboardButton(
                    "♻️ I've Joined — Try Again",
                    callback_data="fsub_check"
                )
            ])
            await message.reply(
                "<b>⚠️ You must join our channel to use this bot!\n\n"
                "Join the channel below, then click <i>Try Again</i>.</b>",
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode=enums.ParseMode.HTML,
                quote=True,
            )
            return  # Block

        await func(bot, message)

    return wrapper


# ─── "Try Again" callback ─────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex("^fsub_check$"))
async def fsub_recheck(bot: Client, query: CallbackQuery):
    """
    Re-checks membership live when user taps 'Try Again'.
    If passed → deletes the join message.
    If failed → shows updated buttons.
    """
    user_id = query.from_user.id
    buttons = await get_fsub_buttons(bot, user_id)

    if buttons:
        buttons.append([
            InlineKeyboardButton(
                "♻️ I've Joined — Try Again",
                callback_data="fsub_check"
            )
        ])
        await query.answer("🛑 Please join the channel first!", show_alert=True)
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        except Exception:
            pass
    else:
        await query.answer("✅ Verified! Now send your YouTube link.", show_alert=True)
        await query.message.delete()
            
