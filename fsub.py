"""
fsub.py — Force Subscribe guard (Pyrogram async version)
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
    Returns the Pyrogram ChatMemberStatus enum directly (no .value conversion).
    Returns None on any error (treat as not joined).
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


async def is_subscribed(client: Client, user_id: int) -> bool:
    """
    Returns True only if the user is genuinely in the channel.
    No grace/pending logic — must actually be a member.
    """
    status = await get_member_status(client, user_id)

    if status is None:
        # UserNotParticipant or error — definitely not joined
        return False

    if status == enums.ChatMemberStatus.BANNED:
        return False

    # Member, admin, owner, restricted (still in channel) → allowed
    return status in (
        enums.ChatMemberStatus.MEMBER,
        enums.ChatMemberStatus.ADMINISTRATOR,
        enums.ChatMemberStatus.OWNER,
        enums.ChatMemberStatus.RESTRICTED,
    )


# ─── Force-sub message sender ─────────────────────────────────────────────────

async def send_force_sub_message(msg: Message) -> None:
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=Config.FSUB_CHANNEL_LINK)],
        [InlineKeyboardButton("✅ I Joined",     callback_data="check_sub")],
    ])
    await msg.reply(
        "👋 <b>Welcome!</b>\n\n"
        "⚠️ You must join our channel to use this bot.\n\n"
        "1️⃣ Click <b>Join Channel</b> below\n"
        "2️⃣ Join the channel\n"
        "3️⃣ Come back and tap <b>✅ I Joined</b>",
        parse_mode=enums.ParseMode.HTML,
        reply_markup=markup,
        quote=True,
    )


# ─── "I Joined" callback handler ──────────────────────────────────────────────

async def handle_check_sub(client: Client, cq: CallbackQuery) -> None:
    user_id = cq.from_user.id
    status  = await get_member_status(client, user_id)

    # Genuinely joined
    if status in (
        enums.ChatMemberStatus.MEMBER,
        enums.ChatMemberStatus.ADMINISTRATOR,
        enums.ChatMemberStatus.OWNER,
        enums.ChatMemberStatus.RESTRICTED,
    ):
        await cq.answer("✅ Verified! You can now use the bot.", show_alert=True)
        try:
            await cq.message.edit_text(
                "✅ <b>Access granted!</b>\n\nSend me a YouTube link or use /search to get started. 🚀",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=None,
            )
        except Exception:
            pass

    # Banned
    elif status == enums.ChatMemberStatus.BANNED:
        await cq.answer("❌ You are banned from the channel. Contact admin.", show_alert=True)

    # Not joined yet (status is None or LEFT)
    else:
        await cq.answer(
            "❌ You have not joined the channel yet!\nPlease join first then tap I Joined.",
            show_alert=True
        )
        
