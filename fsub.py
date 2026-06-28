"""
fsub.py — Force Subscribe guard (Pyrogram async version)
Uses raw Telegram HTTP API for member check (same as Instagram bot)
to avoid Pyrogram enum issues.
"""

import logging
import asyncio
import aiohttp
from pyrogram import Client, enums, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ChatJoinRequest
from database import users as users_col
from config import Config

logger = logging.getLogger("mnbots.fsub")


# ─── Member check via raw HTTP (returns plain string like "member", "left") ──

async def get_member_status(user_id: int) -> str:
    """
    Uses raw Telegram Bot API to get membership status.
    Returns: 'member' | 'administrator' | 'creator' | 'restricted' | 'left' | 'kicked'
    Falls back to 'left' on any error.
    """
    url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/getChatMember"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params={
                "chat_id": Config.FSUB_CHANNEL_ID,
                "user_id": user_id,
            }, timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
                status = data.get("result", {}).get("status", "left")
                logger.info("fsub: user=%s status=%s", user_id, status)
                return status
    except Exception as e:
        logger.warning("fsub: get_member_status error: %s", e)
        return "left"


async def is_subscribed(client, user_id: int) -> bool:
    status = await get_member_status(user_id)

    # Fully approved member
    if status in ("member", "administrator", "creator", "restricted"):
        users_col.update_one({"_id": user_id}, {"$unset": {"pending_agreed": ""}})
        return True

    # Banned
    if status == "kicked":
        users_col.update_one({"_id": user_id}, {"$unset": {"pending_agreed": ""}})
        return False

    # Left or pending — check if they clicked "I Joined"
    doc = users_col.find_one({"_id": user_id}, {"pending_agreed": 1})
    if doc and doc.get("pending_agreed") is True:
        return True

    return False


# ─── ChatJoinRequest handler ──────────────────────────────────────────────────

@Client.on_chat_join_request(filters.chat(str(Config.FSUB_CHANNEL_ID)))
async def on_join_request(client: Client, request: ChatJoinRequest):
    user_id = request.from_user.id
    logger.info("fsub: join request from user_id=%d", user_id)
    users_col.update_one(
        {"_id": user_id},
        {"$set": {"pending_agreed": True}},
        upsert=True,
    )


# ─── Force-sub message ────────────────────────────────────────────────────────

async def send_force_sub_message(msg: Message) -> None:
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=Config.FSUB_CHANNEL_LINK)],
        [InlineKeyboardButton("✅ I Joined",     callback_data="check_sub")],
    ])
    await msg.reply(
        "👋 <b>Welcome!</b>\n\n"
        "⚠️ You must join our channel to use this bot.\n\n"
        "1️⃣ Click <b>Join Channel</b> below\n"
        "2️⃣ Join or send a join request\n"
        "3️⃣ Come back and tap <b>✅ I Joined</b>",
        parse_mode=enums.ParseMode.HTML,
        reply_markup=markup,
        quote=True,
    )


# ─── "I Joined" callback ─────────────────────────────────────────────────────

async def handle_check_sub(client: Client, cq: CallbackQuery) -> None:
    user_id = cq.from_user.id
    status  = await get_member_status(user_id)

    if status == "kicked":
        await cq.answer("❌ You are banned from the channel. Contact admin.", show_alert=True)
        return

    if status in ("member", "administrator", "creator", "restricted"):
        users_col.update_one({"_id": user_id}, {"$unset": {"pending_agreed": ""}})
        await cq.answer("✅ Verified! You can now use the bot.", show_alert=True)
        try:
            await cq.message.edit_text(
                "✅ <b>Access granted!</b>\n\n"
                "Send me a YouTube link or use /search to get started. 🎉",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=None,
            )
        except Exception:
            pass
        return

    # Left or pending — set pending_agreed and grant access
    users_col.update_one(
        {"_id": user_id},
        {"$set": {"pending_agreed": True}},
        upsert=True,
    )
    await cq.answer("✅ Access granted! Welcome.", show_alert=True)
    try:
        await cq.message.edit_text(
            "✅ <b>Access granted!</b>\n\n"
            "Send me a YouTube link or use /search to get started. 🎉",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=None,
        )
    except Exception:
        pass
  
