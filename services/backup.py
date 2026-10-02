"""پشتیبان‌گیری خودکار از SQLite و ارسال آن برای Owner."""
from __future__ import annotations
import asyncio, logging, sqlite3, zipfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from config import BASE_DIR, DATABASE_URL, OWNER_ID
from database.db import SessionLocal
from services.settings import get_backup_interval, get_backup_started, get_backup_execution_time
from services.error_reporting import report_exception

log = logging.getLogger("worldwar3_bot.backup")
TZ = ZoneInfo("Asia/Tehran")
BACKUP_DIR = BASE_DIR / "backups"

def database_path() -> Path:
    if not DATABASE_URL.startswith("sqlite:"):
        raise RuntimeError("پشتیبان‌گیری خودکار فقط برای پایگاه‌داده SQLite فعال است.")
    raw = DATABASE_URL[len("sqlite:/// "):].strip() if DATABASE_URL.startswith("sqlite:/// ") else DATABASE_URL[len("sqlite:///"):]
    if raw.startswith("/"): return Path("/" + raw.lstrip("/"))
    return (BASE_DIR / raw).resolve()

def _zip_database() -> Path:
    """Create a SQLite snapshot; Owner receives it as worldwar3.db."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    source=database_path()
    if not source.exists(): raise FileNotFoundError(f"Database not found: {source}")
    stamp=datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
    snapshot=BACKUP_DIR/f"worldwar3_{stamp}.db"
    src=sqlite3.connect(str(source), timeout=30); dst=sqlite3.connect(str(snapshot))
    try:
        with dst: src.backup(dst)
    finally:
        dst.close(); src.close()
    return snapshot

async def _send_backup(bot, archive: Path) -> bool:
    if not OWNER_ID:
        log.error("OWNER_ID is not configured; backup retained: %s", archive); return False
    caption=("💾 <b>پشتیبان خودکار پایگاه‌داده</b>\n\n"
             f"🕐 زمان: {datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')}\n"
             "🔒 این فایل فقط برای نگهداری است و در روند عادی بازی استفاده نمی‌شود.")
    with archive.open("rb") as fh:
        await bot.send_document(chat_id=int(OWNER_ID),document=fh,filename="worldwar3.db",caption=caption,parse_mode="HTML")
    return True

async def _retry_pending(app):
    pending=sorted(BACKUP_DIR.glob("worldwar3_*.db"))
    for archive in pending:
        try:
            if await _send_backup(app.bot,archive): archive.unlink(missing_ok=True)
        except Exception as exc:
            log.exception("Backup retry failed; keeping %s",archive)
            try:
                await report_exception(app.bot, exc, source="🚨 خطای تلاش مجدد پشتیبان")
            except Exception:
                pass
            break

def _next_execution(now: datetime, execution_time: str, interval_minutes: int = 60) -> datetime:
    """اولین اجرای برنامه‌ریزی‌شده بعد از now را برمی‌گرداند.

    زمان اجرا لنگر برنامه است؛ بنابراین اگر ربات هنگام یک یا چند نوبت خاموش بوده
    باشد، بعد از روشن شدن نزدیک‌ترین نوبت آینده اجرا می‌شود. مثلاً شروع 18:00
    و فاصله 60 دقیقه، روشن شدن در 19:30 را به اجرای بعدی در 20:00 می‌رساند.
    """
    try:
        h,m=map(int,str(execution_time).split(":",1))
        h=max(0,min(23,h)); m=max(0,min(59,m))
    except Exception:
        h,m=0,0
    interval=max(1,int(interval_minutes or 60))
    anchor=now.replace(hour=h,minute=m,second=0,microsecond=0)
    if now < anchor:
        return anchor
    elapsed=(now-anchor).total_seconds()
    steps=int(elapsed // (interval*60)) + 1
    return anchor + timedelta(minutes=steps*interval)

async def backup_worker(app):
    await asyncio.sleep(5)
    next_run=None
    schedule_key=None
    while True:
        try:
            with SessionLocal() as session:
                started=get_backup_started(session)
                interval=max(1,int(get_backup_interval(session)))
                execution_time=get_backup_execution_time(session)
            await _retry_pending(app)
            current_key=(bool(started), int(interval), str(execution_time))
            if not started:
                next_run=None
                schedule_key=None
                await asyncio.sleep(5)
                continue
            now=datetime.now(TZ)
            # تغییر هرکدام از وضعیت/زمان اجرا/فاصله، برنامه قبلی را بی‌درنگ باطل می‌کند.
            if schedule_key != current_key:
                schedule_key=current_key
                next_run=_next_execution(now,execution_time,interval)
            elif next_run is None or next_run <= now:
                next_run=_next_execution(now,execution_time,interval)
            wait=max(1,(next_run-now).total_seconds())
            await asyncio.sleep(wait)
            with SessionLocal() as session:
                if not get_backup_started(session):
                    next_run=None
                    continue
                interval=max(1,int(get_backup_interval(session)))
            archive=await asyncio.to_thread(_zip_database)
            try:
                if await _send_backup(app.bot,archive): archive.unlink(missing_ok=True)
            except Exception as exc:
                log.exception("Fresh backup delivery failed; keeping %s",archive)
                await report_exception(app.bot, exc, source="🚨 خطای ارسال پشتیبان")
            next_run=datetime.now(TZ)+timedelta(minutes=interval)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Backup worker error")
            try:
                await report_exception(app.bot, exc, source='🚨 خطای پشتیبان‌گیری خودکار')
            except Exception:
                pass
            next_run=None
            await asyncio.sleep(30)
