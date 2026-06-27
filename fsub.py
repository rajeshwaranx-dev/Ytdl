"""
fsub.py — Force Subscribe guard (Pyrogram async version)
Checks if a user has joined the required channel before using the bot.
Works in both private chats and groups.
"""

import logging
from pyrogram import Client, enums
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserNotParticipant, ChatAdminRequired, PeerIdInvalid, FloodWait
from database import users as users_col
from config import Config

logger = logging.getLogger("mnbots.fsub")


# ─── Core membership check ────────────────────────────────────────────────────

async def get_member_status(client: Client, user_id: int) -> str:
    """
    Returns Telegram membership status string:
    'member' | 'administrator' | 'creator' | 'restricted' | 'left' | 'kicked'
    Falls back to 'left' on any error.
    """
    try:
        member = await client.get_chat_member(Config.FSUB_CHANNEL_ID, user_id)
        return member.status.value  # Pyrogram ChatMemberStatus enum → string
    except UserNotParticipant:
        return "left"
    except (ChatAdminRequired, PeerIdInvalid) as e:
        logger.error("fsub: cannot check channel %s — %s", Config.FSUB_CHANNEL_ID, e)
        return "left"
    except FloodWait as e:
        import asyncio
        await asyncio.sleep(e.value)
        return "left"
    except Exception as e:
        logger.warning("fsub: get_member_status unexpected error: %s", e)
        return "left"


async def is_subscribed(client: Client, user_id: int) -> bool:
    """
    Returns True if the user is allowed to use the bot:
    - Fully joined / admin / creator / restricted → always True
    - Kicked → always False
    - Left → True only if they clicked 'I Joined' (pending_agreed flag in DB)
    """
    status = await get_member_status(client, user_id)

    if status in ("member", "administrator", "creator", "restricted"):
        # Clear any stale pending flag
        users_col.update_one({"_id": user_id}, {"$unset": {"pending_agreed": ""}})
        return True

    if status == "kicked":
        users_col.update_one({"_id": user_id}, {"$unset": {"pending_agreed": ""}})
        return False

    # status == "left" — check pending_agreed flag set when user clicked "I Joined"
    doc = users_col.find_one({"_id": user_id}, {"pending_agreed": 1})
    if doc and doc.get("pending_agreed") is True:
        return True

    return False


# ─── Force-sub message sender ─────────────────────────────────────────────────

async def send_force_sub_message(msg: Message) -> None:
    """Send the join-channel prompt as a reply to the user's message."""
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=Config.FSUB_CHANNEL_LINK)],
        [InlineKeyboardButton("✅ I Joined",     callback_data="check_sub")],
    ])
    await msg.reply(
        "👋 <b>Welcome!</b>\n\n"
        "⚠️ You must join our channel to use this bot.\n\n"
        "1️⃣ Click <b>Join Channel</b> below\n"
        "2️⃣ Join / send a join request\n"
        "3️⃣ Come back and tap <b>✅ I Joined</b>",
        parse_mode=enums.ParseMode.HTML,
        reply_markup=markup,
        quote=True,
    )


# ─── "I Joined" callback handler ──────────────────────────────────────────────

async def handle_check_sub(client: Client, cq: CallbackQuery) -> None:
    """
    Called when the user taps '✅ I Joined'.
    Re-checks membership and responds accordingly.
    Register this in your plugin with:
        @Client.on_callback_query(filters.regex(r"^check_sub$"))
    """
    user_id = cq.from_user.id
    status  = await get_member_status(client, user_id)

    if status in ("member", "administrator", "creator", "restricted"):
        # Confirmed joined — clean up DB and grant access
        users_col.update_one({"_id": user_id}, {"$unset": {"pending_agreed": ""}})
        await cq.answer("✅ Verified! You can now use the bot.", show_alert=True)
        try:
            await cq.message.edit_reply_markup(None)
            await cq.message.edit_text(
                "✅ <b>Access granted!</b>\n\nSend me a YouTube link or use /search to get started. 🚀",
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass

    elif status == "kicked":
        users_col.update_one({"_id": user_id}, {"$unset": {"pending_agreed": ""}})
        await cq.answer("❌ You are banned from the channel. Contact admin.", show_alert=True)

    else:
        # Still not joined — set pending_agreed so they get one grace attempt
        # (Handles private/approval-required channels where status stays "left")
        users_col.update_one(
            {"_id": user_id},
            {"$set": {"pending_agreed": True}},
            upsert=True,
        )
        await cq.answer("✅ Access granted! Welcome.", show_alert=True)
        try:
            await cq.message.edit_reply_markup(None)
            await cq.message.edit_text(
                "✅ <b>Access granted!</b>\n\nSend me a YouTube link or use /search to get started. 🎉",
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass
            
