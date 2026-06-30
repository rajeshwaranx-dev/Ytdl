"""
fsub.py — Force Subscribe (TechifyBots approach adapted for AskBotz YT Downloader)
- Supports normal channels (AUTH_CHANNELS) and approval-required channels (AUTH_REQ_CHANNELS)
- Auto-deletes fsub message when user joins
- MongoDB stores join requests — no fake bypass
- Global handler checks all private messages
"""

import logging
import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, filters, StopPropagation, enums
from pyrogram.types import (
    Message, InlineKeyboardButton, InlineKeyboardMarkup,
    ChatJoinRequest, ChatMemberUpdated
)
from pyrogram.errors import UserNotParticipant, ChatAdminRequired
from config import Config

logger = logging.getLogger(__name__)


# ─── DB helper ───────────────────────────────────────────────────────────────

class FsubDB:
    def __init__(self):
        client = AsyncIOMotorClient(Config.MONGO_URI)
        db     = client[Config.MONGO_DB]
        self.join_requests = db["join_requests"]
        self.fsub_cache    = db["fsub_cache"]

    async def add_join_req(self, user_id: int, channel_id: int):
        await self.join_requests.update_one(
            {"user_id": user_id},
            {"$addToSet": {"channels": channel_id},
             "$set": {"created_at": datetime.datetime.utcnow()}},
            upsert=True
        )

    async def has_joined_channel(self, user_id: int, channel_id: int) -> bool:
        doc = await self.join_requests.find_one({"user_id": user_id})
        return bool(doc and channel_id in doc.get("channels", []))

    async def save_fsub_msg(self, user_id: int, message_id: int):
        await self.fsub_cache.update_one(
            {"user_id": user_id},
            {"$set": {"message_id": message_id,
                      "created_at": datetime.datetime.utcnow()}},
            upsert=True
        )

    async def get_fsub_msg(self, user_id: int):
        doc = await self.fsub_cache.find_one({"user_id": user_id})
        return doc.get("message_id") if doc else None

    async def delete_fsub_msg_db(self, user_id: int):
        await self.fsub_cache.delete_one({"user_id": user_id})

    async def del_all(self):
        await self.join_requests.drop()
        await self.fsub_cache.drop()


db = FsubDB()


# ─── Check all channels joined ────────────────────────────────────────────────

async def check_all_joined(bot: Client, user_id: int) -> bool:
    for ch in Config.AUTH_CHANNELS:
        try:
            await bot.get_chat_member(ch, user_id)
        except UserNotParticipant:
            return False
        except Exception:
            pass
    for ch in Config.AUTH_REQ_CHANNELS:
        if not await db.has_joined_channel(user_id, ch):
            return False
    return True


# ─── Auto-delete fsub message after joining ───────────────────────────────────

async def auto_delete_fsub(client: Client, user_id: int):
    if not await check_all_joined(client, user_id):
        return
    msg_id = await db.get_fsub_msg(user_id)
    if msg_id:
        try:
            await client.delete_messages(user_id, msg_id)
        except Exception:
            pass
        await db.delete_fsub_msg_db(user_id)
    # Send welcome back message
    try:
        user    = await client.get_users(user_id)
        bot_me  = await client.get_me()
        await client.send_message(
            user_id,
            f"✅ **Welcome {user.mention}!**\n\n"
            f"You have joined all required channels.\n"
            f"Now send me a YouTube link to download! 🚀",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "▶️ Start",
                    url=f"https://t.me/{bot_me.username}?start=start"
                )
            ]])
        )
    except Exception as e:
        logger.error("Failed to send welcome message to %s: %s", user_id, e)


# ─── ChatJoinRequest handler (approval-required channels) ────────────────────

def _is_req_channel(_, __, update):
    return update.chat.id in Config.AUTH_REQ_CHANNELS


@Client.on_chat_join_request(filters.create(_is_req_channel))
async def on_join_request(client: Client, request: ChatJoinRequest):
    await db.add_join_req(request.from_user.id, request.chat.id)
    await auto_delete_fsub(client, request.from_user.id)


# ─── ChatMemberUpdated handler (normal channels) ─────────────────────────────

@Client.on_chat_member_updated(filters.chat(Config.AUTH_CHANNELS or [0]))
async def on_member_join(client: Client, update: ChatMemberUpdated):
    if not update.from_user:
        return
    if update.new_chat_member and update.new_chat_member.status in (
        enums.ChatMemberStatus.MEMBER,
        enums.ChatMemberStatus.ADMINISTRATOR,
        enums.ChatMemberStatus.OWNER,
    ):
        await auto_delete_fsub(client, update.from_user.id)


# ─── Core fsub check ─────────────────────────────────────────────────────────

async def _check_missing(bot: Client, user_id: int) -> list:
    """Returns list of (title, invite_link) for channels user hasn't joined."""
    missing = []

    for ch in Config.AUTH_CHANNELS:
        try:
            await bot.get_chat_member(ch, user_id)
        except UserNotParticipant:
            try:
                chat   = await bot.get_chat(ch)
                invite = await bot.create_chat_invite_link(ch)
                missing.append((chat.title, invite.invite_link))
            except ChatAdminRequired:
                missing.append(("Channel", Config.FSUB_CHANNEL_LINK))
            except Exception:
                missing.append(("Channel", Config.FSUB_CHANNEL_LINK))
        except Exception:
            pass

    for ch in Config.AUTH_REQ_CHANNELS:
        if not await db.has_joined_channel(user_id, ch):
            try:
                chat   = await bot.get_chat(ch)
                invite = await bot.create_chat_invite_link(ch, creates_join_request=True)
                missing.append((chat.title, invite.invite_link))
            except ChatAdminRequired:
                missing.append(("Channel", Config.FSUB_CHANNEL_LINK))
            except Exception:
                missing.append(("Channel", Config.FSUB_CHANNEL_LINK))

    return missing


async def get_fsub(bot: Client, message: Message) -> bool:
    """
    Returns True if user passed fsub check.
    Returns False and sends join prompt if not.
    """
    user_id = message.from_user.id

    # Admin bypass
    if user_id in Config.ADMINS:
        return True

    # Delete old fsub message if exists
    old_msg_id = await db.get_fsub_msg(user_id)
    if old_msg_id:
        try:
            await bot.delete_messages(user_id, old_msg_id)
        except Exception:
            pass
        await db.delete_fsub_msg_db(user_id)

    missing = await _check_missing(bot, user_id)
    if not missing:
        return True

    # Build join buttons
    buttons = []
    for i in range(0, len(missing), 2):
        row = []
        for j in range(2):
            if i + j < len(missing):
                title, link = missing[i + j]
                row.append(InlineKeyboardButton(f"📢 {title}", url=link))
        buttons.append(row)

    bot_me = await bot.get_me()
    buttons.append([InlineKeyboardButton(
        "🔄 Try Again",
        url=f"https://t.me/{bot_me.username}?start=start"
    )])

    msg = await message.reply(
        f"**🔒 Access Restricted!**\n\n"
        f"{message.from_user.mention}, to use this bot you must join "
        f"all required channels.\n\n"
        f"**Required Channels ({len(missing)})**\n\n"
        f"After joining, click **Try Again** below.",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    await db.save_fsub_msg(user_id, msg.id)
    return False


# ─── Global fsub checker (checks ALL private messages) ───────────────────────

@Client.on_message(
    filters.private & ~filters.bot & ~filters.service & ~filters.me,
    group=-10
)
async def global_fsub_checker(client: Client, message: Message):
    if not Config.IS_FSUB:
        return
    if not message.from_user:
        return
    if not await get_fsub(client, message):
        raise StopPropagation


# ─── /delreq admin command ────────────────────────────────────────────────────

@Client.on_message(filters.command("delreq") & filters.private)
async def del_requests(client: Client, message: Message):
    if message.from_user.id not in Config.ADMINS:
        return
    await db.del_all()
    await message.reply("✅ Join request cache cleared successfully.")
        
