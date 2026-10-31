import os

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.environ.get("FOLLOW_THROUGH_DB_PATH", "follow_through.db")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
LOG_PATH = os.environ.get("FOLLOW_THROUGH_LOG_PATH", "follow_through.log")
BACKUP_DEST_DIR = os.environ.get("FOLLOW_THROUGH_BACKUP_DEST_DIR", "")
TIMEZONE = os.environ.get("FOLLOW_THROUGH_TIMEZONE", "UTC")
