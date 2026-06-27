"""
fsub.py — Force Subscribe guard (Pyrogram async version)
Supports: public channels, private channels, admin-approval/join-request channels.

How pending works (no bypass possible):
- When a user sends a join request to the channel, Telegram fires a
  ChatJoinRequest update to the bot (bot must be admin in channel).
- We catch that update and store user_id in DB with fsub_pending=True.
- When they tap "I Joined", we check:
    1. Real member → full access, clear flag
    2. fsub_pending=True in DB → access (they genuinely requested)
    3. Neither → deny
"""

import logging
import asyncio
from pyrogram import Client, enums, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ChatJoinRequest
from pyrogram.errors import UserNotParticipant, ChatAdminRequired, PeerIdInvalid, FloodWait
from database import users as users_col
from config import Config

logger = logging.getLogger("mnbots.fsub")


# ─── Core membership check ────────────────────────────────────────────────────

async def get_member_status(client: Client, user_id: int) -> enums.ChatMemberStatus | None:
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
    return status in (
        enums.ChatMemberStatus.MEMBER,
        enums.ChatMemberStatus.ADMINISTRATOR,
        enums.ChatMemberStatus.OWNER,
        enums.ChatMemberStatus.RESTRICTED,
    )


def _has_pending_request(user_id: int) -> bool:
    """Check if user sent a real join request (stored by ChatJoinRequest handler)."""
    doc = users_col.find_one({"_id": user_id}, {"fsub_pending": 1})
    return bool(doc and doc.get("fsub_pending") is True)


async def is_subscribed(client: Client, user_id: int) -> bool:
    status = await get_member_status(client, user_id)

    if status == enums.ChatMemberStatus.BANNED:
        return False

    if _is_active_member(status):
        # Clear stale pending flag if they are now a real member
        users_col.update_one({"_id": user_id}, {"$unset": {"fsub_pending": ""}})
        return True

    # Not a real member — check if they have a verified pending request
    return _has_pending_request(user_id)


# ─── ChatJoinRequest handler ──────────────────────────────────────────────────
# This fires when a user sends a join request to the channel.
# Bot MUST be admin in the channel to receive this update.

@Client.on_chat_join_request(filters.chat(Config.FSUB_CHANNEL_ID))
async def on_join_request(client: Client, request: ChatJoinRequest):
    user_id = request.from_user.id
    logger.info("fsub: join request from user_id=%d", user_id)
    users_col.update_one(
        {"_id": user_id},
        {"$set": {"fsub_pending": True}},
        upsert=True,
    )


# ─── Force-sub message sender ─────────────────────────────────────────────────

async def send_force_sub_message(msg: Message) -> None:
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=Config.FSUB_CHANNEL_LINK)],
        [InlineKeyboardButton("✅ I Joined", callback_data="check_sub")],
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
                "Send me a YouTube link or use /search to get started. 🎉",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=None,
            )
        except Exception:
            pass
        return

    # Has a real pending join request stored by our handler
    if _has_pending_request(user_id):
        await cq.answer("✅ Join request verified! Access granted.", show_alert=True)
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

    # Never joined, never requested
    await cq.answer(
        "❌ You have not joined the channel yet!\n"
        "Please join or send a join request first.",
        show_alert=True
    )
    
