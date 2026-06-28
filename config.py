import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY")
GITHUB_PAT = os.getenv("GITHUB_PAT", "YOUR_GITHUB_PAT")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bot.db")
