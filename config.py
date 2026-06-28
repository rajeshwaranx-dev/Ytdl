import os

class Config:
    YT_API        = os.environ.get("YT_API", "https://youtube-downloader.mn-bots.workers.dev")
    MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE", 2000))  # MB
    DOWNLOAD_DIR  = "/tmp/mnbots"

    # MongoDB
    MONGO_URI = os.environ.get("MONGO_URI", "")
    MONGO_DB  = os.environ.get("MONGO_DB", "mnbots")

    # Force Subscribe
    FSUB_CHANNEL_ID   = int(os.environ.get("FSUB_CHANNEL_ID", "0"))
    FSUB_CHANNEL_LINK = os.environ.get("FSUB_CHANNEL_LINK", "https://t.me/yourchannel")

    # Log Channel
    LOG_CHANNEL_ID = int(os.environ.get("LOG_CHANNEL_ID", "0"))

    # Bot UI
    START_IMAGE  = os.environ.get("START_IMAGE",  "https://ibb.co/DP2wDxbq")
    CHANNEL_LINK =
