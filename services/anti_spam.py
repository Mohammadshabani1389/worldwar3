"""Fixed, in-code anti-spam limits for users and group bot output."""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from database.db import SessionLocal
from services.settings import (get_anti_spam_enabled, get_anti_spam_user_max, get_anti_spam_user_window, get_anti_spam_group_max, get_anti_spam_group_window)

USER_LIMIT_DURATION = 60.0

@dataclass
class UserState:
    requests: deque
    limited_until: float = 0.0
    warning_message_id: int | None = None

_users: dict[int, UserState] = {}
_group_messages: dict[int, deque] = defaultdict(deque)
_group_blocked_until: dict[int, float] = {}
_group_warning_until: dict[int, float] = {}
_lock = asyncio.Lock()


def _user_state(user_id: int) -> UserState:
    state = _users.get(int(user_id))
    if state is None:
        state = UserState(deque())
        _users[int(user_id)] = state
    return state


def remaining_user_limit(user_id: int) -> int:
    state = _user_state(user_id)
    return max(0, int(state.limited_until - time.monotonic() + 0.999))


def user_warning_sent(user_id: int) -> bool:
    return _user_state(user_id).warning_message_id is not None


def mark_user_warning_sent(user_id: int, message_id: int = -1) -> None:
    _user_state(user_id).warning_message_id = int(message_id)


def user_is_limited(user_id: int) -> bool:
    state = _user_state(user_id)
    if state.limited_until and time.monotonic() >= state.limited_until:
        state.limited_until = 0.0
        state.warning_message_id = None
        state.requests.clear()
        return False
    return state.limited_until > time.monotonic()


def allow_user_request(user_id: int) -> bool:
    """ثبت فقط درخواست واقعی ربات؛ رسیدن به سقف همان درخواست را مسدود می‌کند."""
    now = time.monotonic()
    state = _user_state(user_id)
    if state.limited_until > now:
        return False
    with SessionLocal() as session:
        if not get_anti_spam_enabled(session):
            return True
        max_requests = max(1, int(get_anti_spam_user_max(session)))
        time_window = max(1.0, float(get_anti_spam_user_window(session)))
    state.limited_until = 0.0
    while state.requests and now - state.requests[0] >= time_window:
        state.requests.popleft()
    # درخواست فعلی هم جزو سهمیه است. بنابراین اگر سقف ۸ باشد،
    # درخواست هشتم همان لحظه محدودیت را فعال می‌کند و اجرا نمی‌شود.
    state.requests.append(now)
    if len(state.requests) >= max_requests:
        state.limited_until = now + USER_LIMIT_DURATION
        return False
    return True


def allow_group_message(chat_id: int) -> bool:
    """سقف گروهی به‌صورت یک بازه کامل اعمال می‌شود: پس از رسیدن به سقف،
    تا پایان همان بازه هیچ پیام عادی دیگری از ربات ارسال نمی‌شود."""
    now = time.monotonic()
    with SessionLocal() as session:
        if not get_anti_spam_enabled(session):
            return True
        max_messages = max(1, int(get_anti_spam_group_max(session)))
        time_window = max(1.0, float(get_anti_spam_group_window(session)))
    cid = int(chat_id)
    blocked_until = _group_blocked_until.get(cid, 0.0)
    if blocked_until > now:
        return False
    if blocked_until:
        _group_blocked_until.pop(cid, None)
        _group_messages.pop(cid, None)
    q = _group_messages[cid]
    if not q:
        q.append(now)
        return True
    window_start = q[0]
    if now - window_start >= time_window:
        q.clear()
        q.append(now)
        return True
    # پیام شماره سقف مجاز باید ارسال شود؛ از پیام بعدی تا پایان همین بازه توقف اعمال می‌شود.
    if len(q) >= max_messages:
        _group_blocked_until[cid] = window_start + time_window
        return False
    q.append(now)
    if len(q) >= max_messages:
        _group_blocked_until[cid] = window_start + time_window
    return True


def group_remaining_seconds(chat_id: int) -> int:
    now = time.monotonic()
    cid = int(chat_id)
    blocked_until = _group_blocked_until.get(cid, 0.0)
    if blocked_until > now:
        return max(0, int(blocked_until - now + 0.999))
    return 0


def should_send_group_warning(chat_id: int) -> bool:
    now = time.monotonic()
    cid = int(chat_id)
    if _group_blocked_until.get(cid, 0.0) <= now:
        _group_warning_until.pop(cid, None)
        return True
    until = _group_warning_until.get(cid, 0.0)
    if now >= until:
        _group_warning_until[cid] = _group_blocked_until[cid]
        return True
    return False


def reset_group_state(chat_id: int) -> None:
    """Forget the in-memory quota for a group (mainly useful after a bot restart)."""
    cid = int(chat_id)
    _group_messages.pop(cid, None)
    _group_blocked_until.pop(cid, None)
    _group_warning_until.pop(cid, None)
