import os
from pathlib import Path
from dotenv import load_dotenv

# Load daemon/.env
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

VAULT_DIR = Path(os.getenv("VAULT_DIR", "/Users/grasshop/Desktop/구직/경험정리"))
CONSTITUTION_FILE = Path(os.getenv("CONSTITUTION_FILE", str(VAULT_DIR / "00_헌법.md")))

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is not set in daemon/.env")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is not set in daemon/.env")
