#!/bin/bash
# Run this script on your server to apply all settings changes

# 1. Add settings functions to database.py
cat >> /root/Ytdl/database.py << 'PYEOF'


# ─── Bot Settings (thumbnail/caption) ─────────────────────────────────────────

def get_bot_settings() -> dict:
    """Returns global bot settings with defaults."""
    doc = settings.find_one({"_id": "bot_settings"})
    if not doc:
        doc = {
            "_id": "bot_settings",
            "thumb_mode": "random",
            "custom_thumb_file_id": None,
            "caption_template": "**{title}**",
        }
        settings.insert_one(doc)
    return doc


def set_thumb_mode(mode: str):
    settings.update_one({"_id": "bot_settings"}, {"$set": {"thumb_mode": mode}}, upsert=True)


def set_custom_thumb(file_id: str):
    settings.update_one({"_id": "bot_settings"}, {"$set": {"custom_thumb_file_id": file_id, "thumb_mode": "custom"}}, upsert=True)


def set_caption_template(template: str):
    settings.update_one({"_id": "bot_settings"}, {"$set": {"caption_template": template}}, upsert=True)
PYEOF

# 2. Add download_youtube_thumbnail to helpers/utils.py
cat >> /root/Ytdl/helpers/utils.py << 'PYEOF'


async def download_youtube_thumbnail(thumb_url: str, dest_path: Path) -> Path | None:
    """Downloads a YouTube thumbnail image to dest_path. Returns path or None on failure."""
    if not thumb_url:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(thumb_url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    return None
                data = await r.read()
                async with aiofiles.open(dest_path, "wb") as f:
                    await f.write(data)
                return dest_path
    except Exception as e:
        logger.warning("download_youtube_thumbnail failed: %s", e)
        return None
PYEOF

echo "Database and utils updated successfully"

