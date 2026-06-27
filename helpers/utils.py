"""
helpers/utils.py — Shared utility functions used across plugins.
"""

import re
import sys
import time
import asyncio
import logging
import aiohttp
import aiofiles
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, MessageNotModified
from config import Config

logger = logging.getLogger("mnbots.utils")

# ─── Constants ───────────────────────────────────────────────────────────────

YT_API       = Config.YT_API
DOWNLOAD_DIR = Path(Config.DOWNLOAD_DIR)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

YT_REGEX = re.compile(
    r"(https?://)?(www\.)?"
    r"(youtube\.com/(watch\?v=|shorts/|embed/)|youtu\.be/)"
    r"[\w\-]{11}"
)

_TIMEOUTS = {
    "info":   aiohttp.ClientTimeout(total=30),
    "mp4":    aiohttp.ClientTimeout(total=300),
    "mp3":    aiohttp.ClientTimeout(total=180),
    "search": aiohttp.ClientTimeout(total=20),
}
_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=60)
_MAX_RETRIES     = 3
_RETRY_DELAY     = 5


# ─── URL helpers ─────────────────────────────────────────────────────────────

def extract_url(text: str) -> str | None:
    m = YT_REGEX.search(text)
    return m.group(0) if m else None


def vid_id_from_url(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w\-]{11})", url)
    return m.group(1) if m else url


def clean_audio_title(filename: str) -> str:
    name = Path(filename).stem
    name = re.sub(r"[\(\[][^\)\]]*[\)\]]$", "", name).strip()
    return name or filename


# ─── Formatting helpers ──────────────────────────────────────────────────────

def progress_bar(done: int, total: int, width: int = 16) -> str:
    pct    = done / total if total else 0
    filled = int(width * pct)
    bar    = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct*100:.1f}%"


def fmt_size(b: int) -> str:
    if b >= 1_073_741_824: return f"{b/1_073_741_824:.2f} GB"
    if b >= 1_048_576:     return f"{b/1_048_576:.1f} MB"
    return f"{b/1024:.1f} KB"


def fmt_speed(bps: float) -> str:
    if bps >= 1_048_576: return f"{bps/1_048_576:.2f} MB/s"
    return f"{bps/1024:.1f} KB/s"


# ─── Message helpers ─────────────────────────────────────────────────────────

async def safe_edit(msg: Message, text: str, **kwargs) -> None:
    try:
        await msg.edit(text, **kwargs)
    except MessageNotModified:
        pass
    except FloodWait as e:
        await asyncio.sleep(e.value)
    except Exception:
        pass


# ─── API helpers ─────────────────────────────────────────────────────────────

async def api_get(session: aiohttp.ClientSession, path: str, **params) -> dict | list:
    url      = f"{YT_API}/{path}"
    timeout  = _TIMEOUTS.get(path, _DEFAULT_TIMEOUT)
    last_exc = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with session.get(url, params=params, timeout=timeout) as r:
                r.raise_for_status()
                return await r.json()
        except (asyncio.TimeoutError, aiohttp.ServerDisconnectedError) as e:
            last_exc = e
            if attempt < _MAX_RETRIES:
                logger.warning("api_get /%s timeout (attempt %d/%d), retrying in %ds",
                               path, attempt, _MAX_RETRIES, _RETRY_DELAY)
                await asyncio.sleep(_RETRY_DELAY)
        except aiohttp.ClientResponseError as e:
            if e.status in (502, 503, 504) and attempt < _MAX_RETRIES:
                last_exc = e
                logger.warning("api_get /%s HTTP %d (attempt %d/%d), retrying in %ds",
                               path, e.status, attempt, _MAX_RETRIES, _RETRY_DELAY)
                await asyncio.sleep(_RETRY_DELAY)
                continue
            raise

    raise asyncio.TimeoutError(
        f"/{path} did not respond after {_MAX_RETRIES} attempts"
    ) from last_exc


async def fetch_info(session, yt_url):
    return await api_get(session, "info", url=yt_url)


async def fetch_mp4(session, yt_url, quality=None):
    p = {"url": yt_url}
    if quality is not None: p["quality"] = quality
    return await api_get(session, "mp4", **p)


async def fetch_mp3(session, yt_url, quality=None):
    p = {"url": yt_url}
    if quality is not None: p["quality"] = quality
    return await api_get(session, "mp3", **p)


async def search_yt(session, query):
    result = await api_get(session, "search", s=query)
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for key in ("results", "videos", "items", "data"):
            if isinstance(result.get(key), list):
                return result[key]
        logger.warning("search_yt unexpected dict shape: %r", list(result.keys()))
    return []


# ─── File download with progress ─────────────────────────────────────────────

async def download_file(url: str, dest: Path, msg: Message) -> Path:
    start     = time.time()
    last_edit = 0.0
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=3600)) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0))
            done  = 0
            async with aiofiles.open(dest, "wb") as f:
                async for chunk in r.content.iter_chunked(1024 * 256):
                    await f.write(chunk)
                    done += len(chunk)
                    now   = time.time()
                    if now - last_edit >= 3:
                        last_edit = now
                        elapsed   = now - start
                        speed     = done / elapsed if elapsed else 0
                        eta       = (total - done) / speed if speed and total else 0
                        bar       = progress_bar(done, total)
                        eta_str   = f"{int(eta//60)}m {int(eta%60)}s" if eta >= 60 else f"{int(eta)}s"
                        try:
                            await msg.edit(
                                f"⬇️ **Downloading...**\n"
                                f"{bar}\n"
                                f"`{fmt_size(done)}` / `{fmt_size(total) if total else '?'}`\n"
                                f"🚀 `{fmt_speed(speed)}`   ⏱ ETA `{eta_str}`"
                            )
                        except FloodWait as e:
                            await asyncio.sleep(e.value)
                        except Exception:
                            pass
    return dest


# ─── Button builders ─────────────────────────────────────────────────────────

def quality_buttons(qualities, vid_id, kind) -> InlineKeyboardMarkup:
    buttons, row = [], []
    for q in qualities:
        label = f"{q}p" if kind == "mp4" else f"{q}kbps"
        row.append(InlineKeyboardButton(label, callback_data=f"dl:{kind}:{vid_id}:{q}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="dl:cancel")])
    return InlineKeyboardMarkup(buttons)


def search_result_buttons(results) -> InlineKeyboardMarkup:
    buttons = []
    videos  = [r for r in results if r.get("type") == "video"][:8]
    for v in videos:
        title  = v["title"][:40]
        vid_id = v["videoId"]
        buttons.append([InlineKeyboardButton(f"▶ {title}", callback_data=f"sr:{vid_id}")])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="dl:cancel")])
    return InlineKeyboardMarkup(buttons)

