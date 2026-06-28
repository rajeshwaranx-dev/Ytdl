"""
plugins/admin.py — Admin commands: /stats and /broadcast.
Only accessible by admins listed in Config.ADMINS.
"""

import sys
import asyncio
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait, InputUserDeactivated, UserIsBlocked, PeerIdInvalid
from config import Config
from database import users as users_col, get_stats

logger = logging.getLogger("mnbots.admin")


# ─── Admin filter ─────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in Config.ADMINS


# ─── /stats ──────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("stats"))
async def cmd_stats(client: Client, msg: Message):
    if not is_admin(msg.from_user.id):
        return await msg.reply("❌ You are not authorized to use this command.", quote=True)

    status = await msg.reply("📊 Fetching stats...", quote=True)

    try:
        stats = get_stats()
    except Exception as e:
        return await status.edit(f"❌ Failed to fetch stats: `{e}`")

    text = (
        "📊 **Bot Statistics**\n\n"
        "╔━━━━━━━━━━━━━━━━━╗\n"
        "       **User Stats**\n"
        "╚━━━━━━━━━━━━━━━━━╝\n"
        f"👥 **Total Users:** `{stats['total_users']:,}`\n"
        f"✅ **Unlimited Users:** `{stats['unlimited_users']:,}`\n"
        f"🔒 **Limited Users:** `{stats['limited_users']:,}`\n\n"
        "╔━━━━━━━━━━━━━━━━━╗\n"
        "    **Activity Stats**\n"
        "╚━━━━━━━━━━━━━━━━━╝\n"
        f"⬇️ **Total Downloads:** `{stats['total_downloads']:,}`\n"
        f"🔗 **Total Referrals:** `{stats['total_referrals']:,}`"
    )

    await status.edit(text)


# ─── /broadcast ───────────────────────────────────────────────────────────────

@Client.on_message(filters.command("broadcast"))
async def cmd_broadcast(client: Client, msg: Message):
    if not is_admin(msg.from_user.id):
        return await msg.reply("❌ You are not authorized to use this command.", quote=True)

    # Must reply to a message to broadcast it
    if not msg.reply_to_message:
        return await msg.reply(
            "ℹ️ **Usage:**\n"
            "Reply to any message with `/broadcast` to send it to all users.\n\n"
            "**Optional flags:**\n"
            "`/broadcast pin` — also pin the message\n"
            "`/broadcast forward` — forward instead of copy",
            quote=True
        )

    flags     = msg.text.split()[1:] if len(msg.text.split()) > 1 else []
    do_pin    = "pin"     in flags
    do_forward = "forward" in flags
    bcast_msg = msg.reply_to_message

    # Get all user IDs
    all_users = [u["_id"] for u in users_col.find({}, {"_id": 1})]
    total     = len(all_users)

    status = await msg.reply(
        f"📢 **Broadcasting to {total:,} users...**\n\n"
        f"✅ Success: `0`\n❌ Failed: `0`\n⏳ Pending: `{total:,}`",
        quote=True
    )

    success  = 0
    failed   = 0
    blocked  = 0
    deleted  = 0
    last_edit = asyncio.get_event_loop().time()

    for user_id in all_users:
        try:
            if do_forward:
                sent = await bcast_msg.forward(user_id)
            else:
                sent = await bcast_msg.copy(user_id)

            if do_pin:
                try:
                    await sent.pin(disable_notification=True)
                except Exception:
                    pass

            success += 1

        except FloodWait as e:
            await asyncio.sleep(e.value)
            # Retry once after flood wait
            try:
                if do_forward:
                    await bcast_msg.forward(user_id)
                else:
                    await bcast_msg.copy(user_id)
                success += 1
            except Exception:
                failed += 1

        except UserIsBlocked:
            blocked += 1
            failed  += 1

        except InputUserDeactivated:
            deleted += 1
            failed  += 1

        except (PeerIdInvalid, Exception):
            failed += 1

        # Update status every 5 seconds
        now = asyncio.get_event_loop().time()
        if now - last_edit >= 5:
            last_edit = now
            pending   = total - success - failed
            try:
                await status.edit(
                    f"📢 **Broadcasting...**\n\n"
                    f"✅ Success: `{success:,}`\n"
                    f"❌ Failed: `{failed:,}`\n"
                    f"⏳ Pending: `{pending:,}`"
                )
            except Exception:
                pass

        await asyncio.sleep(0.05)  # Avoid hitting Telegram rate limits

    # Final report
    await status.edit(
        f"📢 **Broadcast Complete!**\n\n"
        f"👥 **Total Users:** `{total:,}`\n"
        f"✅ **Success:** `{success:,}`\n"
        f"❌ **Failed:** `{failed:,}`\n"
        f"🚫 **Blocked:** `{blocked:,}`\n"
        f"🗑 **Deleted Accounts:** `{deleted:,}`"
    )
