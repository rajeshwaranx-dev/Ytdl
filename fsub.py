"""
fsub.py — Force Subscribe guard (Pyrogram async version)
Supports: public channels, private channels, admin-approval channels.
"""

import logging
import asyncio
from pyrogram import Client, enums
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import UserNotParticipant, ChatAdminRequired, PeerIdInvalid, FloodWait
from database import users as users_col
from config import Config

logger = logging.getLogger("mnbots.fsub")


# ─── Core membership check ────────────────────────────────────────────────────

async def get_member_status(client: Client, user_id: int) -> enums.ChatMemberStatus | None:
    """
    Returns Pyrogram ChatMemberStatus enum or None if not a member / error.
    None = UserNotParticipant (not joined, or pending approval).
    """
    try:
        member = await client.get_chat_member(Config.FSUB_CHANNEL_ID, user_id)
        return member.status
    except UserNotParticipant:
        return None
    except (ChatAdminRequired, PeerIdInvalid) as e:
        logger.error("fsub: cannot check channel %s — %s", Config.FSUB_CHANNEL_ID, e)
        return None
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return None
    except Exception as e:
        logger.warning("fsub: get_member_status unexpected error: %s", e)
        return None


def _is_active_member(status: enums.ChatMemberStatus | None) -> bool:
    """True only for users actually inside the channel."""
    return status in (
        enums.ChatMemberStatus.MEMBER,
        enums.ChatMemberStatus.ADMINISTRATOR,
        enums.ChatMemberStatus.OWNER,
        enums.ChatMemberStatus.RESTRICTED,
    )


async def is_subscribed(client: Client, user_id: int) -> bool:
    """
    Returns True if user can use the bot:
    - Genuine member / admin / owner / restricted → True
    - Pending approval (clicked I Joined, request sent) → True
    - Never joined / banned → False
    """
    status = await get_member_status(client, user_id)

    # Banned
    if status == enums.ChatMemberStatus.BANNED:
        return False

    # Genuinely inside the channel
    if _is_active_member(status):
        # Clear any stale pending flag
        users_col.update_one({"_id": user_id}, {"$unset": {"fsub_pending": ""}})
        return True

    # Not a member — check if they have a pending join request approved by us
    doc = users_col.find_one({"_id": user_id}, {"fsub_pending": 1})
    if doc and doc.get("fsub_pending") is True:
        return True

    return False


# ─── Force-sub message sender ─────────────────────────────────────────────────

async def send_force_sub_message(msg: Message) -> None:
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=Config.FSUB_CHANNEL_LINK)],
        [InlineKeyboardButton("✅ I Joined / I Requested", callback_data="check_sub")],
    ])
    await msg.reply(
        "👋 <b>Welcome!</b>\n\n"
        "⚠️ You must join our channel to use this bot.\n\n"
        "1️⃣ Click <b>Join Channel</b> below\n"
        "2️⃣ Join or send a join request\n"
        "3️⃣ Come back and tap <b>✅ I Joined / I Requested</b>",
        parse_mode=enums.ParseMode.HTML,
        reply_markup=markup,
        quote=True,
    )


# ─── "I Joined" callback handler ──────────────────────────────────────────────

async def handle_check_sub(client: Client, cq: CallbackQuery) -> None:
    user_id = cq.from_user.id
    status  = await get_member_status(client, user_id)

    # Banned
    if status == enums.ChatMemberStatus.BANNED:
        await cq.answer("❌ You are banned from the channel. Contact admin.", show_alert=True)
        return

    # Genuinely joined
    if _is_active_member(status):
        users_col.update_one({"_id": user_id}, {"$unset": {"fsub_pending": ""}})
        await cq.answer("✅ Verified! You can now use the bot.", show_alert=True)
        try:
            await cq.message.edit_text(
                "✅ <b>Access granted!</b>\n\n"
                "Send me a YouTube link or use /search to get started. 🚀",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=None,
            )
        except Exception:
            pass
        return

    # Not a member — check if they actually sent a join request
    # We do this by trying to get chat info; if they truly requested,
    # Telegram still returns UserNotParticipant but we trust their tap.
    # We store fsub_pending=True so they get access while request is pending.
    # This flag is cleared automatically once they become a real member.
    doc = users_col.find_one({"_id": user_id}, {"fsub_pending": 1})
    already_pending = doc and doc.get("fsub_pending") is True

    if already_pending:
        # They already tapped before, still pending approval
        await cq.answer(
            "⏳ Your join request is still pending admin approval.\n"
            "You already have temporary access.",
            show_alert=True
        )
        return

    # First time tapping — grant pending access
    users_col.update_one(
        {"_id": user_id},
        {"$set": {"fsub_pending": True}},
        upsert=True,
    )
    await cq.answer(
        "✅ Join request noted! You have temporary access while pending approval.",
        show_alert=True
    )
    try:
        await cq.message.edit_text(
            "⏳ <b>Join request pending approval.</b>\n\n"
            "You have been granted temporary access.\n"
            "Once an admin approves your request you'll be a full member. 🎉\n\n"
            "Send me a YouTube link or use /search to get started.",
            parse_mode=enums.ParseMode.HTML,
            reply_markup=None,
        )
    except Exception:
        pass
    
