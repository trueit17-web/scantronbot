import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
TRON_API_KEY = os.environ.get("TRON_API_KEY") or None
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "15"))
DB_PATH = os.environ.get("DB_PATH", "data/bot.db")
TIMEZONE = os.environ.get("TIMEZONE", "UTC")

_owner_id = os.environ.get("OWNER_ID")
OWNER_ID = int(_owner_id) if _owner_id else None
