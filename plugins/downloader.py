"""
plugins/downloader.py — YouTube URL handler and all download-related callbacks.
FSub is handled globally by fsub.py — no fsub checks needed here.
Supports admin-configurable thumbnail mode (random/youtube/custom) and caption template.
"""

import sys
import time
import asyncio
import logging
import aiohttp
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait
from config import Config
from log_channel import log_download_start, log_download_success, log_download_error
from database import ensure_user, get_bot_settings
from helpers.utils import (
    extract_url, vid_id_from_url, clean_audio_title,
    safe_edit, fetch_info, fetch_mp4, fetch_mp3,
    download_file, quality_buttons, search_result_buttons,
    progress_bar, fmt_size, fmt_speed, get_duration,
    generate_thumbnail, download_youtube_thumbnail,
    DOWNLOAD_DIR,
)

logger = logging.getLogger("mnbots.downloader")

# Cache video info keyed by vid_id so we have title/thumbnail at download time
_video_info_cache: dict[str, dict] = {}


# ─── YouTube URL handler ──────────────────────────────────────────────────────

@Client.on_message(filters.private & filters.text & ~filters.command(["start", "help", "about", "search", "settings", "cancel", "stats", "broadcast", "delreq"]))
async def handle_url(client: Client, msg: Message):
    if not msg.text:
        return

    yt_url = extract_url(msg.text)
    if not yt_url:
        return

    user = msg.from_user
    if not user:
        return

    ensure_user({"id": user.id, "first_name": user.first_name or "", "last_name": user.last_name or "", "username": user.username or ""})

    status = await msg.reply("🔄 Fetching info...", quote=True)
    try:
        async with aiohttp.ClientSession() as session:
            info = await fetch_info(session, yt_url)
    except Exception as e:
        return await safe_edit(status, f"❌ Failed to fetch info: `{e}`")

    title  = info.get("title", "Unknown")
    thumb  = info.get("thumbnail", "")
    vid_id = vid_id_from_url(yt_url)

    _video_info_cache[vid_id] = {"title": title, "thumbnail": thumb}

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 MP4 (Video)", callback_data=f"fmt:mp4:{vid_id}"),
            InlineKeyboardButton("🎵 MP3 (Audio)", callback_data=f"fmt:mp3:{vid_id}"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="dl:cancel")],
    ])

    caption = f"**{title}**\n\nChoose format:"
    try:
        if thumb:
            await status.delete()
            await msg.reply_photo(thumb, caption=caption, reply_markup=markup)
        else:
            await safe_edit(status, caption, reply_markup=markup)
    except Exception:
        await safe_edit(status, caption, reply_markup=markup)


# ─── Cancel ───────────────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^dl:cancel$"))
async def cb_cancel(client: Client, cq: CallbackQuery):
    await cq.answer("Cancelled.")
    try:
        await cq.message.edit_reply_markup(None)
        await cq.message.edit_text("❌ Cancelled.")
    except Exception:
        pass


# ─── Format selection ─────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^fmt:(mp4|mp3):(.+)$"))
async def cb_format(client: Client, cq: CallbackQuery):
    parts  = cq.data.split(":", 2)
    kind   = parts[1]
    vid_id = parts[2]
    yt_url = f"https://youtu.be/{vid_id}"

    await cq.answer("Fetching qualities...")
    try:
        await cq.message.edit_reply_markup(None)
    except Exception:
        pass

    status = await cq.message.reply("⏳ Fetching available qualities...")
    try:
        async with aiohttp.ClientSession() as session:
            data = await fetch_mp4(session, yt_url) if kind == "mp4" else await fetch_mp3(session, yt_url)
    except Exception as e:
        return await safe_edit(status, f"❌ Error: `{e}`")

    qualities = data.get("availableQuality", [])
    if not qualities:
        return await safe_edit(status, "❌ No qualities available.")

    markup = quality_buttons(qualities, vid_id, kind)
    icon   = "🎬" if kind == "mp4" else "🎵"
    await safe_edit(status, f"{icon} Select quality for **{'Video' if kind == 'mp4' else 'Audio'}**:", reply_markup=markup)


# ─── Search result selection ──────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^sr:(.+)$"))
async def cb_search_result(client: Client, cq: CallbackQuery):
    vid_id = cq.data.split(":", 1)[1]
    yt_url = f"https://youtu.be/{vid_id}"

    await cq.answer()
    try:
        await cq.message.edit_reply_markup(None)
    except Exception:
        pass

    status = await cq.message.reply("🔄 Fetching info...")
    try:
        async with aiohttp.ClientSession() as session:
            info = await fetch_info(session, yt_url)
    except Exception as e:
        return await safe_edit(status, f"❌ Failed: `{e}`")

    title = info.get("title", "Unknown")
    thumb = info.get("thumbnail", "")
    _video_info_cache[vid_id] = {"title": title, "thumbnail": thumb}

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 MP4", callback_data=f"fmt:mp4:{vid_id}"),
            InlineKeyboardButton("🎵 MP3", callback_data=f"fmt:mp3:{vid_id}"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="dl:cancel")],
    ])

    caption = f"**{title}**\n\nChoose format:"
    try:
        if thumb:
            await status.delete()
            await cq.message.reply_photo(thumb, caption=caption, reply_markup=markup)
        else:
            await safe_edit(status, caption, reply_markup=markup)
    except Exception:
        await safe_edit(status, caption, reply_markup=markup)


# ─── Quality → Download ───────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^dl:(mp4|mp3):(.+):(\d+)$"))
async def cb_download(client: Client, cq: CallbackQuery):
    parts   = cq.data.split(":", 3)
    kind    = parts[1]
    vid_id  = parts[2]
    quality = int(parts[3])
    yt_url  = f"https://youtu.be/{vid_id}"
    user    = cq.from_user

    await cq.answer("Starting download...")
    try:
        await cq.message.edit_reply_markup(None)
    except Exception:
        pass

    await log_download_start(client, user, yt_url, kind, quality)
    status = await cq.message.reply("⚙️ **Processing...** `0s elapsed`")
    dest: Path | None = None
    thumb_path: Path | None = None

    async def _ticker(msg: Message, stop: asyncio.Event) -> None:
        spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        i, t0   = 0, time.time()
        while not stop.is_set():
            await asyncio.sleep(5)
            if stop.is_set():
                break
            elapsed = int(time.time() - t0)
            m, s    = divmod(elapsed, 60)
            try:
                await msg.edit(f"{spinner[i % len(spinner)]} **Processing...** `{f'{m}m {s}s' if m else f'{s}s'} elapsed`\n`Muxing & encoding — please wait`")
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception:
                pass
            i += 1

    stop_ticker = asyncio.Event()
    ticker_task = asyncio.create_task(_ticker(status, stop_ticker))

    try:
        async with aiohttp.ClientSession() as session:
            data = await fetch_mp4(session, yt_url, quality) if kind == "mp4" else await fetch_mp3(session, yt_url, quality)
    except Exception as e:
        stop_ticker.set()
        await ticker_task
        await safe_edit(status, f"❌ Failed: `{e}`")
        await log_download_error(client, user, yt_url, kind, e, quality)
        return
    finally:
        stop_ticker.set()

    try:
        if not data.get("status"):
            err = "API returned failure status."
            await safe_edit(status, f"❌ {err}")
            await log_download_error(client, user, yt_url, kind, err, quality)
            return

        dl_url = data.get("url")
        if not dl_url:
            err = "API did not return a download URL."
            await safe_edit(status, f"❌ {err}")
            await log_download_error(client, user, yt_url, kind, err, quality)
            return

        filename = data.get("filename", f"{vid_id}.{kind}")
        q_label  = data.get("quality", str(quality))
        cached   = _video_info_cache.get(vid_id, {})
        title    = cached.get("title") or data.get("title", clean_audio_title(filename))
        yt_thumb_url = cached.get("thumbnail", "")
        dest     = DOWNLOAD_DIR / filename

        await safe_edit(status, "⬇️ **Downloading...**\n`Starting...`")
        await download_file(dl_url, dest, status)

        size_mb  = dest.stat().st_size / 1e6
        duration = await get_duration(dest)

        # ── Thumbnail selection based on admin settings ─────────────────────
        bot_settings = get_bot_settings()
        thumb_mode   = bot_settings.get("thumb_mode", "random")

        if kind == "mp4":
            if thumb_mode == "random":
                thumb_path = await generate_thumbnail(dest)

            elif thumb_mode == "youtube":
                jpg_dest = dest.with_suffix(".jpg")
                thumb_path = await download_youtube_thumbnail(yt_thumb_url, jpg_dest)
                if not thumb_path:
                    thumb_path = await generate_thumbnail(dest)  # fallback

            elif thumb_mode == "custom":
                custom_file_id = bot_settings.get("custom_thumb_file_id")
                thumb_path = custom_file_id if custom_file_id else await generate_thumbnail(dest)

        await safe_edit(status, f"📤 **Uploading** `{filename}`...")

        caption_template = bot_settings.get("caption_template", "**{title}**")
        try:
            caption = caption_template.replace("{title}", title)
        except Exception:
            caption = f"**{title}**"

        _up_last  = [time.time()]
        _up_start = [time.time()]

        async def _upload_progress(current: int, total: int) -> None:
            now = time.time()
            if now - _up_last[0] < 3 and current < total:
                return
            _up_last[0] = now
            elapsed     = now - _up_start[0]
            speed       = current / elapsed if elapsed else 0
            eta         = (total - current) / speed if speed and current < total else 0
            eta_str     = f"{int(eta//60)}m {int(eta%60)}s" if eta >= 60 else f"{int(eta)}s"
            await safe_edit(status, f"📤 **Uploading...**\n{progress_bar(current, total)}\n`{fmt_size(current)}` / `{fmt_size(total)}`\n🚀 `{fmt_speed(speed)}`   ⏱ ETA `{eta_str}`")

        if size_mb > Config.MAX_FILE_SIZE:
            await safe_edit(status, f"⚠️ File is `{size_mb:.0f} MB`, too large for Telegram.\n[Direct Download Link]({dl_url})")
            await log_download_success(client, user, yt_url, kind, q_label, None, title)
        elif kind == "mp4":
            thumb_arg = str(thumb_path) if thumb_path else None
            await cq.message.reply_video(str(dest), caption=caption, supports_streaming=True, duration=duration, thumb=thumb_arg, progress=_upload_progress)
            await status.delete()
            await log_download_success(client, user, yt_url, kind, q_label, dest, title)
        else:
            await cq.message.reply_audio(str(dest), caption=caption, title=clean_audio_title(filename), duration=duration, progress=_upload_progress)
            await status.delete()
            await log_download_success(client, user, yt_url, kind, q_label, dest, title)

    except FloodWait as e:
        await asyncio.sleep(e.value)
        await safe_edit(status, "⚠️ Hit flood limit, please retry.")
        await log_download_error(client, user, yt_url, kind, "FloodWait during upload", quality)
    except Exception as e:
        logger.exception("Download/upload failed for %s", vid_id)
        await safe_edit(status, f"❌ Failed: `{e}`")
        await log_download_error(client, user, yt_url, kind, e, quality)
    finally:
        if dest and dest.exists():
            try:
                dest.unlink()
            except Exception:
                pass
        if thumb_path and isinstance(thumb_path, Path) and thumb_path.exists():
            try:
                thumb_path.unlink()
            except Exception:
                pass
        _video_info_cache.pop(vid_id, None)
    
