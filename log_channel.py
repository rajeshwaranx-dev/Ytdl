"""
log_channel.py — Send download activity logs to the admin log channel.

Each event sends a clean formatted message to Config.LOG_CHANNEL_ID.
Events:
  - log_download_start  : user sent a URL / search pick
  - log_download_success: file uploaded successfully (with the file attached)
  - log_download_error  : download or upload failed
"""

import logging
from pathlib import Path

from pyrogram import Client
from pyrogram.types import Message
from pyrogram.errors import FloodWait, ChatWriteForbidden
from config import Config

logger = logging.getLogger("mnbots.log_channel")


def _user_line(user) -> str:
    """Format a compact user info string."""
    name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Unknown"
    mention = f"[{name}](tg://user?id={user.id})"
    uname = f"@{user.username}" if user.username else "no username"
    return f"{mention}  (`{user.id}` · {uname})"


async def _send(client: Client, text: str, **kwargs) -> None:
    """Send a message to the log channel, swallowing non-critical errors."""
    if not Config.LOG_CHANNEL_ID:
        return
    try:
        await client.send_message(Config.LOG_CHANNEL_ID, text, **kwargs)
    except FloodWait as e:
        import asyncio
        await asyncio.sleep(e.value)
        try:
            await client.send_message(Config.LOG_CHANNEL_ID, text, **kwargs)
        except Exception:
            pass
    except ChatWriteForbidden:
        logger.error("log_channel: bot has no write permission in LOG_CHANNEL_ID=%s", Config.LOG_CHANNEL_ID)
    except Exception as e:
        logger.warning("log_channel: failed to send log — %s", e)


# ─── Public helpers ───────────────────────────────────────────────────────────

async def log_download_start(
    client: Client,
    user,           # pyrogram User object
    yt_url: str,
    fmt: str,       # "mp4" or "mp3"
    quality: int | None = None,
) -> None:
    """Log that a user started a download."""
    q_label = f"`{quality}{'p' if fmt == 'mp4' else 'kbps'}`" if quality else "_selecting quality…_"
    icon = "🎬" if fmt == "mp4" else "🎵"
    text = (
        f"📥 **New Download Started**\n\n"
        f"👤 **User:** {_user_line(user)}\n"
        f"🔗 **URL:** {yt_url}\n"
        f"{icon} **Format:** `{fmt.upper()}`  •  **Quality:** {q_label}"
    )
    await _send(client, text, disable_web_page_preview=True)


async def log_download_success(
    client: Client,
    user,
    yt_url: str,
    fmt: str,
    quality: int | str,
    file_path: Path | None,
    title: str = "",
) -> None:
    """
    Log a successful download + upload.
    If file_path is provided and exists, forward the actual file to the log channel.
    """
    if not Config.LOG_CHANNEL_ID:
        return

    icon = "🎬" if fmt == "mp4" else "🎵"
    q_label = f"{quality}{'p' if fmt == 'mp4' else 'kbps'}"
    caption = (
        f"✅ **Download Successful**\n\n"
        f"👤 **User:** {_user_line(user)}\n"
        f"🔗 **URL:** {yt_url}\n"
        f"{icon} **Format:** `{fmt.upper()}`  •  **Quality:** `{q_label}`\n"
        + (f"🎞 **Title:** {title}\n" if title else "")
    )

    # Try to send the actual file to the log channel
    if file_path and file_path.exists():
        try:
            if fmt == "mp4":
                await client.send_video(
                    Config.LOG_CHANNEL_ID,
                    str(file_path),
                    caption=caption,
                    supports_streaming=True,
                )
            else:
                await client.send_audio(
                    Config.LOG_CHANNEL_ID,
                    str(file_path),
                    caption=caption,
                    title=title or file_path.stem,
                )
            return
        except FloodWait as e:
            import asyncio
            await asyncio.sleep(e.value)
        except Exception as e:
            logger.warning("log_channel: could not forward file — %s", e)

    # Fallback: just send the text log if file unavailable
    await _send(client, caption, disable_web_page_preview=True)


async def log_download_error(
    client: Client,
    user,
    yt_url: str,
    fmt: str,
    error: Exception | str,
    quality: int | None = None,
) -> None:
    """Log a failed download/upload."""
    icon = "🎬" if fmt == "mp4" else "🎵"
    q_label = f"`{quality}{'p' if fmt == 'mp4' else 'kbps'}`" if quality else "_unknown_"
    text = (
        f"❌ **Download Failed**\n\n"
        f"👤 **User:** {_user_line(user)}\n"
        f"🔗 **URL:** {yt_url}\n"
        f"{icon} **Format:** `{fmt.upper()}`  •  **Quality:** {q_label}\n"
        f"⚠️ **Error:** `{error}`"
    )
    await _send(client, text, disable_web_page_preview=True)


async def log_search(
    client: Client,
    user,
    query: str,
) -> None:
    """Log a /search query."""
    text = (
        f"🔍 **Search Query**\n\n"
        f"👤 **User:** {_user_line(user)}\n"
        f"🔎 **Query:** `{query}`"
    )
    await _send(client, text)


async def log_new_user(client: Client, user) -> None:
    """Log when a brand new user starts the bot."""
    text = (
        f"🆕 **New User**\n\n"
        f"👤 {_user_line(user)}"
    )
    await _send(client, text)
      
