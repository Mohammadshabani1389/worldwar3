import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{(BASE_DIR / 'database' / 'worldwar3.db').as_posix()}",
)

# SQLite URLs such as sqlite:///database/worldwar3.db are relative to the
# process working directory. The bot must always use its own project database
# even when it is launched from another directory.
if DATABASE_URL.startswith("sqlite:///") and not DATABASE_URL.startswith("sqlite:////"):
    db_part = DATABASE_URL[len("sqlite:///"):]
    if db_part and not db_part.startswith(":memory:"):
        DATABASE_URL = f"sqlite:///{(BASE_DIR / db_part).resolve().as_posix()}"

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN در فایل .env تنظیم نشده است."
    )

OWNER_ID = int(os.getenv("OWNER_ID", "0"))
