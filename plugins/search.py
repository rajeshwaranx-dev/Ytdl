"""
plugins/search.py — /search command handler.
"""

import sys
import aiohttp
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from fsub import get_fsub_buttons
from log_channel import log_search
from helpers.utils import safe_edit, search_yt, search_result_buttons
from database import ensure_user

FSUB_TEXT = (
    "<b>⚠️ You must join our channel to use this bot!</b>\n\n"
    "Join below then tap <i>Try Again</i>."
)


@Client.on_message(filters.command("search"))
async def cmd_search(client: Client, msg: Message):
    user = msg.from_user
    if not user:
        return

    ensure_user({"id": user.id, "first_name": user.first_name or "", "last_name": user.last_name or "", "username": user.username or ""})

    buttons = await get_fsub_buttons(client, user.id)
    if buttons:
        buttons.append([InlineKeyboardButton("♻️ I've Joined — Try Again", callback_data="fsub_check")])
        await msg.reply(
            FSUB_TEXT,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=enums.ParseMode.HTML,
            quote=True,
        )
        return

    query = msg.text.split(None, 1)[1].strip() if len(msg.text.split()) > 1 else ""
    if not query:
        return await msg.reply("Usage: `/search <query>`", quote=True)

    await log_search(client, msg.from_user, query)

    status = await msg.reply("🔍 Searching YouTube...", quote=True)
    try:
        async with aiohttp.ClientSession() as session:
            results = await search_yt(session, query)
    except Exception as e:
        return await safe_edit(status, f"❌ Search failed: `{e}`")

    videos = [r for r in results if r.get("type") == "video"]
    if not videos:
        return await safe_edit(status, f"❌ No video results found for `{query}`.")

    markup = search_result_buttons(results)
    await safe_edit(status, f"🔎 **Results for:** `{query}`\nPick a video:", reply_markup=markup)
    
