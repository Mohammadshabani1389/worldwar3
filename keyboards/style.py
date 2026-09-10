"""Subtle Telegram button styling for the bot UI.

Keeps most buttons neutral and applies only a few semantic colors:
- success: confirm/build/enable/receive
- danger: delete/ban/remove/disable
- primary: main navigation/settings/selection
"""

from telegram import InlineKeyboardButton as _InlineKeyboardButton
import hashlib

# Telegram limits callback_data to 1-64 UTF-8 bytes.  Long dynamic callback
# payloads are replaced with a compact in-process token; callbacks.py resolves
# the token before dispatch.
_LONG_CALLBACKS: dict[str, str] = {}

def resolve_callback_data(data):
    return _LONG_CALLBACKS.get(str(data), data)

def _safe_callback_data(value):
    if value is None:
        return None
    raw = str(value)
    if len(raw.encode("utf-8")) <= 64:
        return value
    token = "cb:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    _LONG_CALLBACKS[token] = raw
    return token


def _pick_style(text: str, callback_data=None):
    t = (text or "").strip().lower()
    c = str(callback_data or "").lower()

    # Keep back/cancel/refresh and ordinary informational buttons neutral.
    if any(x in t for x in ("برگشت", "لغو", "رفرش", "بازگشت")):
        return None

    # Destructive actions: red, but not every button containing a related word.
    if any(x in t for x in ("حذف", "بن ", "بن‌", "رفع بن", "غیرفعال", "پاکسازی", "کاهش موجودی", "برداشتن")):
        return "danger"
    if any(x in c for x in (":delete", ":ban", "remove", "clear", "disable")):
        return "danger"

    # Positive actions: green.
    if any(x in t for x in ("تأیید", "تایید", "ساخت", "ارتقا", "فعال", "دریافت", "افزایش", "اضافه", "ثبت", "انتخاب")):
        return "success"
    if any(x in c for x in ("confirm", "build", "upgrade", "enable", "receive", "add")):
        return "success"

    # Main navigation / neutral selection: blue, sparingly.
    if any(x in t for x in ("مدیریت", "تنظیمات", "آمار", "اطلاعات", "لیست", "جستجو", "تبادل", "اقتصاد", "معدن", "مرکز فرماندهی", "کشور")):
        return "primary"
    if any(x in c for x in ("settings", "stats", "admin", "owner", "list", "search", "exchange", "country", "mine", "command")):
        return "primary"

    return None


def styled_button(*args, **kwargs):
    """Drop-in replacement for InlineKeyboardButton with subtle auto styling."""
    if "callback_data" in kwargs:
        kwargs["callback_data"] = _safe_callback_data(kwargs.get("callback_data"))
    elif len(args) > 0:
        # InlineKeyboardButton accepts callback_data as a keyword in all current
        # PTB versions used by this project; positional handling is intentionally
        # left untouched.
        pass
    if "style" not in kwargs:
        text = kwargs.get("text") if "text" in kwargs else (args[0] if args else "")
        callback_data = kwargs.get("callback_data")
        style = _pick_style(text, callback_data)
        if style:
            kwargs["style"] = style
    return _InlineKeyboardButton(*args, **kwargs)
