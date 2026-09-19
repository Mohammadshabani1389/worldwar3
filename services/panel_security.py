"""Per-message inline-panel ownership."""
from contextvars import ContextVar

_current_owner = ContextVar("panel_owner", default=None)
PANEL_OWNERS = {}

def set_panel_owner(user_id):
    return _current_owner.set(int(user_id) if user_id is not None else None)

def get_panel_owner():
    return _current_owner.get()

def register_panel(chat_id, message_id, user_id):
    if chat_id is not None and message_id is not None and user_id is not None:
        PANEL_OWNERS[(int(chat_id), int(message_id))] = int(user_id)

def check_panel(chat_id, message_id, user_id):
    owner = PANEL_OWNERS.get((int(chat_id), int(message_id)))
    if owner is None:
        return True, None
    return owner == int(user_id), owner
