import asyncio
from html import escape
import json
import re
from datetime import datetime, timedelta, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonCommands
from telegram.ext import ContextTypes
from sqlalchemy import select
from database.db import SessionLocal
from database.models import Admin, Country, BotSetting
from keyboards.main import (
    country_creation_keyboard,
    hq_keyboard,
    private_main_keyboard,
    metal_mine_keyboard,
    exchange_keyboard,
    exchange_input_keyboard,
    exchange_confirm_keyboard,
    exchange_command_keyboard,
    command_keyboard, page_back_keyboard, hq_command_keyboard, mine_command_keyboard, country_command_keyboard, country_name_confirm_keyboard, swap_country_keyboard, swap_target_keyboard, country_edit_confirm_keyboard, country_edit_waiting_keyboard, country_rename_payment_keyboard, store_command_keyboard, shield_purchase_type_keyboard, shield_purchase_list_keyboard, missile_purchase_type_keyboard, missile_purchase_list_keyboard, arsenal_command_keyboard,
)
from config import OWNER_ID
from services.admin import is_admin, is_owner, add_admin, remove_admin, get_admin_user, get_admins, get_user_by_telegram_id, get_users, ban_user, unban_user
from services.settings import phone_required_for, get_bot_shutdown_mode, get_global_loot_percent, set_global_loot_percent, get_anti_spam_enabled, get_anti_spam_user_max, get_anti_spam_user_window, get_anti_spam_group_max, get_anti_spam_group_window, get_backup_interval, get_backup_started, get_backup_execution_time, set_anti_spam_user_max, set_anti_spam_user_window, set_anti_spam_group_max, set_anti_spam_group_window, set_backup_interval, set_backup_started, set_backup_execution_time
from services.economy import get_metal_mine_config, save_metal_mine_config, get_arsenal_config, get_hq_config, get_missiles_config, save_missiles_config, get_config as get_shield_config, save_config as save_shield_config, get_shield_auto_settings
from services.panel_security import set_panel_owner
from services.social_links import get_social_settings, get_social_items, get_active_social_items, add_social_item, update_social_item, set_social_value, social_item_button_url, public_chat_target, private_invite_link, private_message_link_chat_id
from services.social_rewards import is_optional_claimed, is_optional_pending
from services.economy import get_item as get_shield_item, get_items as get_shield_items, purchase as purchase_shield, active_for_target as active_shield_for_target, remaining_text as shield_remaining_text
from enigma.database import ensure_settings as enigma_ensure_settings, get_setting as enigma_get_setting, set_setting as enigma_set_setting
from enigma.challenges import ensure_missions as enigma_ensure_missions
from keyboards.admin import (
    admin_management_keyboard,
    owner_anti_spam_panel_text, owner_anti_spam_keyboard, owner_backup_panel_text, owner_backup_keyboard,
    admin_back_keyboard,
    admin_confirm_keyboard,
    admin_multiple_confirm_keyboard,
    remove_multiple_confirm_keyboard,
    admin_search_result_keyboard,
    balance_final_keyboard,
    ban_multiple_ids_keyboard,
    ban_reason_keyboard, ban_duration_keyboard,
    user_confirm_keyboard, user_multiple_confirm_keyboard, user_search_confirm_keyboard, balance_continue_keyboard, balance_multiple_users_keyboard, resource_keyboard,
    user_action_keyboard, user_detail_back_keyboard,
    shield_add_keyboard, shield_user_confirm_keyboard,
    game_settings_user_keyboard, metal_mine_costs_keyboard, social_constraint_keyboard, social_members_constraint_keyboard, social_time_constraint_keyboard, social_add_confirm_keyboard,
)

from services.game import (
    can_upgrade_hq,
    construction_label,
    hq_instant_finish_uranium_cost,
    country_status,
    create_country,
    get_country_by_name,
    get_default_country,
    get_or_create_user,
    get_user_country_in_continent,
    get_user_countries,
    hq_info,
    normalize_country_name,
    register_user_in_country,
    metal_mine_info,
    can_build_metal_mine,
    can_upgrade_metal_mine,
    collect_metal_mine, metal_mine_instant_finish_uranium_cost,
    finalize_construction, arsenal_instant_finish_uranium_cost,
    arsenal_info,
    can_upgrade_arsenal,
    exchange_rate_text,
    get_exchange_rates,
    EXCHANGE_RATES,
    calculate_exchange,
    save_exchange_rate,
    get_missile_inventory, save_missile_inventory, add_missile_to_inventory, get_missile_count, get_missile_tech_level,
)






def _country_shield_status(session, country):
    """نمایش وضعیت سپرهای کشور: فعال با زمان باقی‌مانده، یا غیرفعال."""
    leader_id=getattr(country,'leader_user_id',None)
    country_id=getattr(country,'id',None)
    if not leader_id or not country_id:
        return {'continental':'غیرفعال','global':'غیرفعال'}
    result={'continental':'غیرفعال','global':'غیرفعال'}
    cfg=get_shield_config(session)
    active=[]
    try:
        state=__import__('services.economy',fromlist=['_state'])._state(session)
        now=__import__('time').time()
        for rec in state.values():
            if int(rec.get('country_id',0) or 0)!=int(country_id): continue
            if float(rec.get('expires_at',0) or 0)<=now: continue
            item=next((x for x in cfg.get('items',[]) if str(x.get('id'))==str(rec.get('item_id'))),None)
            typ=(item.get('type') if item else rec.get('type')) if (item or rec) else None
            if typ: active.append((item,rec,typ))
    except Exception: pass
    for item,rec,typ in active:
        text=shield_remaining_text(rec.get('expires_at'))
        if typ in result:
            result[typ]=text
    return result

def _normalize_search_value(value: str) -> str:
    return (value or "").strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))


def _normalize_phone(value: str) -> str:
    return "".join(ch for ch in _normalize_search_value(value) if ch.isdigit())


def _search_user_by_any(session, raw: str, users):
    """جستجوی واحد کاربر با آیدی، نام کاربری، شماره تلفن یا نام کشور."""
    raw = _normalize_search_value(raw)
    if not raw:
        return None

    # آیدی فقط وقتی بررسی می‌شود که ورودی کاملاً عددی باشد؛
    # بنابراین ورودی متنی هرگز به خطای «آیدی باید عدد باشد» نمی‌رسد.
    if raw.isdigit():
        target = get_user_by_telegram_id(session, int(raw))
        if target is not None and target in users:
            return target

    # نام کاربری فقط در صورتی معتبر است که با @ ارسال شده باشد.
    if raw.startswith("@"):
        username = raw[1:].strip().casefold()
        if username:
            for user in users:
                if (user.username or "").lstrip("@").casefold() == username:
                    return user

    phone = _normalize_phone(raw)
    if phone:
        for user in users:
            if _normalize_phone(user.phone_number or "") == phone:
                return user

    country_query = raw.casefold().strip()
    if country_query:
        for user in users:
            for country in get_user_countries(session, user):
                if (country.title or "").casefold().strip() == country_query:
                    return user

    return None


# پیام بن فقط برای دستورها/گزینه‌های فرمانی ارسال می‌شود؛ پیام‌های عادی چت نباید پاسخ بگیرند.
_BAN_COMMAND_TEXTS = (
    "شروع بازی", "🏁 شروع بازی", "کشور",
    "کشور", "تبادل", "💱 تبادل", "نرخ تبادل", "📊 نرخ تبادل",
    "مرکز فرماندهی", "🏛️ مرکز فرماندهی", "معدن فلز", "⛏️ معدن فلز", "زرادخانه", "🏭 زرادخانه",
    "انتخاب کشور پیشفرض", "🌍 انتخاب کشور پیشفرض",
    "تغییر کشور پیشفرض", "🔄 تغییر کشور پیشفرض",
    "انتخاب گروه پیشفرض", "🌍 انتخاب گروه پیشفرض",
    "تغییر گروه پیشفرض", "🔄 تغییر گروه پیشفرض",
    "برگشت", "🔙 برگشت", "تنظیمات بازی", "🎮 تنظیمات بازی", "تنظیمات اکانت", "🪪 تنظیمات اکانت",
    "ویرایش نام کشور", "🌍 ویرایش نام کشور", "جابجایی", "🔄 جابجایی",
    "پنل ادمین", "پنل owner",
    "پول به فلز", "💰 پول به فلز", "فلز به پول", "🔩 فلز به پول",
    "پول به سوخت", "💰 پول به سوخت", "سوخت به پول", "⛽ سوخت به پول",
    "اورانیوم به سوخت", "☢️ اورانیوم به سوخت", "☢ اورانیوم به سوخت", "اورانیوم به پول", "☢️ اورانیوم به پول", "☢ اورانیوم به پول",
)

def normalize_text(text: str) -> str:
    return (
        text.strip()
        .replace("\u200c", "")
        .replace("\u200f", "")
        .replace("\u200e", "")
        .replace(" ", "")
        .replace("‌", "")
        .replace("ي", "ی")
        .replace("ى", "ی")
        .replace("ك", "ک")
        .lower()
    )


# حذف نویسه‌های نامرئی/Variation Selector باعث می‌شود دکمه‌های شیشه‌ای و
# متن دستی، حتی بعد از بازسازی دیتابیس، دقیقاً به یک دستور برسند.
_TEXT_NOISE = "\ufe0e\ufe0f\u200b\u200c\u200d\u2060"

def command_key(text: str) -> str:
    import unicodedata
    value = normalize_text(text or "")
    for ch in _TEXT_NOISE:
        value = value.replace(ch, "")
    # Emoji/icon glyphs are presentation only; commands must work with or without them.
    value = "".join(ch for ch in value if unicodedata.category(ch) not in {"So", "Sk"})
    return value


BAN_COMMAND_NAMES = {command_key(x) for x in _BAN_COMMAND_TEXTS}

def is_text_command(text: str) -> bool:
    key = command_key(text)
    return key in TEXT_COMMAND_KEYS


def _schedule_delete_after(context, *messages, delay: float = 30.0):
    """Delete transient game info/command messages after a short delay."""
    items = [(m.chat_id, m.message_id) for m in messages if m is not None]
    if not items:
        return

    async def _delete():
        await asyncio.sleep(delay)
        for chat_id, message_id in items:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception:
                pass

    context.application.create_task(_delete())


async def _ensure_native_commands_menu(context, chat_id):
    """فعال‌سازی منوی Commands خود تلگرام بدون ساختن پیام واسط."""
    try:
        await context.bot.set_chat_menu_button(
            chat_id=int(chat_id),
            menu_button=MenuButtonCommands(),
        )
    except Exception:
        # تنظیم منوی تلگرام نباید باعث اختلال در اجرای ربات شود.
        pass


def pending_key(user_id: int) -> str:
    return f"country_name_pending_{user_id}"

TEXT_COMMAND_NAMES = {
    "تبادل", "💱تبادل", "نرختبادل", "📊نرختبادل",
    "مرکزفرماندهی", "🏛️مرکزفرماندهی", "معدنفلز", "⛏️معدنفلز", "زرادخانه", "🏭زرادخانه",
    "انتخابکشورپیشفرض", "🌍انتخابکشورپیشفرض",
    "تغییرکشورپیشفرض", "🔄تغییرکشورپیشفرض",
    "انتخابگروهپیشفرض", "🌍انتخابگروهپیشفرض",
    "تغییرگروهپیشفرض", "🔄تغییرگروهپیشفرض", "چت و کانال", "💬 چت و کانال",
    "برگشت", "🔙برگشت", "تنظیماتبازی", "⚙️تنظیماتبازی", "تنظیماتاکانت", "👤تنظیماتاکانت",
    "ویرایشنامکشور", "🌍ویرایشنامکشور", "جابجایی", "🔄جابجایی",
    "پولبهفلز", "💰پولبهفلز", "فلزبهپول", "🔩فلزبهپول",
    "پولبهسوخت", "💰پولبهسوخت", "سوختبهپول", "⛽سوختبهپول",
    "اورانیومبهسوخت", "☢️اورانیومبهسوخت", "اورانیومبهپول", "☢️اورانیومبهپول",
    "کشور", "شروعبازی", "شروع بازی", "پنلادمین", "پنل مالک", "فروشگاه", "خرید سپر", "خریدسپر", "خرید سپر جهانی", "خریدسپرجهانی", "خرید سپر قاره‌ای", "خریدسپر قاره‌ای", "🛡️ خرید سپر", "سپر جهانی", "🛡️ سپر جهانی", "سپر قاره‌ای", "🛡️ سپر قاره‌ای", "خرید موشک", "🚀 خرید موشک", "خرید موشک کروز", "خرید موشک بالستیک", "خرید موشک هایپرسونیک", "🏪فروشگاه", "موشک‌هایکروز", "موشک‌هایبالستیک", "موشک‌هایهایپرسونیک",
}

TEXT_COMMAND_KEYS = {command_key(x) for x in TEXT_COMMAND_NAMES}

def _enigma_normalize_digits(value: str) -> str:
    """Normalize Arabic/Persian digits so numeric انیگما settings are read exactly."""
    trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    return (value or "").strip().translate(trans)

def _enigma_parse_int(value: str) -> int:
    value = _enigma_normalize_digits(value)
    value = value.replace("٬", "").replace(",", "").replace(" ", "").replace("_", "")
    if not re.fullmatch(r"\d+", value):
        raise ValueError("integer required")
    return int(value, 10)

def _enigma_parse_number(value: str) -> float:
    value = _enigma_normalize_digits(value)
    value = value.replace("٫", ".").replace(",", "").replace("٬", "").replace(" ", "").replace("_", "")
    if not re.fullmatch(r"\d+(?:\.\d+)?", value):
        raise ValueError("number required")
    return float(value)

def clear_all_waiting_states(context, chat_id=None):
    # هر دستور متنی جدید باید هر انتظار قبلی را قطع کند.
    keys = (
        "economy_pending", "balance_pending", "country_edit_waiting",
        "country_edit_name", "self_country_edit", "self_country_edit_name",
        "country_edit", "pending_exchange", "exchange_rate_pending", "admin_pending", "swap_pending", "missile_pending", "missile_operational_pending", "exchange_text_pending", "exchange_text_draft", "missile_draft", "enigma_pending", "security_pending", "social_pending", "arsenal_sell_custom_pending", "arsenal_sell_pending", "shield_adjust_pending", "shield_reset_pending", "shield_add_pending", "shield_edit_pending", "shield_auto_setting_pending",
    )
    for key in keys:
        _clear_waiting_key(context, key, chat_id)



def _missile_launch_level_data(missile, level, session):
    levels = missile.get("levels") or {}
    data = levels.get(str(int(level))) or {}
    power = float(data.get("power", 0) or 0)
    cost = float(data.get("cost", 0) or 0)
    target_time = float(data.get("target_time", 0) or 0)
    loot_percent = get_global_loot_percent(session)
    if int(level) == 1:
        if power <= 0: power = float(missile.get("base_power", 0) or 0)
        if cost <= 0: cost = float(missile.get("base_cost", 0) or 0)
        if target_time <= 0: target_time = float(missile.get("base_target_time", 0) or 0)
    return power, cost, target_time, loot_percent


def _reconcile_arsenal_storage(session, country, missiles_cfg):
    """همگام‌سازی ظرفیت زرادخانه با موجودی واقعی موشک‌ها."""
    inv = get_missile_inventory(session, country.id) or {}
    known = {str(m.get("id")): m for m in (missiles_cfg.get("items", []) or []) if m.get("id") is not None}
    cleaned, total_count, total_capacity = {}, 0, 0.0
    for mid, levels in inv.items():
        m = known.get(str(mid))
        if not m:
            continue
        cap = float(m.get("base_capacity", 0) or 0)
        kept = {}
        for level, count in (levels or {}).items():
            try: count = int(count or 0)
            except Exception: count = 0
            if count <= 0: continue
            kept[str(int(level))] = count
            total_count += count
            total_capacity += cap * count
        if kept: cleaned[str(mid)] = kept
    if cleaned != inv:
        save_missile_inventory(session, country.id, cleaned)
    country.missiles = total_count
    country.arsenal_storage = total_capacity
    return cleaned, total_capacity, total_count


def _launch_target_buildings(country, hq_cfg, mine_cfg, arsenal_cfg):
    buildings=[]
    hq_level=int(getattr(country,"command_center_level",0) or 0)
    if hq_level>0:
        from services.game import hq_level_data
        d=hq_level_data(hq_level,hq_cfg) or {}
        buildings.append({"key":"command_center","name":"مرکز فرماندهی","strength":float(d.get("strength",hq_cfg.get("build_strength",0)) or 0)})
    mine_level=int(getattr(country,"metal_mine_level",0) or 0)
    if mine_level>0:
        from services.game import _metal_mine_level_data
        d=_metal_mine_level_data(mine_level,mine_cfg) or {}
        buildings.append({"key":"metal_mine","name":"معدن فلز","strength":float(d.get("strength",0) or 0)})
    arsenal_level=int(getattr(country,"arsenal_level",0) or 0)
    if arsenal_level>0:
        from services.game import _arsenal_level_data
        d=_arsenal_level_data(arsenal_level,arsenal_cfg) or {}
        buildings.append({"key":"arsenal","name":"زرادخانه","strength":float(d.get("strength",arsenal_cfg.get("build_strength",0)) or 0)})
    return buildings


def _launch_confirmation_text(missile, level, power, target_time, target, buildings, loot_percent=0.0):
    lines=["🚀 <b>تأیید شلیک</b>","",f"🚀 نام موشک: <b>{escape(str(missile.get('name','موشک')))}</b>",f"🔢 سطح موشک: <b>{int(level)}</b>",f"💥 قدرت: <b>{power:,.0f}</b>",f"⏱️ زمان رسیدن به هدف: <b>{target_time:,.0f} ثانیه</b>","",f"🎯 <b>کشور هدف: {escape(str(target.title))}</b>","🏢 <b>ساختمان‌های هدف:</b>"]
    for b in buildings:
        lines.append(f"• {b['name']} — 🛡️ استحکام: <b>{b['strength']:,.0f}</b>")
    loot_percent = max(0.0, min(100.0, float(loot_percent or 0)))
    resources=[]
    # فقط مقدار غارت احتمالی مهاجم نمایش داده می‌شود؛ اورانیوم هرگز قابل غارت نیست.
    for key,label in (("money","💰 پول"),("metal","🔩 فلز"),("fuel","⛽ سوخت")):
        if bool(getattr(target,f"infinite_{key}",False)):
            continue
        current=float(getattr(target,key,0) or 0)
        amount=current * loot_percent / 100.0
        if amount > 0:
            resources.append(f"{label}: <b>+{amount:,.2f}</b>")
    if not resources:
        resources.append("—")
    lines += ["", "💰 <b>غارت احتمالی شما:</b>", *resources]
    return "\n".join(lines)

async def group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user_tg = update.effective_user
    chat = update.effective_chat
    if message is None or user_tg is None or chat is None:
        return
    if user_tg.is_bot:
        return
    # منوی Commands متعلق به خود تلگرام است؛ برای این چت صراحتاً فعال می‌شود.
    # هیچ پیام خالی یا پیام واسطی برای فعال‌کردن آن ارسال نمی‌شود.
    await _ensure_native_commands_menu(context, user_tg.id)
    set_panel_owner(user_tg.id)
    if chat.type not in ("group", "supergroup"):
        return

    # تبلیغ اجباری فقط هنگام استفاده واقعی از دستورات/ورودی‌های ربات بررسی می‌شود؛
    # پیام‌های عادی کاربران در گروه نباید هیچ پیام خودکاری از ربات دریافت کنند.
    gate_text = (message.text or "").strip()
    gate_normalized = command_key(gate_text)
    gate_is_bot_command = (
        gate_text.startswith("/")
        or is_text_command(gate_text)
        or (
            chat.type in ("group", "supergroup")
            and (
                gate_normalized in {command_key("کشور"), command_key("شروع بازی"), command_key("شروعبازی")}
                or re.match(r"^\s*(خرید|فروش)\s+.+$", gate_text) is not None
                or re.match(r"^\s*شلیک\s+.+$", gate_text, flags=re.IGNORECASE) is not None
            )
        )
    )
    with SessionLocal() as gate_session:
        gate_admin = is_admin(gate_session, user_tg.id, OWNER_ID)
        gate_owner = is_owner(user_tg.id, OWNER_ID)
        if not (gate_admin or gate_owner) and gate_is_bot_command:
            missing = []
            for item in get_active_social_items(gate_session, "mandatory_ad"):
                target = item.get("chat_id") or public_chat_target(item.get("url")) or private_message_link_chat_id(item.get("url"))
                if not target:
                    missing.append(item); continue
                try:
                    member = await context.bot.get_chat_member(target, user_tg.id)
                    status = getattr(member, "status", "")
                    joined = status in {"member", "administrator", "creator"} or (status == "restricted" and bool(getattr(member, "is_member", False)))
                except Exception:
                    joined = False
                if not joined:
                    missing.append(item)
            if missing:
                rows = []
                for item in missing:
                    url = social_item_button_url(item.get("url"))
                    if url:
                        rows.append([InlineKeyboardButton("🚨 ورود به تبلیغ اجباری", url=url)])
                if rows:
                    await message.reply_text("🚨 <b>دسترسی محدود است</b>\n\nابتدا در همهٔ تبلیغات اجباری عضو شوید تا دسترسی ربات برای شما باز شود.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))
                return

    text = message.text or ""
    normalized = command_key(text)
    # waiting مربوط به چت دیگر نباید پیام عادی این چت را مصرف کند؛
    # اما دستورهای معتبر گروه (از جمله «شلیک» و «خرید/فروش») همیشه باید عبور کنند.
    _group_command_input = bool(
        text.strip().startswith("/")
        or is_text_command(text)
        or re.match(r"^\s*(شلیک|خرید|فروش)\s+.+$", text.strip(), flags=re.IGNORECASE)
    )
    if _has_foreign_waiting(context, message.chat_id) and text.strip() and not _group_command_input:
        return

    # دستور شلیک در گروه: «شلیک <نام عملیاتی>» و هدف باید پیام کاربر باشد که روی آن Reply شده است.
    launch_match = None
    if text.strip():
        import uuid
        launch_match = re.match(r"^\s*شلیک\s+(.+?)\s*$", text.strip(), flags=re.IGNORECASE)

    with SessionLocal() as session:
        user = get_or_create_user(session, user_tg)
        shutdown_mode = get_bot_shutdown_mode(session)
        admin_user = is_admin(session, user_tg.id, OWNER_ID)
        owner_user = is_owner(user_tg.id, OWNER_ID)
        shield_add=context.user_data.get("shield_add_pending")
        if shield_add and owner_user and _waiting_scope_matches(context, "shield_add_pending", message.chat_id):
            raw=(message.text or "").strip()
            typ=shield_add.get("type")
            # دستورهای آماده، مخصوصاً «برگشت»، نباید به‌عنوان نام سپر ثبت شوند.
            if is_text_command(raw) or raw.startswith("/"):
                if command_key(raw) in {command_key("برگشت"), command_key("🔙 برگشت")}:
                    context.user_data.pop("shield_add_pending", None); context.user_data.pop("shield_edit_pending", None); context.user_data.pop("shield_auto_setting_pending", None)
                    from keyboards.admin import shield_type_management_keyboard
                    session.commit()
                    await message.reply_text(f"🛡️ <b>{'سپرهای جهانی' if typ=='global' else 'سپرهای قاره‌ای'}</b>\n\nعملیات موردنظر را انتخاب کنید:", parse_mode="HTML", reply_markup=shield_type_management_keyboard(typ))
                    return
                context.user_data.pop("shield_add_pending", None); context.user_data.pop("shield_edit_pending", None); context.user_data.pop("shield_auto_setting_pending", None)
                shield_add = None
        if shield_add and owner_user and _waiting_scope_matches(context, "shield_add_pending", message.chat_id):
            try:
                stage=shield_add.get("stage")
                if stage=="name":
                    if not raw or len(raw)>80: raise ValueError
                    shield_add["name"]=raw; shield_add["stage"]="price"
                    await message.reply_text("☢️ <b>قیمت سپر</b>\n\nقیمت را فقط بر حسب اورانیوم ارسال کنید:",parse_mode="HTML",reply_markup=shield_add_keyboard(typ)); return
                if stage=="price":
                    value=float(_enigma_parse_number(raw))
                    if value<0: raise ValueError
                    shield_add["price"]=value; shield_add["stage"]="duration"
                    await message.reply_text("⏱ <b>مدت فعال بودن سپر</b>\n\nمدت اعتبار را بر حسب ساعت ارسال کنید:",parse_mode="HTML",reply_markup=shield_add_keyboard(typ)); return
                if stage=="duration":
                    value=int(float(_enigma_parse_number(raw)))
                    if value<=0: raise ValueError
                    shield_add["duration_hours"] = value; shield_add["stage"] = "cooldown"
                    await message.reply_text(f"🛡️ <b>پیش‌نمایش سپر</b>\n\n📌 نوع: <b>{'جهانی' if typ=='global' else 'قاره‌ای'}</b>\n🏷 نام: <b>{escape(str(shield_add.get('name','سپر')))}</b>\n☢️ قیمت: <b>{float(shield_add.get('price',0)):,.0f} اورانیوم</b>\n⏱ مدت: <b>{value} ثانیه</b>\n\nبرای ثبت نهایی تأیید کنید.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ تأیید و ذخیره نهایی", callback_data="owner:shield_confirm_add")],[InlineKeyboardButton("✏️ ویرایش", callback_data=f"owner:shield_add:{typ}")],[InlineKeyboardButton("🔙 برگشت", callback_data=f"owner:shield_type:{typ}")]])); return
            except Exception:
                await message.reply_text("❌ مقدار نامعتبر است. لطفاً مقدار صحیح ارسال کنید.",reply_markup=shield_add_keyboard(typ)); return

        if not owner_user and (shutdown_mode == "all" or (shutdown_mode == "admins" and admin_user) or (shutdown_mode == "users" and not admin_user)):
            session.commit(); await message.reply_text("⏸️ ربات موقتاً خاموش است."); return
        # خرید/فروش موشک با نام عملیاتی داخل گروه
        # تشخیص خرید/فروش: اگر کل عبارت بعد از دستور دقیقاً نام عملیاتی باشد، عددِ داخل نام را تعداد حساب نکن.
        # فقط وقتی دو فاصله بین نام و عدد وجود داشته باشد، یا نام کامل پیدا نشود، عدد انتهایی تعداد است.
        trade_match = re.match(r"^\s*(خرید|فروش)\s+(.+?)\s*$", text.strip()) if text.strip() else None
        if trade_match:
            action_trade, trade_tail = trade_match.groups()
            wanted_trade, qty_raw = trade_tail.strip(), None
            cfg_preview = get_missiles_config(session)
            exact_names = {str(n).strip().casefold() for m in cfg_preview.get("items", []) if m.get("active") for n in (m.get("operational_names") or [])}
            # دو فاصله عمداً جداکننده تعداد است.
            m_double = re.match(r"^(.+?)\s{2,}(\d+)\s*$", trade_tail)
            if m_double:
                wanted_trade, qty_raw = m_double.groups()
            elif wanted_trade.casefold() not in exact_names:
                m_single = re.match(r"^(.+?)\s+(\d+)\s*$", trade_tail)
                if m_single:
                    candidate, number = m_single.groups()
                    if candidate.strip().casefold() in exact_names:
                        wanted_trade, qty_raw = candidate, number
            qty=max(1,int(qty_raw or 1))
            async def trade_reply(text, **kwargs):
                reply = await message.reply_text(text, **kwargs)
                _schedule_delete_after(context, message, reply, delay=30)
                return reply
            attacker=get_user_country_in_continent(session,user,chat.id)
            if attacker is None:
                await trade_reply("❌ کشور شما در این گروه پیدا نشد."); return
            cfg=get_missiles_config(session)
            missile=None
            for m in cfg.get("items",[]):
                if not m.get("active"): continue
                if any(str(n).strip().casefold()==wanted_trade.strip().casefold() for n in (m.get("operational_names") or [])):
                    missile=m; break
            if missile is None:
                await trade_reply("❌ این نام عملیاتی موشک وجود ندارد یا موشک غیرفعال است."); return
            mid=str(missile.get("id")); level=max(1,min(get_missile_tech_level(session,attacker.id,mid),int(missile.get("max_level",100) or 100)))
            level_data=(missile.get("levels") or {}).get(str(level)) or {}
            price=float(level_data.get("cost",0) or 0) or (float(missile.get("base_cost",0) or 0) if level==1 else 0)
            cap=float(missile.get("base_capacity",0) or 0)
            inv=get_missile_inventory(session,attacker.id)
            if action_trade=="خرید":
                if int(getattr(attacker,"arsenal_level",0) or 0)<=0:
                    await trade_reply("❌ زرادخانه کشور ساخته نشده است."); return
                acfg=get_arsenal_config(session); maxcap=float((acfg.get("levels",{}).get(int(attacker.arsenal_level)) or {}).get("storage_capacity",acfg.get("build_storage_capacity",0)) or 0)
                _,used,_=_reconcile_arsenal_storage(session,attacker,cfg)
                free=max(0.0,maxcap-used)
                # تعداد واقعی خرید = کمترین مقدارِ درخواست، ظرفیت آزاد و موجودی پول.
                # بنابراین اگر کاربر ۳ عدد بخواهد ولی فقط ۲ جای خالی باشد، دقیقاً ۲ عدد
                # خریداری و فقط هزینه همان ۲ عدد کسر می‌شود.
                capacity_possible = qty if cap <= 0 else min(qty, int(free // cap))
                possible = max(0, int(capacity_possible))
                if possible <= 0:
                    await trade_reply(f"❌ ظرفیت زرادخانه برای {qty} {missile.get('name','موشک')} کافی نیست."); return
                total_cost = price * possible
                if not getattr(attacker,"infinite_money",False) and float(attacker.money) < total_cost:
                    await trade_reply(f"❌ پول کافی نیست. هزینه خرید {possible} موشک: {total_cost:,.0f}"); return
                if not getattr(attacker,"infinite_money",False):
                    attacker.money = float(attacker.money or 0) - total_cost
                for _ in range(possible):
                    add_missile_to_inventory(session,attacker.id,mid,level,1)
                attacker.missiles=int(getattr(attacker,"missiles",0) or 0)+possible
                attacker.arsenal_storage=used+cap*possible
                session.commit()
                if possible<qty:
                    reply = await message.reply_text(f"⚠️ ظرفیت زرادخانه برای {qty} عدد کافی نبود؛ {possible} عدد خریداری و اضافه شد.\n💰 مبلغ کسرشده: <b>{total_cost:,.0f}</b>",parse_mode="HTML")
                else:
                    reply = await message.reply_text(f"✅ {possible} عدد {missile.get('name','موشک')} خریداری و به زرادخانه اضافه شد.\n💰 مبلغ: <b>{total_cost:,.0f}</b>",parse_mode="HTML")
                _schedule_delete_after(context, message, reply, delay=30)
                return
            # فروش: موجودی واقعی را از بالاترین سطح‌ها کم می‌کنیم.
            levels_inv=inv.get(mid,{}) or {}; available_total=sum(int(v or 0) for v in levels_inv.values())
            sell_n=min(qty,available_total)
            if sell_n<=0:
                await trade_reply(f"❌ هیچ {missile.get('name','موشک')} در زرادخانه ندارید."); return
            remaining=sell_n
            for lv in sorted((int(k) for k in levels_inv.keys()), reverse=True):
                take=min(remaining,int(levels_inv.get(str(lv),0) or 0));
                if take: add_missile_to_inventory(session,attacker.id,mid,lv,-take); remaining-=take
                if remaining<=0: break
            refund=price*sell_n*0.5
            attacker.money=float(attacker.money)+refund
            attacker.missiles=max(0,int(getattr(attacker,"missiles",0) or 0)-sell_n)
            _,used,_=_reconcile_arsenal_storage(session,attacker,cfg); attacker.arsenal_storage=used
            session.commit()
            if sell_n<qty:
                reply = await message.reply_text(f"⚠️ تعداد {qty} عدد موجود نبود؛ {sell_n} عدد فروخته شد.\n💰 مبلغ دریافتی: <b>{refund:,.0f}</b>",parse_mode="HTML")
            else:
                reply = await message.reply_text(f"✅ {sell_n} عدد {missile.get('name','موشک')} فروخته شد.\n💰 مبلغ دریافتی: <b>{refund:,.0f}</b>",parse_mode="HTML")
            _schedule_delete_after(context, message, reply, delay=30)
            return

        if launch_match:
            if not message.reply_to_message or not message.reply_to_message.from_user or message.reply_to_message.from_user.is_bot:
                session.commit()
                await message.reply_text("🎯 برای شلیک، روی پیام شخص هدف ریپلای کنید و سپس «شلیک نام‌عملیاتی» را ارسال کنید.")
                return
            target_user_id=int(message.reply_to_message.from_user.id)
            if target_user_id == int(user_tg.id):
                session.commit(); await message.reply_text("❌ نمی‌توانید به کشور خودتان شلیک کنید."); return
            attacker=get_user_country_in_continent(session,user,chat.id)
            target=session.scalar(select(Country).where(Country.chat_id==chat.id, Country.leader_user_id==target_user_id))
            if attacker is None or target is None:
                session.commit(); await message.reply_text("❌ کشور مهاجم یا کشور هدف پیدا نشد."); return
            wanted=launch_match.group(1).strip()
            missiles_cfg=get_missiles_config(session)
            missile=None
            op=wanted.casefold()
            for candidate in missiles_cfg.get("items",[]):
                if not candidate.get("active"): continue
                if any(str(n).strip().casefold()==op for n in (candidate.get("operational_names") or [])):
                    missile=candidate; break
            if missile is None:
                session.commit(); await message.reply_text("❌ نام عملیاتی موشک پیدا نشد یا موشک غیرفعال است."); return
            inv=get_missile_inventory(session,attacker.id)
            levels=inv.get(str(missile.get("id")),{}) or {}
            available=[int(k) for k,v in levels.items() if int(v or 0)>0]
            if not available:
                session.commit(); await message.reply_text("❌ این موشک در زرادخانه شما موجود نیست."); return
            level=max(available)
            power,cost,target_time,loot_percent=_missile_launch_level_data(missile,level,session)
            hq_cfg=get_hq_config(session); mine_cfg=get_metal_mine_config(session); arsenal_cfg=get_arsenal_config(session)
            buildings=_launch_target_buildings(target,hq_cfg,mine_cfg,arsenal_cfg)
            shield=active_shield_for_target(session, int(target.leader_user_id), getattr(attacker,"continent_name",None), getattr(target,"continent_name",None), int(target.id))
            if shield:
                blocked_msg=await message.reply_text(f"🛡️ <b>سپر شخص فعال است.</b>\n\n⏳ زمان باقی‌مانده: <b>{shield_remaining_text(shield.get('expires_at'))}</b>\n❌ امکان شلیک به این شخص وجود ندارد.",parse_mode="HTML")
                _schedule_delete_after(context, blocked_msg, delay=30)
                session.commit(); return
            if not buildings:
                session.commit(); await message.reply_text("❌ شخص هدف هیچ ساختمانی ندارد."); return
            if power<=0:
                session.commit(); await message.reply_text("❌ قدرت این سطح موشک تنظیم نشده است."); return
            # هر درخواست شلیک شناسه مستقل دارد تا تأیید یک موشک، درخواست موشک دیگری را جابه‌جا نکند.
            launch_token = uuid.uuid4().hex[:12]
            pending_all = context.user_data.setdefault("missile_launch_pending", {})
            pending_all[launch_token] = {"attacker_country_id":int(attacker.id),"target_country_id":int(target.id),"missile_id":str(missile.get("id")),"level":level,"power":power,"target_time":target_time,"loot_percent":loot_percent,"chat_id":int(chat.id),"launch_message_id":int(message.message_id)}
            session.commit()
            markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ تأیید شلیک",callback_data=f"missile_launch_confirm:{launch_token}")],[InlineKeyboardButton("❌ لغو",callback_data=f"missile_launch_cancel:{launch_token}")]])
            confirmation_message = await message.reply_text(_launch_confirmation_text(missile,level,power,target_time,target,buildings,loot_percent),parse_mode="HTML",reply_markup=markup)
            pending_all[launch_token]["confirmation_message_id"] = int(confirmation_message.message_id)
            return

        # نام قاره همیشه برابر عنوان فعلی گروه باشد و نام رهبر با نام تلگرام صاحب کشور همگام شود.
        for c in session.scalars(select(Country).where(Country.chat_id == chat.id)).all():
            c.continent_name = chat.title or "بدون نام"
            if c.leader_user_id == user_tg.id:
                c.leader_name = user_tg.full_name or user_tg.first_name or c.leader_name
        # منوی Slash را بر اساس نقش فعلی همین کاربر تازه‌سازی کن تا /admin و /owner
        # هیچ‌وقت برای کاربر عادی باقی نمانند.
        from services.command_scopes import set_user_command_scope
        try:
            await set_user_command_scope(
                context.bot,
                user.telegram_id,
                owner=is_owner(user.telegram_id, OWNER_ID),
                admin=is_admin(session, user.telegram_id, OWNER_ID),
            )
        except Exception:
            # تغییر scope تلگرام نباید مانع اجرای دستورات متنی بازی شود.
            pass
        group_allowed = {command_key(x) for x in ("کشور", "شروعبازی", "شروع بازی")}
        pending_country = context.user_data.get(pending_key(user_tg.id)) is True
        if pending_country and not normalized.startswith("/") and normalized not in group_allowed:
            # هر دستور خصوصی که وسط دریافت نام کشور بیاید، انتظار نام را لغو می‌کند؛ اما در گروه اجرا نمی‌شود.
            private_only_tokens = {command_key(x) for x in ("معدنفلز", "تبادل", "نرختبادل", "مرکزفرماندهی", "انتخابکشورپیشفرض", "تغییرکشورپیشفرض", "جابجایی", "ویرایشنامکشور", "برگشت")}
            if normalized in private_only_tokens:
                context.user_data.pop(pending_key(user_tg.id), None)
                session.commit()
                return
        private_command_tokens = {command_key(x) for x in (
            "معدن فلز", "⛏️ معدن فلز", "زرادخانه", "🏭 زرادخانه", "فروشگاه", "🏪 فروشگاه", "خرید سپر", "🛡️ خرید سپر", "خرید سپر جهانی", "🛡️ خرید سپر جهانی", "خرید سپر قاره‌ای", "🛡️ خرید سپر قاره‌ای", "سپر جهانی", "🛡️ سپر جهانی", "سپر قاره‌ای", "🛡️ سپر قاره‌ای", "موشک‌های کروز", "موشک‌های بالستیک", "موشک‌های هایپرسونیک", "کشور", "تبادل", "💱 تبادل", "نرخ تبادل", "📊 نرخ تبادل",
            "مرکز فرماندهی", "🏛️ مرکز فرماندهی", "انتخاب کشور پیشفرض", "🌍 انتخاب کشور پیشفرض",
            "تغییر کشور پیشفرض", "🔄 تغییر کشور پیشفرض", "انتخاب گروه پیشفرض", "🌍 انتخاب گروه پیشفرض",
            "تغییر گروه پیشفرض", "🔄 تغییر گروه پیشفرض", "چت و کانال", "💬 چت و کانال", "برگشت", "🔙 برگشت", "تنظیمات بازی", "🎮 تنظیمات بازی", "تنظیمات اکانت", "🪪 تنظیمات اکانت",
            "ویرایش نام کشور", "🌍 ویرایش نام کشور", "جابجایی", "🔄 جابجایی",
            "پول به فلز", "💰 پول به فلز", "فلز به پول", "🔩 فلز به پول",
            "پول به سوخت", "💰 پول به سوخت", "سوخت به پول", "⛽ سوخت به پول",
            "اورانیوم به سوخت", "☢️ اورانیوم به سوخت", "☢ اورانیوم به سوخت", "اورانیوم به پول", "☢️ اورانیوم به پول", "☢ اورانیوم به پول",
            "کشور", "شروع بازی", "🏁 شروع بازی",
            "خرید موشک کروز", "🚀 خرید موشک کروز",
            "خرید موشک بالستیک", "🚀 خرید موشک بالستیک",
            "خرید موشک هایپرسونیک", "⚡ خرید موشک هایپرسونیک",
        )}
        # در گروه فقط انتظارهایی که صراحتاً در همین گروه ایجاد شده‌اند معتبرند.
        # انتظارهای PV هرگز نباید متن گروه را مصرف کنند.
        _group_waiting_keys = {
            pending_key(user_tg.id), "admin_pending", "balance_pending", "pending_exchange",
            "economy_pending", "country_edit_waiting", "country_edit", "self_country_edit",
            "country_name_pending", "missile_pending", "missile_operational_pending",
            "admin_message_pending", "security_pending", "social_pending",
            "admin_leadership_pending", "admin_leadership_bulk_pending",
            "arsenal_sell_custom_pending", "shield_adjust_pending", "shield_reset_pending", "shield_add_pending", "shield_edit_pending",
            "shield_auto_setting_pending", "exchange_text_pending", "exchange_rate_pending",
            "enigma_pending", "admin_panel", "store_nav", "swap_pending", "arsenal_sell_pending",
        }
        waiting_state = any(
            context.user_data.get(k) is not None
            and context.user_data.get(_waiting_scope_key(k)) is not None
            and int(context.user_data.get(_waiting_scope_key(k))) == int(message.chat_id)
            for k in _group_waiting_keys
        )
        if normalized not in group_allowed and normalized not in private_command_tokens and not waiting_state:
            session.commit()
            return
        # سیستم ارسال پیام مدیریتی
        mp = context.user_data.get("admin_message_pending") or {}
        if mp and (admin_user or owner_user):
            if mp.get("kind") == "private" and mp.get("step") in (None, "recipient"):
                raw=(message.text or "").strip()
                target=None
                # ID
                if raw.isdigit(): target=get_user_by_telegram_id(session,int(raw))
                # نام کاربری
                if target is None:
                    uname=raw.lstrip("@").casefold()
                    target=next((u for u in get_users(session) if (u.username or "").casefold()==uname),None)
                # phone
                if target is None:
                    target=next((u for u in get_users(session) if (u.phone_number or "").replace(" ","")==raw.replace(" ","")),None)
                # country name
                if target is None:
                    c=session.scalar(select(Country).where(Country.title==raw))
                    if c: target=get_user_by_telegram_id(session,c.leader_user_id)
                if target is None:
                    await message.reply_text("❌ کاربر پیدا نشد. آیدی، یوزرنیم، شماره تلفن یا نام کشور معتبر ارسال کنید."); return
                ids=mp.setdefault("recipients",[])
                if int(target.telegram_id) not in ids: ids.append(int(target.telegram_id))
                mp["step"]="recipient"; context.user_data["admin_message_pending"]=mp
                context.user_data[_waiting_scope_key("admin_message_pending")] = int(message.chat_id)
                from keyboards.admin import message_private_continue_keyboard
                countries=get_user_countries(session,target); default_country=get_default_country(session,target)
                role="👑 مالک" if is_owner(target.telegram_id,OWNER_ID) else ("🛡 ادمین" if is_admin(session,target.telegram_id,OWNER_ID) else "👤 کاربر عادی")
                profile=("🔎 <b>کاربر پیدا شد</b>\n\n"
                    f"👤 نام: <b>{escape(target.first_name or target.username or 'بدون نام')}</b>\n"
                    f"🆔 آیدی: <code>{target.telegram_id}</code>\n"
                    f"🔤 نام کاربری: {escape('@'+target.username if target.username else 'ثبت نشده')}\n"
                    f"📱 شماره: {escape(target.phone_number or 'ثبت نشده')}\n"
                    f"🎭 نقش: {role}\n"
                    f"🌍 کشور پیش‌فرض: {escape(default_country.title) if default_country else 'ثبت نشده'}\n"
                    f"🌎 تعداد کشورها: <b>{len(countries)}</b>\n\n"
                    "این کاربر به گیرندگان اضافه شد. برای ادامه، گزینه موردنظر را انتخاب کنید.")
                await message.reply_text(profile,parse_mode="HTML",reply_markup=message_private_continue_keyboard()); return
            if mp.get("step") == "text":
                # هر نوع پیام تلگرام قابل ارسال است: متن، عکس، ویدئو، فایل، صدا، استیکر و...
                content_type = "text" if (message.text or "").strip() else ("photo" if message.photo else "video" if message.video else "document" if message.document else "audio" if message.audio else "voice" if message.voice else "sticker" if message.sticker else "animation" if message.animation else "other")
                if content_type == "text" and not (message.text or "").strip():
                    await message.reply_text("❌ پیام خالی قابل ارسال نیست."); return
                mp["text"]=(message.text or message.caption or "").strip()
                mp["source_chat_id"]=int(message.chat_id)
                mp["source_message_id"]=int(message.message_id)
                mp["content_type"]=content_type
                media = (message.photo[-1] if message.photo else message.video or message.document or message.audio or message.voice or message.sticker or message.animation)
                mp["file_id"] = getattr(media, "file_id", None)
                context.user_data["admin_message_pending"]=mp
                context.user_data[_waiting_scope_key("admin_message_pending")] = int(message.chat_id)
                from keyboards.admin import message_confirm_keyboard
                recipients=mp.get("recipients",[])
                target_desc = str(mp.get("target","all")) if mp.get("kind")=="public" else ", ".join(str(x) for x in recipients)
                preview = escape(mp["text"]) if mp["text"] else f"📎 پیام از نوع <b>{content_type}</b>"
                await message.reply_text(f"📨 <b>پیش‌نمایش پیام</b>\n\n{preview}\n\n📎 نوع محتوا: <b>{content_type}</b>\n👥 گیرندگان: <b>{escape(target_desc)}</b>\n\nارسال شود؟",parse_mode="HTML",reply_markup=message_confirm_keyboard()); return

        if user.is_banned and normalized in BAN_COMMAND_NAMES:
            session.commit()
            await message.reply_text(ban_status_text(user), parse_mode="HTML")
            return

        # پیام‌های عادی گروه نباید به خاطر ثبت نشدن شماره پاسخ بگیرند؛ فقط دستورات گیت شماره را فعال می‌کنند.
        is_bot_command = normalized in BAN_COMMAND_NAMES or normalized.startswith("/")
        if is_bot_command and phone_required_for(session, is_admin_user=is_admin(session, user_tg.id, OWNER_ID), is_owner_user=is_owner(user_tg.id, OWNER_ID)) and not user.phone_number:
            session.commit()
            try:
                bot_username = (await context.bot.get_me()).username
            except Exception:
                bot_username = None
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("🤖 ورود به ربات", url=f"https://t.me/{bot_username}")]]) if bot_username else None
            await message.reply_text("📱 برای ادامه بازی ابتدا شماره تلفن خودتان را در پیوی ربات ثبت کنید.", reply_markup=markup)
            return

        if normalized == "کشور":
            own_country = get_user_country_in_continent(session, user, chat.id)
            if own_country is None:
                session.commit()
                await message.reply_text("❌ شما هنوز در این قاره کشوری ندارید. ابتدا «شروع بازی» را اجرا کنید.")
                return
            session.commit()
            info_msg = await message.reply_text(country_status(own_country, get_metal_mine_config(session), __import__("services.economy",fromlist=["get_arsenal_config"]).get_arsenal_config(session), _country_shield_status(session, own_country)), parse_mode="HTML")
            _schedule_delete_after(context, message, info_msg)
            return

        if normalized in {command_key("شروع بازی"), command_key("🏁 شروع بازی")}:
            # هر شخص حداکثر یک کشور در هر قاره دارد.
            own_country = get_user_country_in_continent(session, user, chat.id)
            if own_country is not None:
                session.commit()
                info_msg = await message.reply_text(
                    "🌍 <b>کشور شما در این قاره</b>\n\n" + country_status(own_country, get_metal_mine_config(session), __import__("services.economy",fromlist=["get_arsenal_config"]).get_arsenal_config(session), _country_shield_status(session, own_country)),
                    parse_mode="HTML",
                )
                _schedule_delete_after(context, message, info_msg)
                return

            context.user_data[pending_key(user_tg.id)] = True
            context.user_data[_waiting_scope_key(pending_key(user_tg.id))] = int(message.chat_id)
            context.user_data[f"country_creation_start_{user_tg.id}"] = message.message_id
            session.commit()
            prompt_msg = await message.reply_text(
                "🌍 <b>قاره: " + (chat.title or "بدون نام") + "</b>\n\n"
                "این اولین ورود شما به این قاره است.\n"
                "برای انتخاب نام کشور، حتماً روی همین پیام ربات ریپلای بزنید و نام کشور را ارسال کنید.\n\n"
                "👑 نام رهبر کشور = نام شما\n"
                "⚠️ نام کشور باید در کل بازی یکتا باشد.",
                parse_mode="HTML",
                reply_markup=country_creation_keyboard(),
            )
            context.user_data[f"country_creation_prompt_{user_tg.id}"] = prompt_msg.message_id
            return

        if context.user_data.get(pending_key(user_tg.id)) is True:
            prompt_id = context.user_data.get(f"country_creation_prompt_{user_tg.id}")
            reply = message.reply_to_message
            if not reply or reply.message_id != prompt_id or not reply.from_user or not reply.from_user.is_bot:
                # نام کشور فقط در پاسخ مستقیم به پیام ربات پذیرفته می‌شود.
                return
            if normalized.startswith("/") or not text.strip():
                return

            country_name = normalize_country_name(text)
            if len(country_name) < 2 or len(country_name) > 40:
                await message.reply_text("❌ نام کشور باید بین ۲ تا ۴۰ کاراکتر باشد.")
                return

            if get_country_by_name(session, country_name) is not None:
                session.commit()
                await message.reply_text("❌ این نام کشور قبلاً انتخاب شده است.\nلطفاً نام دیگری انتخاب کنید.")
                return

            context.user_data[pending_key(user_tg.id)] = False
            context.user_data[f"country_name_value_{user_tg.id}"] = country_name
            context.user_data[f"country_creation_name_message_{user_tg.id}"] = message.message_id
            session.commit()
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تأیید", callback_data="country_name_confirm")],
                [InlineKeyboardButton("✏️ تعویض اسم", callback_data="country_name_change")],
                [InlineKeyboardButton("🔙 برگشت", callback_data="country_name_cancel")],
            ])
            prompt_id = context.user_data.get(f"country_creation_prompt_{user_tg.id}")
            try:
                await context.bot.edit_message_text(
                    chat_id=chat.id, message_id=int(prompt_id),
                    text=f"🌍 نام کشور انتخابی: <b>{country_name}</b>\n\nآیا تأیید می‌کنید؟",
                    parse_mode="HTML", reply_markup=markup
                )
            except Exception:
                await message.reply_text(f"🌍 نام کشور انتخابی: <b>{country_name}</b>\n\nآیا تأیید می‌کنید؟", parse_mode="HTML", reply_markup=markup)


from services.economy import reset_purchase_limitations as reset_shield_purchase_limitations, adjust_active_shield_time

_WAITING_SCOPE_KEYS = {'shield_add_pending', 'shield_edit_pending', 'shield_auto_setting_pending', 'social_pending', 'missile_operational_pending', 'balance_pending', 'exchange_text_pending', 'user_admin_origin', 'self_country_edit', 'arsenal_sell_custom_pending', 'admin_message_pending', 'balance_selected_country', 'user_detail_back', 'store_nav', 'self_country_edit_name', 'missile_pending', 'admin_leadership_bulk_pending', 'exchange_rate_pending', 'arsenal_sell_pending', 'leadership_operation', 'country_edit_waiting', 'global_loot_percent_pending', 'missile_draft', 'balance_selected_user', 'economy_pending', 'security_pending', 'country_edit', 'owner_economy_confirm', 'admin_pending', 'enigma_pending', 'social_delete_pending', 'leadership_back_callback', 'swap_pending', 'admin_leadership_pending', 'shield_adjust_pending', 'shield_reset_pending', 'country_edit_name', 'pending_exchange', 'admin_panel'}


def _waiting_scope_key(key):
    return f"__waiting_scope__{key}"


def _waiting_scope_matches(context, key, chat_id):
    scope = context.user_data.get(_waiting_scope_key(key))
    return scope is None or int(scope) == int(chat_id)


def _has_foreign_waiting(context, chat_id):
    for key in _WAITING_SCOPE_KEYS:
        if context.user_data.get(key) is not None and not _waiting_scope_matches(context, key, chat_id):
            return True
    return False


def _clear_waiting_key(context, key, chat_id=None):
    if chat_id is None or _waiting_scope_matches(context, key, chat_id):
        context.user_data.pop(key, None)
        context.user_data.pop(_waiting_scope_key(key), None)


def _clear_social_waiting(context, chat_id=None):
    for key in ("social_pending", "social_delete_pending"):
        _clear_waiting_key(context, key, chat_id)


def _social_add_preview_text(pending, draft):
    typ = {"mandatory_ad":"🚨 تبلیغ اجباری", "optional_ad":"🎁 تبلیغ اختیاری", "chat":"💬 چت بازی", "channel":"📣 کانال بازی", "panel":"🧩 پنل بازی"}.get(pending.get("field"), "🔗 مورد")
    lines = ["📋 <b>مشخصات نهایی ثبت</b>", "", f"📌 نوع: <b>{typ}</b>", f"🔗 لینک: <code>{escape(str(draft.get('link','')))}</code>"]
    if pending.get("field") == "optional_ad":
        lines.append(f"☢️ پاداش: <b>{float(draft.get('reward',0) or 0):,.0f}</b> اورانیوم")
        lines.append(f"⏳ زمان دریافت پاداش: <b>{int(pending.get('reward_delay_minutes',60) or 60)} دقیقه</b>")
    if pending.get("max_members"):
        lines.append(f"👥 محدودیت اعضا: <b>{int(pending['max_members']):,}</b>")
    else:
        lines.append("👥 محدودیت اعضا: <b>بدون محدودیت</b>")
    if pending.get("duration_minutes"):
        lines.append(f"⏱️ محدودیت زمانی: <b>{int(pending['duration_minutes'])} دقیقه</b>")
    else:
        lines.append("⏱️ محدودیت زمانی: <b>بدون محدودیت</b>")
    lines += ["", "اطلاعات بالا را بررسی کنید:", "با «تأیید و ثبت» مورد ذخیره می‌شود."]
    return "\n".join(lines)

async def private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user_tg = update.effective_user

    if message is None or user_tg is None:
        return
    if user_tg.is_bot:
        return
    set_panel_owner(user_tg.id)

    # اگر کاربر در میانهٔ یک waiting تبلیغ/لینک، یک دستور یا دکمهٔ منویی
    # جدید بفرستد، waiting قبلی دیگر نباید پیام جدید را مصرف کند.
    incoming_text = (message.text or "").strip()
    if incoming_text and (is_text_command(incoming_text) or incoming_text.startswith("/")):
        _clear_social_waiting(context, message.chat_id)

    # عضویت در تبلیغات اجباری روی تمام پیام‌های خصوصی اعمال می‌شود.
    with SessionLocal() as gate_session:
        gate_admin = is_admin(gate_session, user_tg.id, OWNER_ID)
        gate_owner = is_owner(user_tg.id, OWNER_ID)
        mandatory = [x for x in get_social_items(gate_session, "mandatory_ad") if str(x.get("url") or "").strip()] if not (gate_admin or gate_owner) else []
        missing=[]
        for item in mandatory:
            target=item.get("chat_id") or public_chat_target(item.get("url")) or private_message_link_chat_id(item.get("url")); ok=False
            if target:
                try:
                    member=await context.bot.get_chat_member(target, user_tg.id)
                    status=getattr(member,"status","")
                    ok=status in {"member","administrator","creator"} or (status == "restricted" and bool(getattr(member,"is_member",False)))
                except Exception: ok=False
            if not ok: missing.append(item)
        if missing:
            rows=[]
            for item in missing:
                url=social_item_button_url(item.get("url"))
                if url: rows.append([InlineKeyboardButton("🚨 ورود به تبلیغ اجباری",url=url)])
            rows.append([InlineKeyboardButton("🔄 بررسی عضویت",callback_data=f"social:mandatory_check:{int(user_tg.id)}")])
            await message.reply_text("🚨 <b>عضویت در تبلیغات اجباری</b>\n\nبرای استفاده از ربات ابتدا در همه تبلیغات اجباری عضو شوید و سپس بررسی عضویت را بزنید.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(rows))
            return

    normalized = command_key(message.text or "")

    with SessionLocal() as session:
        # اگر کاربر هنگام waiting تجربه رهبری یک دستور واقعی بفرستد، waiting باید همان لحظه لغو شود
        # تا دستور جدید عادی پردازش شود؛ اما عدد 0/سایر اعداد باید حتماً به waiting برسند.
        _lead_pending = context.user_data.get("admin_leadership_pending")
        _lead_bulk_pending = context.user_data.get("admin_leadership_bulk_pending")
        if (is_text_command(message.text) or (message.text or "").startswith("/")) and (_lead_pending or _lead_bulk_pending):
            context.user_data.pop("admin_leadership_pending", None)
            context.user_data.pop("admin_leadership_bulk_pending", None)
            context.user_data.pop(_waiting_scope_key("admin_leadership_pending"), None)
            context.user_data.pop(_waiting_scope_key("admin_leadership_bulk_pending"), None)
            _lead_pending = None
            _lead_bulk_pending = None

        # waiting یک چت دیگر نباید پیام این چت را مصرف کند؛ اگر همین چت waiting تجربه رهبری دارد،
        # ورودی عددی آن باید قبل از سایر waitingها پردازش شود.
        if _has_foreign_waiting(context, message.chat_id) and not (
            _lead_pending and _waiting_scope_matches(context, "admin_leadership_pending", message.chat_id)
        ) and (message.text or "").strip() and not is_text_command(message.text) and not (message.text or "").startswith("/"):
            return

        # ورودی عددی تجربه رهبری: فقط پیش‌نمایش ساخته می‌شود و ثبت نهایی بعد از تأیید انجام می‌گیرد.
        if _lead_pending and _waiting_scope_matches(context, "admin_leadership_pending", message.chat_id) and (message.text or "").strip() and (is_owner(user_tg.id, OWNER_ID) or is_admin(session, user_tg.id, OWNER_ID)):
            raw = _enigma_normalize_digits((message.text or "").strip()).replace(",", "").replace("٬", "").replace("٫", ".").replace(" ", "").replace("_", "")
            try:
                value = float(raw)
                if value < 0:
                    raise ValueError
            except Exception:
                await message.reply_text("❌ مقدار معتبر نیست. یک عدد مثبت ارسال کنید.")
                return
            target_id = int(_lead_pending["user_id"]); country_id = int(_lead_pending["country_id"])
            country = session.get(Country, country_id)
            if country is None or int(country.leader_user_id or 0) != target_id:
                context.user_data.pop("admin_leadership_pending", None)
                await message.reply_text("❌ کشور انتخاب‌شده دیگر متعلق به این کاربر نیست.")
                return
            old = float(country.leadership_experience or 0)
            delta = value if _lead_pending.get("mode") == "add" else -value
            new_value = max(0.0, old + delta)
            context.user_data["admin_leadership_confirm"] = {"user_id": target_id, "country_id": country_id, "mode": _lead_pending.get("mode"), "old": old, "delta": delta, "new": new_value}
            context.user_data.pop("admin_leadership_pending", None)
            label = "افزودن" if delta >= 0 else "کم کردن"
            await message.reply_text(
                f"👑 <b>تأیید تغییر تجربه رهبری</b>\n\n"
                f"👤 کاربر: <b>{escape((get_user_by_telegram_id(session, target_id).first_name if get_user_by_telegram_id(session, target_id) else None) or str(target_id))}</b>\n"
                f"🌍 کشور: <b>{escape(country.title)}</b>\n"
                f"🎖 مقدار قبلی: <b>{old:,.0f}</b>\n"
                f"📌 {label}: <b>{value:,.0f}</b>\n"
                f"🎖 مقدار جدید: <b>{new_value:,.0f}</b>\n\n"
                "آیا این تغییر را تأیید می‌کنید؟",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ تأیید", callback_data="admin:leadership_confirm")],
                    [InlineKeyboardButton("✏️ ویرایش مقدار", callback_data=f"admin:user_leadership_country:{target_id}:{country_id}")],
                    [InlineKeyboardButton("🔙 برگشت", callback_data=f"admin:user_leadership:{target_id}")],
                ])
            )
            return

        user = get_or_create_user(session, user_tg)
        shutdown_mode = get_bot_shutdown_mode(session)
        admin_user = is_admin(session, user_tg.id, OWNER_ID)
        owner_user = is_owner(user_tg.id, OWNER_ID)

        # تنظیمات خودکار سپر در PV Owner؛ فقط در همان چت مصرف می‌شود.
        auto_pending=context.user_data.get("shield_auto_setting_pending")
        if auto_pending and owner_user and _waiting_scope_matches(context,"shield_auto_setting_pending",message.chat_id):
            raw=(message.text or "").strip()
            if raw and (is_text_command(raw) or raw.startswith("/")):
                context.user_data.pop("shield_auto_setting_pending",None); context.user_data.pop(_waiting_scope_key("shield_auto_setting_pending"),None)
            else:
                try:
                    value=float(_enigma_parse_number(raw))
                    field=auto_pending.get("field")
                    if field=="auto_attack_threshold": value=int(value); valid=value>=1
                    else: valid=value>0
                    if not valid: raise ValueError
                    from services.economy import save_shield_auto_setting, get_shield_auto_settings
                    save_shield_auto_setting(session,field,value); session.commit()
                    context.user_data.pop("shield_auto_setting_pending",None); context.user_data.pop(_waiting_scope_key("shield_auto_setting_pending"),None)
                    st=get_shield_auto_settings(session)
                    from keyboards.admin import shield_auto_settings_keyboard
                    await message.reply_text(f"✅ تنظیم ذخیره شد.\n\n🎯 تعداد اتک لازم: <b>{st['auto_attack_threshold']}</b>\n🛡️ مدت سپر رایگان: <b>{st['auto_shield_hours']:g} ساعت</b>\n⏳ کسر از سپر هنگام اتک: <b>{st['shield_attack_penalty_hours']:g} ساعت</b>",parse_mode="HTML",reply_markup=shield_auto_settings_keyboard())
                    return
                except Exception:
                    await message.reply_text("❌ مقدار واردشده نامعتبر است. دوباره ارسال کنید.")
                    return

        # ویرایش مرحله‌ای سپر در چت خصوصی Owner؛ مقدار فقط پس از دریافت معتبر ذخیره می‌شود.
        shield_edit = context.user_data.get("shield_edit_pending")
        if shield_edit and owner_user and _waiting_scope_matches(context,"shield_edit_pending",message.chat_id):
            raw_edit = (message.text or "").strip()
            if raw_edit and (is_text_command(raw_edit) or raw_edit.startswith("/")):
                if command_key(raw_edit) in {command_key("برگشت"), command_key("🔙 برگشت")}:
                    typ=shield_edit.get("type"); item_id=shield_edit.get("item_id")
                    context.user_data.pop("shield_edit_pending", None); context.user_data.pop(_waiting_scope_key("shield_edit_pending"),None)
                    from keyboards.admin import shield_item_detail_keyboard
                    item=get_shield_item_by_id(session,item_id)
                    if item:
                        await message.reply_text(f"🛡️ <b>{escape(str(item.get('name','سپر')))}</b>",parse_mode="HTML",reply_markup=shield_item_detail_keyboard(typ,item_id,bool(item.get('active'))))
                    return
                # سایر فرمان‌ها نباید به عنوان مقدار ویرایش مصرف شوند.
                context.user_data.pop("shield_edit_pending", None); context.user_data.pop(_waiting_scope_key("shield_edit_pending"),None)
                shield_edit=None
            if shield_edit:
                try:
                    typ=shield_edit.get("type"); item_id=shield_edit.get("item_id"); field=shield_edit.get("field")
                    cfg=get_shield_config(session); item=next((x for x in cfg.get("items",[]) if str(x.get("id"))==str(item_id)),None)
                    if not item: raise ValueError
                    if field=="name":
                        if not raw_edit or len(raw_edit)>80: raise ValueError
                        item["name"]=raw_edit
                    else:
                        value=float(_enigma_parse_number(raw_edit))
                        if value<=0: raise ValueError
                        if field=="price": item["price"]=value
                        elif field=="duration": item["duration_hours"]=value
                        elif field=="cooldown": item["cooldown_hours"]=value
                        else: raise ValueError
                    save_shield_config(session,cfg); session.commit()
                    context.user_data.pop("shield_edit_pending", None); context.user_data.pop(_waiting_scope_key("shield_edit_pending"),None)
                    from keyboards.admin import shield_item_detail_keyboard
                    await message.reply_text(f"✅ <b>تغییرات سپر ذخیره شد.</b>\n\n🏷 نام: <b>{escape(str(item.get('name','سپر')))}</b>\n☢️ قیمت: <b>{float(item.get('price',0) or 0):,.0f} اورانیوم</b>\n⏱ مدت فعال بودن: <b>{float(item.get('duration_hours',0) or 0):g} ساعت</b>\n🔁 فاصله خرید: <b>{float(item.get('cooldown_hours',0) or 0):g} ساعت</b>",parse_mode="HTML",reply_markup=shield_item_detail_keyboard(typ,item_id,bool(item.get('active'))))
                    return
                except Exception:
                    await message.reply_text("❌ مقدار واردشده نامعتبر است. دوباره ارسال کنید:")
                    return

        # دریافت مرحله‌ای اطلاعات سپر در چت خصوصی Owner؛ تا تأیید نهایی فقط draft است.
        shield_add = context.user_data.get("shield_add_pending")
        if shield_add and owner_user and _waiting_scope_matches(context, "shield_add_pending", message.chat_id):
            raw = (message.text or "").strip()
            typ = shield_add.get("type")
            if raw and (is_text_command(raw) or raw.startswith("/")):
                if command_key(raw) in {command_key("برگشت"), command_key("🔙 برگشت")}:
                    context.user_data.pop("shield_add_pending", None); context.user_data.pop("shield_edit_pending", None); context.user_data.pop("shield_auto_setting_pending", None)
                    from keyboards.admin import shield_type_management_keyboard
                    await message.reply_text(f"🛡️ <b>{'سپرهای جهانی' if typ=='global' else 'سپرهای قاره‌ای'}</b>\n\nعملیات موردنظر را انتخاب کنید:", parse_mode="HTML", reply_markup=shield_type_management_keyboard(typ))
                    return
                context.user_data.pop("shield_add_pending", None); context.user_data.pop("shield_edit_pending", None); context.user_data.pop("shield_auto_setting_pending", None)
                shield_add = None
            if shield_add:
                try:
                    stage = shield_add.get("stage")
                    if stage == "name":
                        if not raw or len(raw) > 80: raise ValueError
                        shield_add["name"] = raw; shield_add["stage"] = "price"
                        await message.reply_text("☢️ <b>قیمت سپر</b>\n\nقیمت را فقط بر حسب اورانیوم ارسال کنید:", parse_mode="HTML", reply_markup=shield_add_keyboard(typ)); return
                    if stage == "price":
                        value = float(_enigma_parse_number(raw))
                        if value < 0: raise ValueError
                        shield_add["price"] = value; shield_add["stage"] = "duration"
                        await message.reply_text("⏱ <b>مدت فعال بودن سپر</b>\n\nمدت اعتبار را بر حسب ساعت ارسال کنید:", parse_mode="HTML", reply_markup=shield_add_keyboard(typ)); return
                    if stage == "duration":
                        value = float(_enigma_parse_number(raw))
                        if value <= 0: raise ValueError
                        shield_add["duration_hours"] = value; shield_add["stage"] = "cooldown"
                        await message.reply_text(
                            f"⏳ <b>فاصله خرید مجدد همین سپر</b>\n\nاین سپر چند ساعت بعد دوباره قابل خرید باشد؟", parse_mode="HTML", reply_markup=shield_add_keyboard(typ)); return
                    if stage == "cooldown":
                        value = float(_enigma_parse_number(raw))
                        if value <= 0: raise ValueError
                        shield_add["cooldown_hours"] = value; shield_add["stage"] = "confirm"
                        await message.reply_text(
                            f"🛡️ <b>پیش‌نمایش سپر</b>\n\n📌 نوع: <b>{'جهانی' if typ=='global' else 'قاره‌ای'}</b>\n🏷 نام: <b>{escape(str(shield_add.get('name','سپر')))}</b>\n☢️ قیمت: <b>{float(shield_add.get('price',0)):,.0f} اورانیوم</b>\n⏱ مدت: <b>{value} ثانیه</b>\n\nبرای ثبت نهایی تأیید کنید.\nاطلاعات تا قبل از تأیید در حافظه موقت باقی می‌ماند و هنوز ذخیره نشده است.",
                            parse_mode="HTML", reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("✅ تأیید و ذخیره نهایی", callback_data="owner:shield_confirm_add")],
                                [InlineKeyboardButton("✏️ ویرایش", callback_data=f"owner:shield_add:{typ}")],
                                [InlineKeyboardButton("🔙 برگشت", callback_data=f"owner:shield_type:{typ}")],
                            ])); return
                except Exception:
                    await message.reply_text("❌ مقدار نامعتبر است. لطفاً مقدار صحیح ارسال کنید.", reply_markup=shield_add_keyboard(typ)); return
        if not owner_user and (shutdown_mode == "all" or (shutdown_mode == "admins" and admin_user) or (shutdown_mode == "users" and not admin_user)):
            session.commit(); await message.reply_text("⏸️ ربات موقتاً خاموش است."); return
        for c in session.scalars(select(Country).where(Country.leader_user_id == user_tg.id)).all():
            c.leader_name = user_tg.full_name or user_tg.first_name or c.leader_name
        group_allowed = {command_key(x) for x in ("کشور", "شروعبازی", "شروع بازی")}
        pending_country = context.user_data.get(pending_key(user_tg.id)) is True
        if pending_country and not normalized.startswith("/") and normalized not in group_allowed:
            # هر دستور خصوصی که وسط دریافت نام کشور بیاید، انتظار نام را لغو می‌کند؛ اما در گروه اجرا نمی‌شود.
            private_only_tokens = {command_key(x) for x in ("معدنفلز", "تبادل", "نرختبادل", "مرکزفرماندهی", "انتخابکشورپیشفرض", "تغییرکشورپیشفرض", "جابجایی", "ویرایشنامکشور", "برگشت")}
            if normalized in private_only_tokens:
                context.user_data.pop(pending_key(user_tg.id), None)
                session.commit()
                return
        private_command_tokens = {command_key(x) for x in (
            "معدن فلز", "⛏️ معدن فلز", "زرادخانه", "🏭 زرادخانه", "فروشگاه", "🏪 فروشگاه", "خرید موشک", "🚀 خرید موشک", "کشور", "تبادل", "💱 تبادل", "نرخ تبادل", "📊 نرخ تبادل",
            "مرکز فرماندهی", "🏛️ مرکز فرماندهی", "خرید سپر", "🛡️ خرید سپر", "خرید سپر جهانی", "🛡️ خرید سپر جهانی", "خرید سپر قاره‌ای", "🛡️ خرید سپر قاره‌ای", "سپر جهانی", "🛡️ سپر جهانی", "سپر قاره‌ای", "🛡️ سپر قاره‌ای", "انتخاب کشور پیشفرض", "🌍 انتخاب کشور پیشفرض",
            "تغییر کشور پیشفرض", "🔄 تغییر کشور پیشفرض", "انتخاب گروه پیشفرض", "🌍 انتخاب گروه پیشفرض",
            "تغییر گروه پیشفرض", "🔄 تغییر گروه پیشفرض", "چت و کانال", "💬 چت و کانال", "برگشت", "🔙 برگشت", "تنظیمات بازی", "🎮 تنظیمات بازی", "تنظیمات اکانت", "🪪 تنظیمات اکانت",
            "ویرایش نام کشور", "🌍 ویرایش نام کشور", "جابجایی", "🔄 جابجایی",
            "پول به فلز", "💰 پول به فلز", "فلز به پول", "🔩 فلز به پول",
            "پول به سوخت", "💰 پول به سوخت", "سوخت به پول", "⛽ سوخت به پول",
            "اورانیوم به سوخت", "☢️ اورانیوم به سوخت", "☢ اورانیوم به سوخت", "اورانیوم به پول", "☢️ اورانیوم به پول", "☢ اورانیوم به پول",
            "کشور", "شروع بازی", "🏁 شروع بازی",
            # انتخاب نوع موشک در فروشگاه هم یک دستور متنی است و باید قبل از
            # رسیدن به گیت عمومی پردازش پیام مجاز باشد.
            "خرید موشک کروز", "🚀 خرید موشک کروز",
            "خرید موشک بالستیک", "🚀 خرید موشک بالستیک",
            "خرید موشک هایپرسونیک", "⚡ خرید موشک هایپرسونیک",
        )}
        store_nav = context.user_data.get("store_nav")
        # در مرحله انتخاب موشک فروشگاه، نام موشک یک ReplyKeyboard command است؛
        # بنابراین باید قبل از فیلتر دستورات عمومی اجازه عبور داشته باشد.
        store_missile_selection = store_nav == "purchase_list"
        waiting_state = any([
            pending_country,
            bool(context.user_data.get("admin_pending")),
            bool(context.user_data.get("balance_pending")),
            bool(context.user_data.get("pending_exchange")),
            bool(context.user_data.get("economy_pending")),
            bool(context.user_data.get("country_edit_waiting")),
            bool(context.user_data.get("country_edit")),
            bool(context.user_data.get("self_country_edit")),
            bool(context.user_data.get("country_name_pending")),
            bool(context.user_data.get("missile_pending")),
            bool(context.user_data.get("missile_operational_pending")),
            bool(context.user_data.get("admin_message_pending")),
            bool(context.user_data.get("exchange_text_pending")),
            bool(context.user_data.get("exchange_rate_pending")),
            bool(context.user_data.get("enigma_pending")),
            bool(context.user_data.get("security_pending")),
            bool(context.user_data.get("social_pending")),
            bool(context.user_data.get("arsenal_sell_custom_pending")),
            bool(context.user_data.get("shield_adjust_pending")),
            bool(context.user_data.get("shield_reset_pending")),
            store_missile_selection,
        ])
        if normalized not in group_allowed and normalized not in private_command_tokens and not waiting_state:
            session.commit()
            return
        # سیستم ارسال پیام مدیریتی
        mp = context.user_data.get("admin_message_pending") or {}
        if mp and (admin_user or owner_user):
            if mp.get("kind") == "private" and mp.get("step") in (None, "recipient"):
                raw=(message.text or "").strip()
                target=None
                # ID
                if raw.isdigit(): target=get_user_by_telegram_id(session,int(raw))
                # نام کاربری
                if target is None:
                    uname=raw.lstrip("@").casefold()
                    target=next((u for u in get_users(session) if (u.username or "").casefold()==uname),None)
                # phone
                if target is None:
                    target=next((u for u in get_users(session) if (u.phone_number or "").replace(" ","")==raw.replace(" ","")),None)
                # country name
                if target is None:
                    c=session.scalar(select(Country).where(Country.title==raw))
                    if c: target=get_user_by_telegram_id(session,c.leader_user_id)
                if target is None:
                    await message.reply_text("❌ کاربر پیدا نشد. آیدی، یوزرنیم، شماره تلفن یا نام کشور معتبر ارسال کنید."); return
                ids=mp.setdefault("recipients",[])
                if int(target.telegram_id) not in ids: ids.append(int(target.telegram_id))
                mp["step"]="recipient"; context.user_data["admin_message_pending"]=mp
                context.user_data[_waiting_scope_key("admin_message_pending")] = int(message.chat_id)
                from keyboards.admin import message_private_continue_keyboard
                await message.reply_text(f"✅ کاربر <code>{target.telegram_id}</code> اضافه شد.\n\nآیا کاربر دیگری هم اضافه می‌کنید؟",parse_mode="HTML",reply_markup=message_private_continue_keyboard()); return
            if mp.get("step") == "text":
                # هر نوع پیام تلگرام قابل ارسال است: متن، عکس، ویدئو، فایل، صدا، استیکر و...
                content_type = "text" if (message.text or "").strip() else ("photo" if message.photo else "video" if message.video else "document" if message.document else "audio" if message.audio else "voice" if message.voice else "sticker" if message.sticker else "animation" if message.animation else "other")
                if content_type == "text" and not (message.text or "").strip():
                    await message.reply_text("❌ پیام خالی قابل ارسال نیست."); return
                mp["text"]=(message.text or message.caption or "").strip()
                mp["source_chat_id"]=int(message.chat_id)
                mp["source_message_id"]=int(message.message_id)
                mp["content_type"]=content_type
                media = (message.photo[-1] if message.photo else message.video or message.document or message.audio or message.voice or message.sticker or message.animation)
                mp["file_id"] = getattr(media, "file_id", None)
                context.user_data["admin_message_pending"]=mp
                context.user_data[_waiting_scope_key("admin_message_pending")] = int(message.chat_id)
                from keyboards.admin import message_confirm_keyboard
                recipients=mp.get("recipients",[])
                target_desc = str(mp.get("target","all")) if mp.get("kind")=="public" else ", ".join(str(x) for x in recipients)
                preview = escape(mp["text"]) if mp["text"] else f"📎 پیام از نوع <b>{content_type}</b>"
                await message.reply_text(f"📨 <b>پیش‌نمایش پیام</b>\n\n{preview}\n\n📎 نوع محتوا: <b>{content_type}</b>\n👥 گیرندگان: <b>{escape(target_desc)}</b>\n\nارسال شود؟",parse_mode="HTML",reply_markup=message_confirm_keyboard()); return

        if user.is_banned and normalized in BAN_COMMAND_NAMES:
            session.commit()
            await message.reply_text(ban_status_text(user), parse_mode="HTML")
            return
        country = get_default_country(session, user)

        # کاربر خصوصی بدون کشور پیش‌فرض فقط می‌تواند تنظیمات بازی را باز کند.
        if (
            update.effective_chat
            and update.effective_chat.type == "private"
            and country is None
            and not is_owner(user_tg.id, OWNER_ID)
            and not is_admin(session, user_tg.id, OWNER_ID)
        ):
            allowed_without_country = {
                command_key("تنظیمات بازی"), command_key("🎮 تنظیمات بازی"),
                command_key("انتخاب کشور پیشفرض"), command_key("🌍 انتخاب کشور پیشفرض"),
                command_key("انتخاب گروه پیشفرض"), command_key("🌍 انتخاب گروه پیشفرض"),
                command_key("شروع بازی"), command_key("🏁 شروع بازی"),
            }
            if normalized not in allowed_without_country and not waiting_state:
                await message.reply_text("🎮 هنوز کشور پیش‌فرضی ندارید. ابتدا از تنظیمات بازی کشور خود را انتخاب کنید.", reply_markup=command_keyboard(no_country=True))
                session.commit()
                return

        # گیت ثبت شماره تلفن بر اساس نقش
        if phone_required_for(session, is_admin_user=is_admin(session, user_tg.id, OWNER_ID), is_owner_user=is_owner(user_tg.id, OWNER_ID)) and not user.phone_number:
            session.commit()
            await message.reply_text("📱 <b>ثبت شماره تلفن الزامی است.</b>\n\nابتدا مخاطب خودتان را از طریق دکمه ثبت شماره ارسال کنید.", parse_mode="HTML")
            return

        # IMPORTANT: resolve text commands before ANY waiting-state handler.
        # Otherwise a stale numeric/ID/name waiter can consume the command text.
        if is_text_command(message.text):
            clear_all_waiting_states(context, message.chat_id)
            context.user_data.pop(pending_key(user_tg.id), None)
            context.user_data.pop(f"country_name_pending_{user_tg.id}", None)
            context.user_data.pop(f"country_name_value_{user_tg.id}", None)

        # هر دستور جدید باید انتظار ورودی قبلی را لغو کند و سپس خودش اجرا شود.
        command_names = {command_key(x) for x in (
            "کشور", "تبادل", "💱 تبادل", "نرخ تبادل", "📊 نرخ تبادل", "مرکز فرماندهی", "🏛️ مرکز فرماندهی",
            "معدن فلز", "⛏️ معدن فلز", "زرادخانه", "🏭 زرادخانه", "فروشگاه", "🏪 فروشگاه", "خرید سپر", "🛡️ خرید سپر", "خرید سپر جهانی", "🛡️ خرید سپر جهانی", "خرید سپر قاره‌ای", "🛡️ خرید سپر قاره‌ای", "سپر جهانی", "🛡️ سپر جهانی", "سپر قاره‌ای", "🛡️ سپر قاره‌ای", "موشک‌های کروز", "موشک‌های بالستیک", "موشک‌های هایپرسونیک", "انتخاب کشور پیشفرض", "🌍 انتخاب کشور پیشفرض",
            "تغییر کشور پیشفرض", "🔄 تغییر کشور پیشفرض", "انتخاب گروه پیشفرض", "🌍 انتخاب گروه پیشفرض",
            "تغییر گروه پیشفرض", "🔄 تغییر گروه پیشفرض", "چت و کانال", "💬 چت و کانال", "برگشت", "🔙 برگشت", "تنظیمات بازی", "🎮 تنظیمات بازی", "تنظیمات اکانت", "🪪 تنظیمات اکانت",
            "ویرایش نام کشور", "🌍 ویرایش نام کشور", "جابجایی", "🔄 جابجایی", "کشور", "شروع بازی", "🏁 شروع بازی", "فروشگاه", "🏪 فروشگاه", "موشک‌های کروز", "موشک‌های بالستیک", "موشک‌های هایپرسونیک",
            "پنل ادمین", "پنل owner",
            "خرید موشک کروز", "🚀 خرید موشک کروز",
            "خرید موشک بالستیک", "🚀 خرید موشک بالستیک",
            "خرید موشک هایپرسونیک", "⚡ خرید موشک هایپرسونیک",
            "پول به فلز", "💰 پول به فلز", "فلز به پول", "🔩 فلز به پول",
            "پول به سوخت", "💰 پول به سوخت", "سوخت به پول", "⛽ سوخت به پول", "اورانیوم به سوخت", "☢️ اورانیوم به سوخت", "اورانیوم به پول", "☢️ اورانیوم به پول",
        )}
        if normalized in command_names:
            for key in ("economy_pending", "balance_pending", "country_edit_waiting", "country_edit_name", "self_country_edit", "self_country_edit_name", "country_edit", "pending_exchange", "exchange_rate_pending", "admin_pending", "swap_pending", "missile_pending", "missile_operational_pending", "security_pending", "social_pending", "admin_leadership_bulk_pending", "admin_leadership_pending", "arsenal_sell_custom_pending", "arsenal_sell_pending", "shield_adjust_pending", "shield_reset_pending", "shield_add_pending"):
                _clear_waiting_key(context, key, message.chat_id)
            context.user_data.pop(pending_key(user_tg.id), None)
            context.user_data.pop(f"country_name_pending_{user_tg.id}", None)
            context.user_data.pop(f"country_name_value_{user_tg.id}", None)

        # دریافت نام عملیاتی موشک توسط Owner
        missile_operational_pending = context.user_data.get("missile_operational_pending")
        if missile_operational_pending and is_owner(user_tg.id, OWNER_ID) and (message.text or "").strip():
            raw_name=(message.text or "").strip()
            if len(raw_name) > 100:
                await message.reply_text("❌ نام عملیاتی بیش از ۱۰۰ کاراکتر است.")
                return
            cfg=get_missiles_config(session)
            mid=str(missile_operational_pending.get("id"))
            m=next((x for x in cfg.get("items",[]) if str(x.get("id"))==mid),None)
            if not m:
                context.user_data.pop("missile_operational_pending",None)
                await message.reply_text("❌ موشک پیدا نشد.")
                return
            names=m.setdefault("operational_names",[]) or []
            if raw_name in names:
                await message.reply_text("❌ این نام عملیاتی قبلاً ثبت شده است.")
                return
            names.append(raw_name)
            m["operational_names"]=names
            save_missiles_config(session,cfg); session.commit()
            context.user_data.pop("missile_operational_pending",None)
            from keyboards.admin import missile_operational_keyboard
            await message.reply_text(f"✅ نام عملیاتی «{escape(raw_name)}» اضافه شد.",parse_mode="HTML",reply_markup=missile_operational_keyboard(mid))
            return

        # تنظیم متن تبادل توسط Owner
        exchange_text_pending = context.user_data.get("exchange_text_pending")
        if exchange_text_pending and is_owner(user_tg.id, OWNER_ID) and (message.text or "").strip():
            text = (message.text or "").strip()
            if len(text) > 4000:
                await message.reply_text("❌ متن تبادل بیش از حد طولانی است. حداکثر ۴۰۰۰ کاراکتر.")
                return
            context.user_data["exchange_text_draft"] = text
            context.user_data.pop("exchange_text_pending", None)
            from keyboards.admin import exchange_text_confirm_keyboard
            await message.reply_text("🧾 <b>متن جدید تبادل</b>\n\n" + escape(text) + "\n\nآیا این متن کامل تأیید شود؟", parse_mode="HTML", reply_markup=exchange_text_confirm_keyboard())
            return

        # تنظیم دلخواه درصد غارت کلی توسط Owner
        if context.user_data.get("global_loot_percent_pending") and is_owner(user_tg.id, OWNER_ID) and (message.text or "").strip():
            raw = (message.text or "").strip().replace(",", "").replace("٪", "%")
            try:
                value = max(0.0, min(100.0, float(raw.replace("%", ""))))
            except ValueError:
                await message.reply_text("❌ درصد نامعتبر است.")
                return
            set_global_loot_percent(session, value); session.commit()
            context.user_data.pop("global_loot_percent_pending", None)
            from keyboards.admin import missile_global_loot_percent_keyboard
            await message.reply_text(f"✅ درصد غارت منابع کلی روی <b>{value:g}%</b> تنظیم شد.", parse_mode="HTML", reply_markup=missile_global_loot_percent_keyboard())
            return

        # ثبت استیکر اختصاصی شلیک موشک توسط Owner
        missile_pending = context.user_data.get("missile_pending")
        if missile_pending and missile_pending.get("step") == "sticker" and is_owner(user_tg.id, OWNER_ID) and message.sticker:
            cfg=get_missiles_config(session)
            mid=str(missile_pending.get("id"))
            m=next((x for x in cfg.get("items",[]) if str(x.get("id"))==mid),None)
            if not m:
                context.user_data.pop("missile_pending",None)
                await message.reply_text("❌ موشک پیدا نشد.")
                return
            m["launch_sticker"] = str(message.sticker.file_id)
            save_missiles_config(session,cfg); session.commit()
            context.user_data.pop("missile_pending",None)
            # بعد از ذخیره، فقط یک پیام با پنل «تنظیمات بازی» نمایش بده؛
            # پیام تأیید جداگانه همراه با پنل دیگری ساخته نشود.
            await message.reply_text("🎮 <b>تنظیمات بازی</b>\n\nاستیکر شلیک موشک با موفقیت ذخیره شد. از این پس هنگام شلیک، ابتدا استیکر و سپس مشخصات حمله ارسال می‌شود.", parse_mode="HTML", reply_markup=game_settings_user_keyboard())
            return

        # مدیریت موشک‌ها توسط Owner
        missile_pending = context.user_data.get("missile_pending")
        if missile_pending and is_owner(user_tg.id, OWNER_ID) and (message.text or "").strip():
            raw=(message.text or "").strip()
            cfg=get_missiles_config(session)
            step=missile_pending.get("step")
            if step=="name":
                typ=missile_pending.get("type","کروز")
                context.user_data["missile_pending"]={"step":"name_confirm","type":typ,"name":raw}
                context.user_data[_waiting_scope_key("missile_pending")] = int(message.chat_id)
                from keyboards.admin import missile_name_confirm_keyboard
                await message.reply_text(f"🚀 <b>نام موشک</b>\n\nنام واردشده: <b>{escape(raw)}</b>\nنوع: <b>{escape(typ)}</b>\n\nنام موشک تأیید شود؟",parse_mode="HTML",reply_markup=missile_name_confirm_keyboard())
                return
            if step=="name_confirm":
                return
            try:
                value=float(raw.replace(",","").replace("٬","").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹","0123456789")))
            except ValueError:
                await message.reply_text("❌ مقدار باید عددی باشد."); return
            if value<0:
                await message.reply_text("❌ مقدار نمی‌تواند منفی باشد."); return
            # هیچ تنظیم موشکی تا قبل از تأیید نهایی ذخیره نمی‌شود.
            if missile_pending.get("draft"):
                draft=context.user_data.get("missile_draft")
                if not draft:
                    context.user_data.pop("missile_pending",None); await message.reply_text("❌ عملیات منقضی شده است."); return
                missile_pending["value"] = value
                context.user_data["missile_pending"] = missile_pending
                context.user_data[_waiting_scope_key("missile_pending")] = int(message.chat_id)
                from keyboards.admin import missile_value_confirm_keyboard
                await message.reply_text(f"🧾 مقدار واردشده: <b>{value:,.0f}</b>\n\nآیا این مقدار تأیید شود؟", parse_mode="HTML", reply_markup=missile_value_confirm_keyboard())
                return
            mid=str(missile_pending.get("id")); m=next((x for x in cfg.get("items",[]) if str(x.get("id"))==mid),None)
            if not m:
                context.user_data.pop("missile_pending",None); await message.reply_text("❌ موشک پیدا نشد."); return
            missile_pending["value"] = value
            context.user_data["missile_pending"] = missile_pending
            context.user_data[_waiting_scope_key("missile_pending")] = int(message.chat_id)
            from keyboards.admin import missile_value_confirm_keyboard
            await message.reply_text(f"🧾 مقدار واردشده: <b>{value:,.0f}</b>\n\nآیا این مقدار تأیید شود؟", parse_mode="HTML", reply_markup=missile_value_confirm_keyboard())
            return

        # دریافت نام عملیاتی موشک توسط Owner
        missile_operational_pending = context.user_data.get("missile_operational_pending")
        if missile_operational_pending and is_owner(user_tg.id, OWNER_ID) and (message.text or "").strip():
            raw_name=(message.text or "").strip()
            if len(raw_name) > 100:
                await message.reply_text("❌ نام عملیاتی بیش از ۱۰۰ کاراکتر است.")
                return
            cfg=get_missiles_config(session)
            mid=str(missile_operational_pending.get("id"))
            m=next((x for x in cfg.get("items",[]) if str(x.get("id"))==mid),None)
            if not m:
                context.user_data.pop("missile_operational_pending",None)
                await message.reply_text("❌ موشک پیدا نشد.")
                return
            names=m.setdefault("operational_names",[]) or []
            if raw_name in names:
                await message.reply_text("❌ این نام عملیاتی قبلاً ثبت شده است.")
                return
            names.append(raw_name)
            m["operational_names"]=names
            save_missiles_config(session,cfg); session.commit()
            context.user_data.pop("missile_operational_pending",None)
            from keyboards.admin import missile_operational_keyboard
            await message.reply_text(f"✅ نام عملیاتی «{escape(raw_name)}» اضافه شد.",parse_mode="HTML",reply_markup=missile_operational_keyboard(mid))
            return

        # تنظیم متن تبادل توسط Owner
        exchange_text_pending = context.user_data.get("exchange_text_pending")
        if exchange_text_pending and is_owner(user_tg.id, OWNER_ID) and (message.text or "").strip():
            text = (message.text or "").strip()
            if len(text) > 2000:
                await message.reply_text("❌ متن تبادل بیش از حد طولانی است. حداکثر ۲۰۰۰ کاراکتر.")
                return
            context.user_data["exchange_text_draft"] = text
            context.user_data.pop("exchange_text_pending", None)
            from keyboards.admin import exchange_text_confirm_keyboard
            await message.reply_text("🧾 <b>متن جدید تبادل</b>\n\n" + escape(text) + "\n\nآیا این متن کامل تأیید شود؟", parse_mode="HTML", reply_markup=exchange_text_confirm_keyboard())
            return

        # تنظیم نرخ تبادل Owner — دریافت مرحله‌ای دو مقدار
        exchange_rate_pending = context.user_data.get("exchange_rate_pending")
        if exchange_rate_pending and is_owner(user_tg.id, OWNER_ID) and (message.text or "").strip():
            raw=(message.text or "").strip().replace(",", "").replace("٬", "").replace("٫", ".").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
            try:
                value=float(raw)
                if value<=0: raise ValueError
            except ValueError:
                rate=get_exchange_rates(session).get(exchange_rate_pending.get("key"))
                resource_names={"money":"💰 پول","metal":"🔩 فلز","fuel":"⛽ سوخت","uranium":"☢️ اورانیوم"}
                wanted=resource_names.get((rate or {}).get("from_resource"), "منبع") if exchange_rate_pending.get("step",1)==1 else resource_names.get((rate or {}).get("to_resource"), "منبع")
                await message.reply_text(f"❌ مقدار {wanted} باید یک عدد مثبت باشد.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت",callback_data="owner:exchange_settings")]])); return

            rate=get_exchange_rates(session).get(exchange_rate_pending.get("key"))
            if not rate:
                context.user_data.pop("exchange_rate_pending",None)
                await message.reply_text("❌ نوع تبادل نامعتبر است.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت",callback_data="owner:exchange_settings")]])); return
            resource_names={"money":"💰 پول","metal":"🔩 فلز","fuel":"⛽ سوخت","uranium":"☢️ اورانیوم"}
            step=int(exchange_rate_pending.get("step",1))
            if step==1:
                exchange_rate_pending["input_unit"]=value
                exchange_rate_pending["step"]=2
                context.user_data["exchange_rate_pending"]=exchange_rate_pending
                context.user_data[_waiting_scope_key("exchange_rate_pending")] = int(message.chat_id)
                await message.reply_text(
                    f"💱 <b>{rate['title']}</b>\n\n"
                    f"✅ مقدار {resource_names[rate['from_resource']]}: <b>{value:,.0f}</b>\n\n"
                    f"حالا مقدار {resource_names[rate['to_resource']]} را ارسال کنید.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت",callback_data="owner:exchange_settings")]])
                ); return

            save_exchange_rate(session, exchange_rate_pending["key"], exchange_rate_pending["input_unit"], value)
            session.commit(); context.user_data.pop("exchange_rate_pending",None)
            await message.reply_text(
                f"✅ نرخ تبادل ذخیره شد.\n\n"
                f"{resource_names[rate['from_resource']]}: <b>{exchange_rate_pending['input_unit']:,.0f}</b>\n"
                f"{resource_names[rate['to_resource']]}: <b>{value:,.0f}</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت",callback_data="owner:exchange_settings")]])
            ); return

        # تنظیمات اقتصاد Owner
        economy_pending = context.user_data.get("economy_pending")
        if economy_pending and not context.user_data.get("enigma_pending") and (message.text or "").strip():
            raw = (message.text or "").strip().replace(",", "").replace("٬", "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
            try:
                value = float(raw)
            except ValueError:
                await message.reply_text("❌ مقدار باید یک عدد معتبر باشد.")
                return
            if value < 0:
                await message.reply_text("❌ مقدار نمی‌تواند منفی باشد.")
                return
            if economy_pending.get("type") in {"swap_cooldown", "country_establish_uranium"}:
                economy_pending["value"] = value
                context.user_data["economy_pending"] = economy_pending
                context.user_data[_waiting_scope_key("economy_pending")] = int(message.chat_id)
                session.commit()
                label = "محدودیت جابه‌جایی (ساعت)" if economy_pending.get("type") == "swap_cooldown" else "هزینه اورانیوم تأسیس کشور"
                await message.reply_text(
                    f"✏️ <b>{label}</b>\n\nمقدار جدید: <b>{value:,.0f}</b>\n\nآیا این مقدار تأیید شود؟",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ تأیید", callback_data="owner:economy_value_confirm")],
                        [InlineKeyboardButton("✏️ ویرایش", callback_data="owner:economy_value_edit")],
                        [InlineKeyboardButton("🔙 برگشت", callback_data="owner:economy_value_cancel")],
                    ])
                )
                return

            if economy_pending.get("building") == "settings" and economy_pending.get("type") in {"country_rename_uranium", "country_rename_money"}:
                # هزینه تغییر نام باید مستقل از منطق اقتصاد ساختمان‌ها پردازش شود.
                economy_pending["value"] = value
                context.user_data["economy_pending"] = economy_pending
                context.user_data[_waiting_scope_key("economy_pending")] = int(message.chat_id)
                label = "☢️ اورانیوم" if economy_pending.get("type") == "country_rename_uranium" else "💰 پول"
                await message.reply_text(
                    f"💳 <b>هزینه تغییر نام با {label}</b>\n\nمقدار جدید: <b>{value:,.0f}</b>\n\nآیا تأیید شود؟",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ تأیید", callback_data="owner:economy_value_confirm")],
                        [InlineKeyboardButton("✏️ ویرایش", callback_data="owner:economy_value_edit")],
                        [InlineKeyboardButton("❌ لغو", callback_data="owner:economy_value_cancel")],
                    ])
                )
                return

            if economy_pending.get("building") == "leadership":
                ptype=economy_pending.get("type")
                economy_pending["value"]=value
                context.user_data["economy_pending"]=economy_pending
                context.user_data[_waiting_scope_key("economy_pending")] = int(message.chat_id)
                labels={"group":"⚔️ تجربه رهبری پایه گروه","global":"🌐 تجربه رهبری پایه سراسری","reset":"⏱️ زمان ریست حمله‌های تکراری (ساعت)"}
                label=labels.get(ptype,"تنظیم تجربه رهبری")
                session.commit()
                await message.reply_text(
                    f"✏️ <b>{label}</b>\n\nمقدار جدید: <b>{value:,.0f}</b>\n\nآیا این مقدار تأیید شود؟",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ تأیید",callback_data="owner:economy_value_confirm")],
                        [InlineKeyboardButton("✏️ ویرایش",callback_data="owner:economy_value_edit")],
                        [InlineKeyboardButton("❌ لغو",callback_data="owner:economy_value_cancel")],
                    ])
                )
                return

            if economy_pending.get("building") == "initial":
                economy_pending["value"]=value; context.user_data["economy_pending"]=economy_pending; session.commit()
                context.user_data[_waiting_scope_key("economy_pending")] = int(message.chat_id)
                await message.reply_text(f"✏️ <b>مقدار جدید</b>\n\n<b>{value:,.0f}</b>\n\nآیا تأیید شود؟",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ تأیید",callback_data="owner:economy_value_confirm")],[InlineKeyboardButton("✏️ ویرایش",callback_data="owner:economy_value_edit")],[InlineKeyboardButton("🔙 برگشت",callback_data="owner:economy_value_cancel")]])); return

            if economy_pending.get("building") == "hq":
                field = economy_pending.get("field")
                ptype = economy_pending.get("type")
                if ptype == "max_level":
                    if not raw.isdigit() or not 1 <= int(raw) <= 100:
                        await message.reply_text("❌ حداکثر سطح باید عدد صحیح بین 1 تا 100 باشد.")
                        return
                    economy_pending["value"] = int(raw)
                    economy_pending["back_callback"] = "owner:economy_hq"
                    label = "حداکثر سطح مرکز فرماندهی"
                elif ptype in {"build_military_power", "build_strength", "build_completion_time", "build_cost", "level", "hq_instant_finish_rate"}:
                    economy_pending["value"] = value
                    if ptype == "level":
                        economy_pending["back_callback"] = f"owner:hq_level:{int(economy_pending['level'])}"
                        label = f"تنظیم سطح {int(economy_pending['level'])}"
                    elif ptype == "build_cost":
                        economy_pending["back_callback"] = "owner:hq_build_costs"
                        label = f"هزینه ساخت {field}"
                    elif ptype == "hq_instant_finish_rate":
                        economy_pending["back_callback"] = "owner:economy_hq"
                        label = "☢️ اورانیوم تکمیل فوری مرکز فرماندهی (ساعتی)"
                    else:
                        economy_pending["back_callback"] = "owner:hq_build"
                        label = "قدرت نظامی ساخت مرکز فرماندهی" if ptype == "build_military_power" else "استحکام ساخت مرکز فرماندهی"
                else:
                    await message.reply_text("⚠️ عملیات اقتصاد مرکز فرماندهی نامعتبر است.")
                    return
                context.user_data["economy_pending"] = economy_pending
                context.user_data[_waiting_scope_key("economy_pending")] = int(message.chat_id)
                session.commit()
                await message.reply_text(
                    f"✏️ <b>{label}</b>\n\nمقدار جدید: <b>{economy_pending['value']:,.0f}</b>\n\nآیا این مقدار تأیید شود?",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ تأیید", callback_data="owner:economy_value_confirm")],
                        [InlineKeyboardButton("✏️ ویرایش", callback_data="owner:economy_value_edit")],
                        [InlineKeyboardButton("❌ لغو", callback_data="owner:economy_value_cancel")],
                    ])
                )
                return

            if economy_pending.get("building") == "mine":
                ptype = economy_pending.get("type")
                if ptype == "mine_instant_finish_rate":
                    economy_pending["value"] = value
                    economy_pending["back_callback"] = "owner:economy_metal_mine"
                    context.user_data["economy_pending"] = economy_pending
                    context.user_data[_waiting_scope_key("economy_pending")] = int(message.chat_id)
                    context.user_data["owner_economy_confirm"] = dict(economy_pending)
                    context.user_data[_waiting_scope_key("owner_economy_confirm")] = int(message.chat_id)
                    session.commit()
                    await message.reply_text(
                        f"✏️ <b>☢️ اورانیوم تکمیل فوری معدن فلز (ساعتی)</b>\n\nمقدار جدید: <b>{value:,.2f}</b>\n\nآیا این مقدار تأیید شود؟",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅ تأیید", callback_data="owner:economy_value_confirm")],
                            [InlineKeyboardButton("✏️ ویرایش", callback_data="owner:economy_value_edit")],
                            [InlineKeyboardButton("❌ لغو", callback_data="owner:economy_value_cancel")],
                        ])
                    )
                    return

            if economy_pending.get("building") == "arsenal":
                if economy_pending.get("type") == "arsenal_instant_finish_rate":
                    economy_pending["value"] = value
                    economy_pending["back_callback"] = "owner:economy_arsenal"
                    context.user_data["economy_pending"] = economy_pending
                    context.user_data[_waiting_scope_key("economy_pending")] = int(message.chat_id)
                    context.user_data["owner_economy_confirm"] = dict(economy_pending)
                    context.user_data[_waiting_scope_key("owner_economy_confirm")] = int(message.chat_id)
                    session.commit()
                    await message.reply_text(
                        f"✏️ <b>☢️ اورانیوم تکمیل فوری زرادخانه (ساعتی)</b>\n\nمقدار جدید: <b>{value:,.2f}</b> اورانیوم در ساعت\n\nآیا این مقدار تأیید شود؟",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅ تأیید", callback_data="owner:economy_value_confirm")],
                            [InlineKeyboardButton("✏️ ویرایش", callback_data="owner:economy_value_edit")],
                            [InlineKeyboardButton("❌ لغو", callback_data="owner:economy_value_cancel")],
                        ])
                    )
                    return

                if economy_pending.get("type") == "max_level":
                    if not raw.isdigit() or not 2 <= int(raw) <= 100:
                        await message.reply_text("❌ حداکثر سطح باید عدد صحیح بین 2 تا 100 باشد.")
                        return
                    economy_pending["value"]=int(raw)
                    economy_pending["back_callback"]="owner:economy_arsenal"
                elif economy_pending.get("type") in {"build_storage_capacity","build_military_power","build_strength","build_completion_time","build_cost","level","required_hq_level"}:
                    economy_pending["value"]=value
                    if economy_pending.get("type")=="level":
                        economy_pending["back_callback"]=f"owner:arsenal_level:{int(economy_pending['level'])}"
                    elif economy_pending.get("type")=="build_cost":
                        economy_pending["back_callback"]="owner:arsenal_build_costs"
                    else:
                        economy_pending["back_callback"]="owner:arsenal_build"
                context.user_data["economy_pending"]=economy_pending
                context.user_data[_waiting_scope_key("economy_pending")] = int(message.chat_id)
                label="حداکثر سطح زرادخانه" if economy_pending.get("type")=="max_level" else "تنظیم زرادخانه"
                await message.reply_text(f"✏️ <b>{label}</b>\n\nمقدار جدید: <b>{value:,.0f}</b>\n\nآیا این مقدار تأیید شود؟",parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ تأیید",callback_data="owner:economy_value_confirm")],
                        [InlineKeyboardButton("✏️ ویرایش",callback_data="owner:economy_value_edit")],
                        [InlineKeyboardButton("❌ لغو",callback_data="owner:economy_value_cancel")],
                    ]))
                return

            cfg = get_metal_mine_config(session)
            field = economy_pending.get("field")
            if economy_pending.get("type") == "max_level":
                if not raw.isdigit():
                    await message.reply_text("❌ حداکثر سطح باید عدد صحیح بین 2 تا 100 باشد.")
                    return
                max_level = int(raw)
                if max_level < 2 or max_level > 100:
                    await message.reply_text("❌ حداکثر سطح باید بین 2 تا 100 باشد.")
                    return
                economy_pending["value"] = max_level
                economy_pending["back_callback"] = "owner:economy_metal_mine"
                context.user_data["economy_pending"] = economy_pending
                context.user_data[_waiting_scope_key("economy_pending")] = int(message.chat_id)
                session.commit()
                await message.reply_text(
                    f"🔝 <b>حداکثر سطح معدن</b>\n\nمقدار جدید: <b>{max_level}</b>\n\nآیا این مقدار تأیید شود؟",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ تأیید", callback_data="owner:economy_value_confirm")],
                        [InlineKeyboardButton("✏️ ویرایش", callback_data="owner:economy_value_edit")],
                        [InlineKeyboardButton("🔙 برگشت", callback_data="owner:economy_value_cancel")],
                    ])
                )
                return

            if economy_pending.get("type") in {"build_required_hq_level", "build_military", "build_strength", "build_production", "build_storage", "build_completion_time", "build_cost", "build_cost_uranium", "level"}:
                economy_pending["value"] = value
                if economy_pending.get("type") == "level":
                    economy_pending["back_callback"] = f"owner:mine_level:{int(economy_pending['level'])}"
                    label = f"تنظیم سطح {int(economy_pending['level'])}"
                elif economy_pending.get("type") == "build_required_hq_level":
                    economy_pending["back_callback"] = "owner:economy_metal_mine"
                    label = "سطح مرکز فرماندهی موردنیاز ساخت معدن"
                elif economy_pending.get("type") == "build_military":
                    economy_pending["back_callback"] = "owner:economy_metal_mine"
                    label = "قدرت نظامی ساخت"
                elif economy_pending.get("type") == "build_strength":
                    economy_pending["back_callback"] = "owner:economy_metal_mine"
                    label = "استحکام ساخت"
                elif economy_pending.get("type") == "build_production":
                    economy_pending["back_callback"] = "owner:economy_metal_mine"
                    label = "تولید در ساعت ساخت"
                elif economy_pending.get("type") == "build_storage":
                    economy_pending["back_callback"] = "owner:economy_metal_mine"
                    label = "ظرفیت مخزن ساخت"
                elif economy_pending.get("type") == "build_completion_time":
                    economy_pending["back_callback"] = "owner:economy_metal_mine"
                    label = "زمان تکمیل ساخت"
                elif economy_pending.get("type") == "build_cost_uranium":
                    economy_pending["back_callback"] = "owner:mine_build_costs"
                    label = "هزینه ساخت با اورانیوم"
                else:
                    economy_pending["back_callback"] = "owner:mine_build_costs"
                    label = f"هزینه ساخت {field}"
                context.user_data["economy_pending"] = economy_pending
                context.user_data[_waiting_scope_key("economy_pending")] = int(message.chat_id)
                session.commit()
                await message.reply_text(
                    f"✏️ <b>{label}</b>\n\nمقدار جدید: <b>{value:,.0f}</b>\n\nآیا این مقدار تأیید شود؟",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ تأیید", callback_data="owner:economy_value_confirm")],
                        [InlineKeyboardButton("✏️ ویرایش", callback_data="owner:economy_value_edit")],
                        [InlineKeyboardButton("❌ لغو", callback_data="owner:economy_value_cancel")],
                    ])
                )
                return

        # عملیات افزایش/کاهش/ریست سپر کاربران؛ فقط در همان چتی که عملیات شروع شده است.
        shield_pending = context.user_data.get("shield_adjust_pending")
        if shield_pending and (message.text or "").strip() and _waiting_scope_matches(context,"shield_adjust_pending",message.chat_id) and (is_owner(user_tg.id, OWNER_ID) or is_admin(session,user_tg.id,OWNER_ID)):
            raw=(message.text or "").strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹","0123456789")).replace(",","").replace("٬","").replace("٫",".")
            if shield_pending.get("mode") in {"single", "multiple"} and not shield_pending.get("shield_type"):
                target=_search_user_by_any(session,raw,get_users(session))
                if target is None:
                    await message.reply_text("❌ کاربری با این مشخصات پیدا نشد."); return
                uid=int(target.telegram_id)
                if any((int(x.get("user_id")) if isinstance(x,dict) else int(x))==uid for x in shield_pending.get("users",[])):
                    await message.reply_text("⚠️ این کاربر قبلاً انتخاب شده است."); return
                countries=get_user_countries(session,target)
                if not countries:
                    await message.reply_text("⚠️ این کاربر هیچ کشوری ندارد."); return
                shield_pending["pending_country_user_id"]=uid; context.user_data["shield_adjust_pending"]=shield_pending
                from keyboards.admin import shield_user_country_pick_keyboard
                await message.reply_text(f"🌍 <b>کشور کاربر {uid} را انتخاب کنید</b>",parse_mode="HTML",reply_markup=shield_user_country_pick_keyboard(uid,countries,"adjust",shield_pending.get("back_callback","admin:user_tools"))); return
            try: amount=float(raw)
            except Exception:
                await message.reply_text("❌ مقدار باید یک عدد معتبر باشد."); return
            if amount<=0:
                await message.reply_text("❌ مقدار باید بیشتر از صفر باشد."); return
            shield_pending["amount"]=amount; context.user_data["shield_adjust_pending"]=shield_pending
            users_text="\n".join(f"🆔 <code>{(entry.get('user_id') if isinstance(entry,dict) else entry)}</code>" + (f" — 🌍 <code>{entry.get('country_id')}</code>" if isinstance(entry,dict) else "") for entry in shield_pending.get("users",[]))
            typ="سپر جهانی" if shield_pending.get("shield_type")=="global" else "سپر قاره‌ای"; sign_text="افزایش" if shield_pending.get("sign")=="add" else "کاهش"
            await message.reply_text(f"🛡️ <b>تأیید تنظیم سپر</b>\n\n{users_text}\n\n{typ}: <b>{sign_text} {amount:g} ساعت</b>\n\nآیا تأیید می‌کنید؟",parse_mode="HTML",reply_markup=shield_user_confirm_keyboard())
            return

        shield_reset_pending=context.user_data.get("shield_reset_pending")
        if shield_reset_pending and (message.text or "").strip() and _waiting_scope_matches(context,"shield_reset_pending",message.chat_id) and (is_owner(user_tg.id, OWNER_ID) or is_admin(session,user_tg.id,OWNER_ID)):
            raw=(message.text or "").strip()
            target=_search_user_by_any(session,raw,get_users(session))
            if target is None:
                await message.reply_text("❌ کاربری با این مشخصات پیدا نشد."); return
            uid=int(target.telegram_id)
            if any((int(x.get("user_id")) if isinstance(x,dict) else int(x))==uid for x in shield_reset_pending.get("users",[])):
                await message.reply_text("⚠️ این کاربر قبلاً انتخاب شده است."); return
            countries=get_user_countries(session,target)
            if not countries:
                await message.reply_text("⚠️ این کاربر هیچ کشوری ندارد."); return
            shield_reset_pending["pending_country_user_id"]=uid; context.user_data["shield_reset_pending"]=shield_reset_pending
            from keyboards.admin import shield_user_country_pick_keyboard
            await message.reply_text(f"🌍 <b>کشور کاربر {uid} را برای ریست انتخاب کنید</b>",parse_mode="HTML",reply_markup=shield_user_country_pick_keyboard(uid,countries,"reset", "admin:shield_manage")); return

        # عملیات افزایش/کاهش موجودی
        balance_pending = context.user_data.get("balance_pending")
        if balance_pending and (message.text or "").strip():
            raw = (message.text or "").strip().replace(",", "").replace("٬", "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
            # در حالت چندنفره، ابتدا IDها دریافت می‌شوند؛ پس از انتخاب منبع، مقدار دریافت می‌شود.
            if balance_pending.get("mode") == "multiple" and not balance_pending.get("resource"):
                target = _search_user_by_any(session, raw, get_users(session))
                if target is None:
                    await message.reply_text("❌ کاربری با این مشخصات پیدا نشد. آیدی، نام کاربری با @، شماره تلفن یا نام کشور را ارسال کنید.")
                    return
                target_id = int(target.telegram_id)
                if target_id in balance_pending["users"]:
                    await message.reply_text("⚠️ این کاربر قبلاً انتخاب شده است.")
                    return
                balance_pending["pending_user_id"] = target_id
                context.user_data["balance_pending"] = balance_pending
                context.user_data[_waiting_scope_key("balance_pending")] = int(message.chat_id)
                session.commit()
                countries=get_user_countries(session,target); default_country=get_default_country(session,target)
                role="👑 مالک" if is_owner(target.telegram_id,OWNER_ID) else ("🛡 ادمین" if is_admin(session,target.telegram_id,OWNER_ID) else "👤 کاربر عادی")
                profile=(f"🔎 <b>کاربر پیدا شد</b>\n\n👤 نام: <b>{escape(target.first_name or target.username or 'بدون نام')}</b>\n🆔 آیدی: <code>{target.telegram_id}</code>\n🔤 نام کاربری: {escape('@'+target.username if target.username else 'ثبت نشده')}\n📱 شماره: {escape(target.phone_number or 'ثبت نشده')}\n🎭 نقش: {role}\n🌍 کشور پیش‌فرض: {escape(default_country.title) if default_country else 'ثبت نشده'}\n🌎 تعداد کشورها: <b>{len(countries)}</b>\n\n")
                await message.reply_text(profile+"آیا این کاربر برای تغییر موجودی تأیید شود؟", parse_mode="HTML", reply_markup=user_search_confirm_keyboard(target_id, "admin:balance_change", "admin:balance_search_confirm:{user_id}"))
                return
            if balance_pending.get("resource"):
                try:
                    amount = float(raw)
                except ValueError:
                    await message.reply_text("❌ مقدار باید یک عدد معتبر باشد.")
                    return
                if amount <= 0:
                    await message.reply_text("❌ مقدار باید بیشتر از صفر باشد.")
                    return
                balance_pending.setdefault("items", []).append({"resource": balance_pending.pop("resource"), "amount": amount})
                context.user_data["balance_pending"] = balance_pending
                context.user_data[_waiting_scope_key("balance_pending")] = int(message.chat_id)
                session.commit()
                await message.reply_text(
                    "📦 مورد دریافت شد.\n\nبرای افزودن منبع دیگر روی «➕ ادامه» بزنید؛ اگر کارتان تمام شده «🏁 پایان» را بزنید.",
                    reply_markup=balance_continue_keyboard(balance_pending["sign"], balance_pending.get("back_action", "admin:users"))
                )
                return
            # تک‌نفره بعد از ID
            if balance_pending.get("mode") == "single" and not balance_pending.get("users"):
                target = _search_user_by_any(session, raw, get_users(session))
                if target is None:
                    await message.reply_text("❌ کاربری با این مشخصات پیدا نشد. آیدی، نام کاربری با @، شماره تلفن یا نام کشور را ارسال کنید.")
                    return
                target_id = int(target.telegram_id)
                balance_pending["pending_user_id"] = target_id
                balance_pending["users"] = [target_id]
                context.user_data["balance_selected_user"] = target_id
                context.user_data[_waiting_scope_key("balance_selected_user")] = int(message.chat_id)
                context.user_data["balance_pending"] = balance_pending
                context.user_data[_waiting_scope_key("balance_pending")] = int(message.chat_id)
                session.commit()
                countries=get_user_countries(session,target); default_country=get_default_country(session,target)
                role="👑 مالک" if is_owner(target.telegram_id,OWNER_ID) else ("🛡 ادمین" if is_admin(session,target.telegram_id,OWNER_ID) else "👤 کاربر عادی")
                profile=(f"🔎 <b>کاربر پیدا شد</b>\n\n👤 نام: <b>{escape(target.first_name or target.username or 'بدون نام')}</b>\n🆔 آیدی: <code>{target.telegram_id}</code>\n🔤 نام کاربری: {escape('@'+target.username if target.username else 'ثبت نشده')}\n📱 شماره: {escape(target.phone_number or 'ثبت نشده')}\n🎭 نقش: {role}\n🌍 کشور پیش‌فرض: {escape(default_country.title) if default_country else 'ثبت نشده'}\n🌎 تعداد کشورها: <b>{len(countries)}</b>\n\n")
                await message.reply_text(profile+"آیا این کاربر برای تغییر موجودی تأیید شود؟", parse_mode="HTML", reply_markup=user_search_confirm_keyboard(target_id, "admin:balance_change", "admin:balance_search_confirm:{user_id}"))
                return

        # دریافت نام کشور در فرآیند تأسیس اولیه
        if context.user_data.get(pending_key(user_tg.id)) is True and context.user_data.get("country_edit_waiting") and (message.text or "").strip():
            raw_name = normalize_country_name(message.text)
            if len(raw_name) < 2 or len(raw_name) > 40:
                await message.reply_text("❌ نام کشور باید بین ۲ تا ۴۰ کاراکتر باشد.")
                return
            if get_country_by_name(session, raw_name) is not None:
                await message.reply_text("❌ این نام کشور قبلاً انتخاب شده است.")
                return
            context.user_data[f"country_name_value_{user_tg.id}"] = raw_name
            context.user_data.pop("country_edit_waiting", None)
            await message.reply_text(
                f"🌍 نام کشور انتخابی: <b>{raw_name}</b>\n\nآیا تأیید می‌کنید؟",
                parse_mode="HTML",
                reply_markup=country_name_confirm_keyboard(),
            )
            return

        # دریافت نام جدید کشور در ویرایش مدیریتی یا شخصی
        if context.user_data.get("country_edit_waiting") and (message.text or "").strip():
            raw_name = normalize_country_name(message.text)
            if len(raw_name) < 2 or len(raw_name) > 40:
                await message.reply_text("❌ نام کشور باید بین ۲ تا ۴۰ کاراکتر باشد.")
                return
            if get_country_by_name(session, raw_name) is not None:
                await message.reply_text("❌ این نام کشور قبلاً انتخاب شده است.")
                return
            context.user_data["country_edit_name"] = raw_name
            context.user_data[_waiting_scope_key("country_edit_name")] = int(message.chat_id)
            context.user_data.pop("country_edit_waiting", None)
            await message.reply_text(f"🌍 نام جدید کشور: <b>{raw_name}</b>\n\nتأیید می‌کنید؟", parse_mode="HTML", reply_markup=country_edit_confirm_keyboard())
            return

        # دریافت نام جدید کشور توسط بازیکن
        if context.user_data.get("self_country_edit") and (message.text or "").strip():
            raw_name = normalize_country_name(message.text)
            if len(raw_name) < 2 or len(raw_name) > 40:
                await message.reply_text("❌ نام کشور باید بین ۲ تا ۴۰ کاراکتر باشد.")
                return
            if get_country_by_name(session, raw_name) is not None:
                await message.reply_text("❌ این نام کشور قبلاً انتخاب شده است.")
                return
            context.user_data["self_country_edit_name"] = raw_name
            context.user_data[_waiting_scope_key("self_country_edit_name")] = int(message.chat_id)
            await message.reply_text(f"🌍 نام جدید کشور: <b>{raw_name}</b>\n\nتأیید می‌کنید؟", parse_mode="HTML", reply_markup=country_edit_confirm_keyboard())
            return

        if normalized == command_key("کشور"):
            country = get_default_country(session, user)
            if country is None:
                await message.reply_text("❌ کشور پیش‌فرضی ندارید. ابتدا از تنظیمات بازی یک کشور پیش‌فرض انتخاب کنید.", reply_markup=command_keyboard(no_country=True))
            else:
                info_msg=await message.reply_text(country_status(country, get_metal_mine_config(session), __import__("services.economy",fromlist=["get_arsenal_config"]).get_arsenal_config(session), _country_shield_status(session, country)), parse_mode="HTML")
                _schedule_delete_after(context, message, info_msg)
            session.commit(); return

        if normalized in {command_key("چت و کانال"), command_key("💬 چت و کانال")}:
            # تبلیغات اجباریِ عضو‌شده و اختیاریِ پاداش‌گرفته دیگر نمایش داده نمی‌شوند.
            active=get_active_social_items(session)
            rows=[]

            for item in active:
                typ=item.get("type")
                url=social_item_button_url(item.get("url"))
                if not url: continue
                if typ == "panel":
                    rows.append([InlineKeyboardButton("🧩 پنل بازی", url=url)])
                elif typ == "mandatory_ad":
                    target=item.get("chat_id") or public_chat_target(item.get("url")) or private_message_link_chat_id(item.get("url"))
                    joined=False
                    if target:
                        try:
                            member=await context.bot.get_chat_member(target, user_tg.id)
                            status=getattr(member,"status","")
                            joined=status in {"member","administrator","creator"} or (status == "restricted" and bool(getattr(member,"is_member",False)))
                        except Exception:
                            joined=False
                    if not joined:
                        rows.append([InlineKeyboardButton("🚨 تبلیغ اجباری", url=url)])
                elif typ == "optional_ad" and not is_optional_claimed(session, user_tg.id, item.get("id")) and not is_optional_pending(session, user_tg.id, item.get("id")):
                    reward=float(item.get("reward",0) or 0)
                    rows.append([InlineKeyboardButton(f"🎁 تبلیغ اختیاری — ☢️ {reward:,.0f}", url=url)])

            # چت و کانال همیشه در این بخش هستند و تا حد امکان کنار هم قرار می‌گیرند.
            chats=[x for x in active if x.get("type")=="chat" and social_item_button_url(x.get("url"))]
            channels=[x for x in active if x.get("type")=="channel" and social_item_button_url(x.get("url"))]
            for i in range(max(len(chats),len(channels))):
                row=[]
                if i < len(chats):
                    row.append(InlineKeyboardButton("💬 چت بازی", url=social_item_button_url(chats[i].get("url"))))
                if i < len(channels):
                    row.append(InlineKeyboardButton("📣 کانال بازی", url=social_item_button_url(channels[i].get("url"))))
                if row: rows.append(row)


            if rows:
                await message.reply_text("<b>ارتباطات رسمی بازی</b>\n\nاز گزینه موردنظر وارد شوید:",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(rows))
            else:
                await message.reply_text("<b>ارتباطات رسمی بازی</b>\n\nهنوز مورد فعالی برای نمایش وجود ندارد.",parse_mode="HTML")
            return

        if normalized in {command_key("تنظیمات اکانت"), command_key("🪪 تنظیمات اکانت")}:
            target = user
            role = "👑 مالک ربات" if is_owner(target.telegram_id, OWNER_ID) else ("🛡️ مدیر" if is_admin(session, target.telegram_id, OWNER_ID) else "👤 بازیکن")
            # Telegram Bot API اطلاعات بیو و عکس پروفایل را از getChat / getUserProfilePhotos می‌دهد.
            bio = "ثبت نشده"
            photo_id = None
            try:
                chat_info = await context.bot.get_chat(target.telegram_id)
                bio = getattr(chat_info, "bio", None) or "ثبت نشده"
            except Exception:
                pass
            try:
                photos = await context.bot.get_user_profile_photos(target.telegram_id, limit=1)
                if photos.total_count and photos.photos:
                    photo_id = photos.photos[0][-1].file_id
            except Exception:
                pass
            created = target.created_at.strftime("%Y/%m/%d — %H:%M") if target.created_at else "ثبت نشده"
            last_active = target.last_active_at.strftime("%Y/%m/%d — %H:%M") if target.last_active_at else "ثبت نشده"
            username = ("@" + target.username) if target.username else "ثبت نشده"
            text = (
                "🪪 <b>پروفایل و اطلاعات اکانت</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"✨ نام: <b>{escape(str(target.first_name or 'بدون نام'))}</b>\n"
                f"🔤 نام کاربری: <b>{escape(username)}</b>\n"
                f"🆔 آیدی تلگرام: <code>{target.telegram_id}</code>\n"
                f"📱 شماره تلفن: <b>{escape(str(target.phone_number or 'ثبت نشده'))}</b>\n"
                f"📝 بیوگرافی: <b>{escape(str(bio))}</b>\n"
                f"🎭 نقش: <b>{role}</b>\n"
                f"📅 تاریخ عضویت در ربات: <b>{created}</b>\n"
                f"🕐 آخرین فعالیت ثبت‌شده: <b>{last_active}</b>\n"
                f"🚫 وضعیت حساب: <b>{'مسدود' if target.is_banned else 'فعال'}</b>\n"
                "━━━━━━━━━━━━━━━━━━"
            )
            if photo_id:
                await message.reply_photo(photo=photo_id, caption=text, parse_mode="HTML", reply_markup=page_back_keyboard())
            else:
                await message.reply_text(text, parse_mode="HTML", reply_markup=page_back_keyboard())
            return

        if normalized in {command_key("تنظیمات بازی"), command_key("🎮 تنظیمات بازی")}:
            await message.reply_text("🎮 <b>تنظیمات بازی</b>\n\nبخش موردنظر را انتخاب کنید:", parse_mode="HTML", reply_markup=game_settings_user_keyboard())
            await message.reply_text("🎮", reply_markup=page_back_keyboard())
            return

        # دستور ویرایش نام کشور
        if normalized in {command_key("ویرایش نام کشور"), command_key("🌍 ویرایش نام کشور")}:
            country = get_default_country(session, user)
            if not country:
                await message.reply_text("❌ هنوز کشور پیش‌فرضی ندارید.")
                return
            context.user_data["self_country_edit"] = True
            context.user_data[_waiting_scope_key("self_country_edit")] = int(message.chat_id)
            context.user_data["self_country_edit_name"] = None
            context.user_data[_waiting_scope_key("self_country_edit_name")] = int(message.chat_id)
            context.user_data["country_edit"] = {"target_user": user_tg.id, "country_id": country.id, "back": "main_menu"}
            context.user_data[_waiting_scope_key("country_edit")] = int(message.chat_id)
            await message.reply_text("💳 <b>هزینه تغییر نام کشور فعال است.</b>\nنام جدید را ارسال کنید.", parse_mode="HTML", reply_markup=country_edit_waiting_keyboard())
            return

        # دستور جابجایی کشورها
        if normalized in {command_key("جابجایی"), command_key("🔄 جابجایی")}:
            countries = get_user_countries(session, user)
            if len(countries) < 2:
                await message.reply_text("⚠️ برای جابجایی حداقل دو کشور لازم است. ابتدا در حداقل دو گروه کشور خودتان را تأسیس کنید.")
                return
            context.user_data["swap_pending"] = {"country_ids": [c.id for c in countries]}
            context.user_data[_waiting_scope_key("swap_pending")] = int(message.chat_id)
            session.commit()
            await message.reply_text("🔄 <b>کشور مبدأ را انتخاب کنید:</b>", parse_mode="HTML", reply_markup=swap_country_keyboard(countries))
            return

        if normalized in {command_key("فروشگاه"), command_key("🏪 فروشگاه"), command_key("🏪فروشگاه")}:
            context.user_data.pop("pending_exchange", None)
            context.user_data["store_nav"] = "store"
            context.user_data[_waiting_scope_key("store_nav")] = int(message.chat_id)
            await message.reply_text("🏪 <b>فروشگاه تسلیحات</b>\n\nبرای خرید، گزینه زیر را انتخاب کنید:", parse_mode="HTML", reply_markup=store_command_keyboard())
            session.commit(); return

        if normalized in {command_key("خرید سپر"), command_key("🛡️ خرید سپر")}:
            context.user_data["store_nav"] = "shield_types"
            context.user_data[_waiting_scope_key("store_nav")] = int(message.chat_id)
            await message.reply_text("🛡️ <b>خرید سپر</b>\n\nنوع سپر را انتخاب کنید:", parse_mode="HTML", reply_markup=shield_purchase_type_keyboard()); session.commit(); return

        # هر دو شکل قدیمی و جدید دکمه‌ها باید دقیقاً به همان مسیر خرید برسند.
        shield_type_map = {
            command_key("سپر جهانی"): "global",
            command_key("🛡️ سپر جهانی"): "global",
            command_key("خرید سپر جهانی"): "global",
            command_key("🛡️ خرید سپر جهانی"): "global",
            command_key("سپر قاره‌ای"): "continental",
            command_key("🛡️ سپر قاره‌ای"): "continental",
            command_key("خرید سپر قاره‌ای"): "continental",
            command_key("🛡️ خرید سپر قاره‌ای"): "continental",
        }
        if normalized in shield_type_map:
            typ=shield_type_map[normalized]
            items=get_shield_items(session,typ,active_only=True)
            context.user_data["store_nav"] = f"shield_list:{typ}"
            context.user_data[_waiting_scope_key("store_nav")] = int(message.chat_id)
            if not items:
                await message.reply_text(f"🔒 {'سپرهای جهانی' if typ=='global' else 'سپرهای قاره‌ای'} فعلاً در فروشگاه موجود نیست.", reply_markup=shield_purchase_type_keyboard()); session.commit(); return
            await message.reply_text(f"🛡️ <b>{'سپرهای جهانی' if typ=='global' else 'سپرهای قاره‌ای'}</b>\n\nسپر موردنظر را انتخاب کنید:", parse_mode="HTML", reply_markup=shield_purchase_list_keyboard(items,typ,1)); session.commit(); return

        if normalized in {command_key("خرید موشک"), command_key("🚀 خرید موشک")}:
            context.user_data["store_nav"] = "purchase_types"
            context.user_data[_waiting_scope_key("store_nav")] = int(message.chat_id)
            await message.reply_text("🚀 <b>خرید موشک</b>\n\nنوع موشک را انتخاب کنید:", parse_mode="HTML", reply_markup=missile_purchase_type_keyboard()); return

        missile_type_map = {
            command_key("خرید موشک کروز"): "کروز",
            command_key("🚀 خرید موشک کروز"): "کروز",
            command_key("خرید موشک بالستیک"): "بالستیک",
            command_key("🚀 خرید موشک بالستیک"): "بالستیک",
            command_key("خرید موشک هایپرسونیک"): "هایپرسونیک",
            command_key("⚡ خرید موشک هایپرسونیک"): "هایپرسونیک",
        }
        if normalized in missile_type_map:
            context.user_data["store_nav"] = "purchase_list"
            context.user_data[_waiting_scope_key("store_nav")] = int(message.chat_id)
            wanted = missile_type_map[normalized]
            # همه موشک‌های فعال این نوع نمایش داده می‌شوند؛ حتی اگر کشور هنوز شرایط باز کردن قفل را نداشته باشد.
            # موشک غیرفعال هرگز وارد فروشگاه نمی‌شود.
            country = get_default_country(session, user)
            raw_items = [m for m in get_missiles_config(session).get("items", []) if m.get("type") == wanted and bool(m.get("active", False))]
            items=[]
            current_hq=int(getattr(country, "command_center_level", 0) or 0) if country else 0
            current_arsenal=int(getattr(country, "arsenal_level", 0) or 0) if country else 0
            for m in raw_items:
                levels=m.get("levels") or {}
                tech_level = int(get_missile_tech_level(session, country.id, m.get("id"))) if country else 1
                tech_level = max(1, min(tech_level, int(m.get("max_level", 100) or 100)))
                level_data=levels.get(str(tech_level)) or levels.get("1") or {}
                hq_req=int(level_data.get("hq_required", m.get("hq_required", 1)) or 1)
                arsenal_req=int(level_data.get("arsenal_required", m.get("arsenal_required", 1)) or 1)
                item=dict(m)
                item["display_level"]=tech_level
                item["display_power"]=float(level_data.get("power", 0) or 0) or (float(m.get("base_power", 0) or 0) if tech_level == 1 else 0.0)
                item["display_capacity"]=float(m.get("base_capacity", 0) or 0)
                item["display_cost"]=float(level_data.get("cost", 0) or 0) or (float(m.get("base_cost", 0) or 0) if tech_level == 1 else 0.0)
                item["display_target_time"]=float(level_data.get("target_time", 0) or 0) or (float(m.get("base_target_time", 0) or 0) if tech_level == 1 else 0.0)
                item["hq_required"]=hq_req
                item["arsenal_required"]=arsenal_req
                item["locked"]=(current_hq < hq_req or current_arsenal < arsenal_req)
                items.append(item)
            if not items:
                await message.reply_text(f"🏪 <b>موشک‌های {wanted}</b>\n\nفعلاً موشک فعالی از این نوع در فروشگاه ثبت نشده است.", parse_mode="HTML", reply_markup=missile_purchase_type_keyboard())
            else:
                # مشخصات قدرت/ظرفیت/قیمت داخل پیام لیست نمایش داده می‌شود؛
                # دکمه‌ها فقط نام موشک و سطح را نشان می‌دهند.
                detail_lines=[]
                for item in items:
                    lock_mark=" 🔒" if item.get("locked") else ""
                    line = (
                        f"<b>{item.get('name','موشک')}</b>{lock_mark} — "
                        f"سطح {int(item.get('display_level',1))}\n"
                        f"🪖 قدرت: {float(item.get('display_power',0) or 0):,.0f}\n"
                        f"📦 ظرفیت: {float(item.get('display_capacity',0) or 0):,.0f}\n"
                        f"💰 قیمت: {float(item.get('display_cost',0) or 0):,.0f}\n"
                        f"⏱️ زمان رسیدن: {float(item.get('display_target_time',0) or 0):,.0f} ثانیه"
                    )
                    if item.get("locked"):
                        line += (
                            f"\n🔒 <b>شرایط باز شدن قفل:</b>"
                            f"\n🏛️ سطح مرکز فرماندهی لازم: <b>{int(item.get('hq_required',1))}</b>"
                            f"\n🏭 سطح زرادخانه لازم: <b>{int(item.get('arsenal_required',1))}</b>"
                        )
                    detail_lines.append(line)
                text=(f"╭━━━━━━━━━━━━━━━━━━━━╮\n🚀 <b>فروشگاه موشک‌های {wanted}</b>\n╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
                      "🛒 موشک موردنظر را برای خرید انتخاب کنید.\n\n"
                      + "\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(detail_lines)
                      + "\n\n━━━━━━━━━━━━━━━━━━━━")
                await message.reply_text(text, parse_mode="HTML", reply_markup=missile_purchase_list_keyboard(items))
            session.commit(); return

        # خرید یک موشک ثبت‌شده از فروشگاه
        cfg_for_purchase = get_missiles_config(session)
        missile = next((m for m in cfg_for_purchase.get("items",[])
                        if bool(m.get("active", False)) and (
                            command_key(str(m.get("name", ""))) == normalized
                            or normalized == command_key(str(m.get("name", "")) + " — سطح 1")
                            or normalized.startswith(command_key(str(m.get("name", "")) + " — سطح"))
                        )), None)
        if missile:
            raw_name = str(missile.get("name","موشک"))
            country=get_default_country(session,user)
            if not country:
                await message.reply_text("❌ ابتدا کشور پیش‌فرض خود را انتخاب کنید."); return
            if not bool(missile.get("active", False)):
                await message.reply_text("🔒 این موشک در حال حاضر غیرفعال است و قابل استفاده نیست."); return
            levels=missile.get("levels") or {}
            max_level=int(missile.get("max_level",100) or 100)
            purchase_level=max(1, min(get_missile_tech_level(session, country.id, missile.get("id")), max_level))
            level_data=levels.get(str(purchase_level)) or {}
            # فروشگاه باید دقیقاً از سطح فناوری فعلی کاربر استفاده کند؛
            # فقط برای سطح ۱ در صورت خالی بودن مقدار، مقدار پایه Owner fallback می‌شود.
            base_hq=int(missile.get("hq_required",1) or 1)
            base_arsenal=int(missile.get("arsenal_required",1) or 1)
            level_hq_required=int(level_data.get("hq_required", base_hq) or base_hq)
            level_arsenal_required=int(level_data.get("arsenal_required", base_arsenal) or base_arsenal)
            current_hq=int(getattr(country,"command_center_level",0) or 0)
            current_arsenal=int(getattr(country,"arsenal_level",0) or 0)
            if current_hq < level_hq_required or current_arsenal < level_arsenal_required:
                reasons=[]
                if current_hq < level_hq_required: reasons.append(f"🏛️ سطح مرکز فرماندهی لازم: {level_hq_required}")
                if current_arsenal < level_arsenal_required: reasons.append(f"🏭 سطح زرادخانه لازم: {level_arsenal_required}")
                await message.reply_text(f"🔒 سطح {purchase_level} این موشک قفل است.\n" + "\n".join(reasons)); return
            lvl1=level_data
            if current_arsenal <= 0:
                await message.reply_text("❌ زرادخانه کشور ساخته نشده است. ابتدا زرادخانه را بسازید."); return
            if current_hq < level_hq_required or current_arsenal < level_arsenal_required:
                reasons=[]
                if current_hq < level_hq_required: reasons.append(f"🏛️ سطح مرکز فرماندهی لازم برای سطح ۱: {level_hq_required}")
                if current_arsenal < level_arsenal_required: reasons.append(f"🏭 سطح زرادخانه لازم برای سطح ۱: {level_arsenal_required}")
                await message.reply_text("🔒 سطح این موشک قفل است.\n" + "\n".join(reasons)); return
            if purchase_level == 1:
                price=float(lvl1.get("cost", 0) or 0) or float(missile.get("base_cost",0) or 0)
                power=float(lvl1.get("power", 0) or 0) or float(missile.get("base_power",0) or 0)
                target_time=float(lvl1.get("target_time", 0) or 0) or float(missile.get("base_target_time",0) or 0)
            else:
                price=float(lvl1.get("cost", 0) or 0)
                power=float(lvl1.get("power", 0) or 0)
                target_time=float(lvl1.get("target_time", 0) or 0)
            cap=float(missile.get("base_capacity",0) or 0); arsenal_cap=0.0
            # ظرفیت واقعی را از موجودی محاسبه کن؛ مقدار قدیمی country.arsenal_storage قابل اعتماد نیست.
            _inv_reconciled, current, _total_count = _reconcile_arsenal_storage(session, country, cfg_for_purchase)
            if getattr(country,"arsenal_level",0)>0:
                from services.economy import get_arsenal_config
                acfg=get_arsenal_config(session); arsenal_cap=float((acfg.get("levels",{}).get(int(country.arsenal_level)) or {}).get("storage_capacity", acfg.get("build_storage_capacity",0)))
            if cap>0 and current+cap>arsenal_cap:
                await message.reply_text(f"❌ ظرفیت زرادخانه کافی نیست.\nفضای لازم: {cap:,.0f}\nفضای باقی‌مانده: {max(0,arsenal_cap-current):,.0f}"); return
            if not (getattr(country,"infinite_money",False) or float(country.money)>=price):
                await message.reply_text(f"❌ پول کافی نیست.\nکمبود: {max(0,price-float(country.money)):,.0f}"); return
            if not getattr(country,"infinite_money",False): country.money-=price
            country.arsenal_storage=current+cap
            country.missiles=int(getattr(country,"missiles",0))+1
            add_missile_to_inventory(session, country.id, missile.get("id"), level=purchase_level, amount=1)
            session.commit()
            # بعد از خرید، کاربر در همان صفحهٔ لیست موشک‌های همان نوع می‌ماند؛
            # بازگشت فقط با زدن دکمهٔ «🔙 برگشت» انجام می‌شود.
            context.user_data["store_nav"] = "purchase_list"
            context.user_data[_waiting_scope_key("store_nav")] = int(message.chat_id)
            wanted_type = str(missile.get("type", "")).strip()
            current_hq = int(getattr(country, "command_center_level", 0) or 0)
            current_arsenal = int(getattr(country, "arsenal_level", 0) or 0)
            page_items = []
            for m in cfg_for_purchase.get("items", []):
                if str(m.get("type", "")).strip() != wanted_type or not bool(m.get("active", False)):
                    continue
                levels = m.get("levels") or {}
                tech_level = int(get_missile_tech_level(session, country.id, m.get("id")))
                tech_level = max(1, min(tech_level, int(m.get("max_level", 100) or 100)))
                level_data = levels.get(str(tech_level)) or levels.get("1") or {}
                hq_req = int(level_data.get("hq_required", m.get("hq_required", 1)) or 1)
                arsenal_req = int(level_data.get("arsenal_required", m.get("arsenal_required", 1)) or 1)
                item = dict(m)
                item["display_level"] = tech_level
                item["display_power"] = float(level_data.get("power", 0) or 0) or (float(m.get("base_power", 0) or 0) if tech_level == 1 else 0.0)
                item["display_capacity"] = float(m.get("base_capacity", 0) or 0)
                item["display_cost"] = float(level_data.get("cost", 0) or 0) or (float(m.get("base_cost", 0) or 0) if tech_level == 1 else 0.0)
                item["display_target_time"] = float(level_data.get("target_time", 0) or 0) or (float(m.get("base_target_time", 0) or 0) if tech_level == 1 else 0.0)
                item["hq_required"] = hq_req
                item["arsenal_required"] = arsenal_req
                item["locked"] = current_hq < hq_req or current_arsenal < arsenal_req
                page_items.append(item)
            await message.reply_text(
                f"✅ موشک «{missile.get('name','موشک')}» خریداری شد و در زرادخانه قرار گرفت.\n"
                f"🔰 سطح: {purchase_level}\n💥 قدرت: {power:,.0f}\n📦 ظرفیت اشغال: {cap:,.0f}\n💰 قیمت: {price:,.0f}\n⏱️ زمان رسیدن: {target_time:,.0f} ثانیه\n\n"
                f"🚀 <b>موشک‌های {wanted_type}</b>\nموشک موردنظر را برای خرید انتخاب کنید:",
                parse_mode="HTML",
                reply_markup=missile_purchase_list_keyboard(page_items),
            )
            return
        exchange_commands = {
            "پولبهفلز": "money_to_metal",
            "💰پولبهفلز": "money_to_metal",
            "فلزبهپول": "metal_to_money",
            "🔩فلزبهپول": "metal_to_money",
            "پولبهسوخت": "money_to_fuel",
            "💰پولبهسوخت": "money_to_fuel",
            "سوختبهپول": "fuel_to_money",
            "⛽سوختبهپول": "fuel_to_money",
            "اورانیومبهسوخت": "uranium_to_fuel",
            "☢️اورانیومبهسوخت": "uranium_to_fuel",
            "اورانیومبهپول": "uranium_to_money",
            "☢️اورانیومبهپول": "uranium_to_money",
        }

        # هر دستور جدید، انتظار قبلی را قطع می‌کند.
        command_names = {command_key(x) for x in (set(TEXT_COMMAND_NAMES) | set(exchange_commands.keys()))}

        if context.user_data.get("pending_exchange") and normalized in command_names:
            context.user_data.pop("pending_exchange", None)

        # =====================================================
        # فروش تعداد دلخواه موشک از زرادخانه
        # =====================================================
        arsenal_custom = context.user_data.get("arsenal_sell_custom_pending")
        if arsenal_custom and (message.text or "").strip():
            raw_qty = _enigma_normalize_digits((message.text or "").strip()).replace(",", "").replace("٬", "").replace(" ", "")
            if not re.fullmatch(r"\d+", raw_qty):
                await message.reply_text("❌ فقط یک عدد صحیح وارد کنید.")
                return
            qty=int(raw_qty)
            country=get_default_country(session,user)
            if country is None:
                context.user_data.pop("arsenal_sell_custom_pending",None)
                await message.reply_text("❌ کشور پیش‌فرضی ندارید.")
                return
            mid=str(arsenal_custom.get("mid")); level=int(arsenal_custom.get("level",1))
            available=get_missile_count(get_missile_inventory(session,country.id),mid,level)
            if qty<=0:
                await message.reply_text("❌ تعداد باید بیشتر از صفر باشد.")
                return
            if qty>available:
                await message.reply_text(f"❌ این تعداد موجود نیست. حداکثر موجودی: <b>{available}</b> فروند",parse_mode="HTML")
                return
            cfg=get_missiles_config(session)
            missile=next((m for m in cfg.get("items",[]) if str(m.get("id"))==mid),None)
            if missile is None:
                context.user_data.pop("arsenal_sell_custom_pending",None)
                await message.reply_text("❌ موشک پیدا نشد.")
                return
            lvl=(missile.get("levels") or {}).get(str(level),{}) or {}
            price=float(lvl.get("cost",0) or 0) or float(missile.get("base_cost",0) or 0)
            refund=price/2
            context.user_data.pop("arsenal_sell_custom_pending",None)
            context.user_data["arsenal_sell_pending"]={"mid":mid,"level":level,"quantity":qty,"refund":refund,"name":str(missile.get("name","موشک"))}
            context.user_data[_waiting_scope_key("arsenal_sell_pending")] = int(message.chat_id)
            await message.reply_text(
                f"💰 <b>تأیید فروش</b>\n\n🚀 {escape(str(missile.get('name','موشک')))} — سطح {level}\n📦 تعداد فروش: <b>{qty}</b> فروند\n💵 دریافتی هر فروند: <b>{refund:,.0f}</b>\n💰 مجموع دریافتی: <b>{refund*qty:,.0f}</b>\n\nفروش این تعداد تأیید شود؟",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ تأیید فروش", callback_data="arsenal_sell_confirm")],
                    [InlineKeyboardButton("🔙 تغییر تعداد", callback_data="arsenal_sell_change_qty")],
                ])
            )
            return

        # اعمال مقدار تجربه رهبری روی چند کاربر منتخب
        leadership_bulk_apply = context.user_data.get("admin_leadership_bulk_pending")
        if leadership_bulk_apply and _waiting_scope_matches(context, "admin_leadership_bulk_pending", message.chat_id) and leadership_bulk_apply.get("mode") in {"add","sub"}:
            raw = _enigma_normalize_digits((message.text or "").strip()).replace(",","").replace("٬","").replace(" ","")
            try:
                value = float(raw)
                if value < 0: raise ValueError
            except Exception:
                await message.reply_text("❌ مقدار معتبر نیست. یک عدد مثبت ارسال کنید.")
                return
            changed=[]
            for uid in leadership_bulk_apply.get("user_ids",[]):
                target=get_user_by_telegram_id(session,int(uid))
                if not target: continue
                country=get_default_country(session,target)
                if country is None:
                    cs=get_user_countries(session,target); country=cs[0] if cs else None
                if not country or int(country.leader_user_id or 0)!=int(uid): continue
                old=float(country.leadership_experience or 0)
                delta=value if leadership_bulk_apply.get("mode")=="add" else -value
                country.leadership_experience=max(0.0,old+delta)
                changed.append((target,country,old,delta))
            session.commit(); context.user_data.pop("admin_leadership_bulk_pending",None)
            if not changed:
                await message.reply_text("❌ هیچ کشور معتبری برای تغییر پیدا نشد."); return
            lines=["✅ <b>تجربه رهبری کاربران تغییر کرد.</b>"]
            for target,country,old,delta in changed:
                lines.append(f"👤 {escape(target.first_name or target.username or str(target.telegram_id))} — 🌍 {escape(country.title)} — {old:,.0f} → {float(country.leadership_experience):,.0f}")
            await message.reply_text("\n".join(lines),parse_mode="HTML"); return

        # =====================================================
        # تنظیمات امنیت و پشتیبان‌گیری Owner
        # =====================================================
        social_pending=context.user_data.get("social_pending")
        if social_pending:
            raw=(message.text or "").strip(); field=social_pending.get("field")
            try:
                mode=social_pending.get("mode","legacy_edit")
                # محدودیت تعداد/زمان برای تبلیغ اجباری و اختیاری.
                if mode == "add" and social_pending.get("constraint_waiting"):
                    kind=social_pending.get("constraint_waiting")
                    value=_enigma_normalize_digits(raw).replace(",","").replace("٬","").replace(" ","")
                    if not re.fullmatch(r"\d+", value) or int(value) <= 0:
                        await message.reply_text("❌ مقدار باید یک عدد صحیح بزرگ‌تر از صفر باشد."); return
                    value=int(value)
                    if kind == "members":
                        social_pending["max_members"]=value
                        social_pending["limit_type"]="members"
                        social_pending.pop("constraint_waiting",None)
                        social_pending["constraint_stage"]="time"
                        context.user_data["social_pending"]=social_pending
                        context.user_data[_waiting_scope_key("social_pending")] = int(message.chat_id)
                        await message.reply_text("⏱️ <b>محدودیت زمانی را بفرستید</b>\n\nمدت فعال بودن تبلیغ را به دقیقه ارسال کنید:",parse_mode="HTML",reply_markup=social_time_constraint_keyboard()); return
                    social_pending["duration_minutes"]=value
                    social_pending["limit_type"]="time"
                    social_pending.pop("constraint_waiting",None)
                    social_pending["constraint_stage"]="done"
                    context.user_data["social_pending"]=social_pending
                    context.user_data[_waiting_scope_key("social_pending")] = int(message.chat_id)
                    d=social_pending.get("draft") or {}
                    await message.reply_text(_social_add_preview_text(social_pending,d),parse_mode="HTML",reply_markup=social_add_confirm_keyboard()); return

                # ویرایش لینک: هیچ تغییری تا تأیید Owner ذخیره نمی‌شود.
                if mode == "edit_item" and field in {"mandatory_ad","optional_ad","chat","channel","panel"}:
                    normalized_link=raw.strip()
                    if not (normalized_link.lower().startswith(("http://","https://","t.me/","telegram.me/")) or normalized_link.startswith("@")):
                        raise ValueError("link format")
                    target=public_chat_target(normalized_link)
                    target_chat=None
                    if target:
                        target_chat=await context.bot.get_chat(target)
                    else:
                        private_chat_id=private_message_link_chat_id(normalized_link)
                        if private_chat_id is not None:
                            target_chat=await context.bot.get_chat(private_chat_id)
                    if target_chat is None and not private_invite_link(normalized_link):
                        raise ValueError("link target")
                    # لینک دعوت خصوصی در بلوک بعدی با لینک پیام همان چت/کانال تأیید می‌شود.
                    if target_chat is not None and field in {"mandatory_ad","optional_ad","chat","channel"}:
                        bot_member=await context.bot.get_chat_member(target_chat.id,context.bot.id)
                        if getattr(bot_member,"status","") not in {"administrator","creator"}: raise ValueError("not admin")
                        if field=="channel" and getattr(target_chat,"type","")!="channel": raise ValueError("channel type")
                        if field=="chat" and getattr(target_chat,"type","") not in {"group","supergroup"}: raise ValueError("chat type")
                    social_pending["new_url"]=normalized_link
                    social_pending["new_chat_id"]=getattr(target_chat,"id",None)
                    social_pending["new_chat_type"]=getattr(target_chat,"type",None)
                    context.user_data["social_pending"]=social_pending
                    context.user_data[_waiting_scope_key("social_pending")] = int(message.chat_id)
                    update_social_item(session,social_pending.get("item_id"),url=normalized_link,chat_id=getattr(target_chat,"id",None),chat_type=getattr(target_chat,"type",None))
                    session.commit(); item_id=social_pending.get("item_id"); context.user_data.pop("social_pending",None)
                    await message.reply_text("✅ لینک با موفقیت ذخیره شد.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت",callback_data=f"owner:social_edit_item:{item_id}:menu")]])); return

                # لینک دعوت خصوصی: فقط لینک پیام همان چت/کانال کافی است؛ Forward لازم نیست.
                if mode in {"add","edit_item"} and field in {"mandatory_ad","optional_ad","chat","channel"}:
                    normalized_link=raw.strip()
                    if not (normalized_link.lower().startswith(("http://","https://","t.me/","telegram.me/")) or normalized_link.startswith("@")):
                        raise ValueError("link format")
                    # لینک t.me/c/... می‌تواند لینک پیام یک گروه عمومی هم باشد؛
                    # در این حالت نباید دوباره از Owner لینک پیام دیگری بخواهیم.
                    message_chat_id = private_message_link_chat_id(normalized_link)
                    if message_chat_id is not None:
                        target_chat = await context.bot.get_chat(message_chat_id)
                        bot_member = await context.bot.get_chat_member(target_chat.id, context.bot.id)
                        if getattr(bot_member,"status","") not in {"administrator","creator"}:
                            raise ValueError("not admin")
                        if field=="channel" and getattr(target_chat,"type","")!="channel": raise ValueError("channel type")
                        if field=="chat" and getattr(target_chat,"type","") not in {"group","supergroup"}: raise ValueError("chat type")
                        if mode=="add":
                            social_pending["draft"]={"link":normalized_link,"chat_id":target_chat.id,"chat_type":getattr(target_chat,"type",None),"reward":float(social_pending.get("pending_reward",0) or 0)}
                            social_pending.pop("pending_reward",None); context.user_data["social_pending"]=social_pending
                            context.user_data[_waiting_scope_key("social_pending")] = int(message.chat_id)
                            if field=="optional_ad":
                                social_pending["mode"]="reward_item"; context.user_data["social_pending"]=social_pending
                                context.user_data[_waiting_scope_key("social_pending")] = int(message.chat_id)
                                await message.reply_text("☢️ <b>پاداش تبلیغ اختیاری</b>\n\nمقدار اورانیوم را ارسال کنید:",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت",callback_data="owner:social_add")]])); return
                            if field=="mandatory_ad":
                                social_pending["constraint_stage"]="members"
                                context.user_data["social_pending"]=social_pending
                                context.user_data[_waiting_scope_key("social_pending")] = int(message.chat_id)
                                await message.reply_text("👥 <b>محدودیت اعضا را ارسال کنید</b>\n\nحداکثر تعداد کاربرانی که می‌توانند این تبلیغ را دریافت کنند را به‌صورت عدد بفرستید:",parse_mode="HTML",reply_markup=social_members_constraint_keyboard()); return
                            await message.reply_text("📋 <b>ثبت نهایی</b>\n\nلینک چت/کانال معتبر است و ربات ادمین آن است.\n\nبا تأیید Owner ثبت می‌شود.",parse_mode="HTML",reply_markup=social_add_confirm_keyboard()); return
                        update_social_item(session,social_pending.get("item_id"),url=normalized_link,chat_id=target_chat.id,chat_type=getattr(target_chat,"type",None)); session.commit(); context.user_data.pop("social_pending",None)
                        await message.reply_text("✅ لینک پیام معتبر است و مورد به‌روزرسانی شد.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت",callback_data="owner:social_list")]])); return

                    if private_invite_link(normalized_link):
                        context.user_data["social_pending"]={"mode":"private_verify","field":field,"item_id":social_pending.get("item_id"),"link":normalized_link,"original_mode":mode}
                        context.user_data[_waiting_scope_key("social_pending")] = int(message.chat_id)
                        back_cb="owner:social_add" if mode=="add" else f"owner:social_edit_item:{social_pending.get('item_id')}:menu"
                        await message.reply_text("🔐 <b>لینک خصوصی دریافت شد.</b>\n\nحالا فقط <b>لینک یکی از پیام‌های همان گروه/کانال</b> را کپی کنید و همین‌جا بفرستید.\n❗ نیازی به Forward نیست.\n\nربات سپس ادمین بودن خودش را بررسی می‌کند.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت",callback_data=back_cb)]])); return

                if mode == "private_verify":
                    message_chat_id=private_message_link_chat_id(raw)
                    if message_chat_id is not None:
                        target_chat=await context.bot.get_chat(message_chat_id)
                    else:
                        # برای کانال/گروه عمومی که لینک دعوتِ خصوصی دارد،
                        # لینک پیام عمومی مثل https://t.me/ChannelName/25
                        # نیز باید به‌عنوان اثبات همان چت پذیرفته شود.
                        public_target=public_chat_target(raw)
                        if not public_target:
                            await message.reply_text("❌ لینک پیام معتبر نیست. نمونه: https://t.me/ChannelName/25 یا https://t.me/c/123456789/25"); return
                        target_chat=await context.bot.get_chat(public_target)
                    bot_member=await context.bot.get_chat_member(target_chat.id, context.bot.id)
                    if getattr(bot_member,"status","") not in {"administrator","creator"}:
                        await message.reply_text("❌ ربات در این چت/کانال ادمین نیست. ابتدا ربات را ادمین کنید."); return
                    if field=="channel" and getattr(target_chat,"type","")!="channel":
                        await message.reply_text("❌ برای کانال بازی باید لینک پیام یک کانال را بفرستید."); return
                    if field=="chat" and getattr(target_chat,"type","") not in {"group","supergroup"}:
                        await message.reply_text("❌ برای چت بازی باید لینک پیام یک گروه/سوپرگروه را بفرستید."); return
                    if social_pending.get("original_mode")=="add":
                        social_pending={"mode":"add","field":field,"draft":{"link":social_pending.get("link"),"chat_id":target_chat.id,"chat_type":getattr(target_chat,"type",None)}}
                        context.user_data["social_pending"]=social_pending
                        context.user_data[_waiting_scope_key("social_pending")] = int(message.chat_id)
                        if field=="optional_ad":
                            context.user_data["social_pending"]["mode"]="reward_item"
                            await message.reply_text("☢️ <b>پاداش تبلیغ اختیاری</b>\n\nمقدار اورانیوم را ارسال کنید:",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت",callback_data="owner:social_add")]])); return
                        if field=="mandatory_ad":
                            social_pending["constraint_stage"]="members"
                            context.user_data["social_pending"]=social_pending
                            context.user_data[_waiting_scope_key("social_pending")] = int(message.chat_id)
                            await message.reply_text("👥 <b>محدودیت اعضا را ارسال کنید</b>\n\nحداکثر تعداد کاربرانی که می‌توانند این تبلیغ را دریافت کنند را به‌صورت عدد بفرستید:",parse_mode="HTML",reply_markup=social_members_constraint_keyboard()); return
                        await message.reply_text("📋 <b>ثبت نهایی</b>\n\nربات ادمین بودنش را تأیید کرد.\n\nبا تأیید Owner این مورد ثبت می‌شود.",parse_mode="HTML",reply_markup=social_add_confirm_keyboard()); return
                    item_id=social_pending.get("item_id")
                    update_social_item(session,item_id,url=social_pending.get("link"),chat_id=target_chat.id,chat_type=getattr(target_chat,"type",None)); session.commit(); context.user_data.pop("social_pending",None)
                    await message.reply_text("✅ لینک خصوصی ذخیره شد.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت",callback_data=f"owner:social_edit_item:{item_id}:menu")]])); return

                if mode == "add_edit_members":
                    value_raw=_enigma_normalize_digits(raw).replace(",","").replace("٬","").replace(" ","")
                    if not re.fullmatch(r"\d+", value_raw) or int(value_raw) <= 0:
                        await message.reply_text("❌ محدودیت اعضا باید یک عدد صحیح بزرگ‌تر از صفر باشد."); return
                    pending=context.user_data.get("social_pending") or {}; pending["max_members"]=int(value_raw); pending["limit_type"]="members"; pending["mode"]="add"; pending.pop("constraint_waiting",None); context.user_data["social_pending"]=pending
                    context.user_data[_waiting_scope_key("social_pending")] = int(message.chat_id)
                    from keyboards.admin import social_add_edit_keyboard
                    await message.reply_text("✅ محدودیت کاربر تغییر کرد.",parse_mode="HTML",reply_markup=social_add_edit_keyboard(pending)); return

                if mode == "add_edit_time":
                    value_raw=_enigma_normalize_digits(raw).replace(",","").replace("٬","").replace(" ","")
                    if not re.fullmatch(r"\d+", value_raw) or int(value_raw) <= 0:
                        await message.reply_text("❌ محدودیت زمانی باید یک عدد صحیح بزرگ‌تر از صفر باشد."); return
                    pending=context.user_data.get("social_pending") or {}; pending["duration_minutes"]=int(value_raw); pending["limit_type"]="time"; pending["mode"]="add"; pending.pop("constraint_waiting",None); context.user_data["social_pending"]=pending
                    context.user_data[_waiting_scope_key("social_pending")] = int(message.chat_id)
                    from keyboards.admin import social_add_edit_keyboard
                    await message.reply_text("✅ محدودیت زمان تغییر کرد.",parse_mode="HTML",reply_markup=social_add_edit_keyboard(pending)); return

                if mode == "edit_members":
                    value_raw=_enigma_normalize_digits(raw).replace(",","").replace("٬","").replace(" ","")
                    if not re.fullmatch(r"\d+", value_raw) or int(value_raw) <= 0:
                        await message.reply_text("❌ محدودیت اعضا باید یک عدد صحیح بزرگ‌تر از صفر باشد."); return
                    item_id=social_pending.get('item_id'); item=next((x for x in get_social_items(session) if str(x.get('id'))==str(item_id)),None)
                    if not item: raise ValueError
                    item["max_members"]=int(value_raw); item["limit_type"]="members"; _save_items(session,get_social_items(session)); session.commit(); context.user_data.pop("social_pending",None)
                    await message.reply_text("✅ محدودیت کاربر ذخیره شد.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت",callback_data=f"owner:social_edit_item:{item_id}:menu")]])); return

                if mode == "edit_time":
                    value_raw=_enigma_normalize_digits(raw).replace(",","").replace("٬","").replace(" ","")
                    if not re.fullmatch(r"\d+", value_raw) or int(value_raw) <= 0:
                        await message.reply_text("❌ محدودیت زمانی باید یک عدد صحیح بزرگ‌تر از صفر و برحسب دقیقه باشد."); return
                    item_id=social_pending.get('item_id'); item=next((x for x in get_social_items(session) if str(x.get('id'))==str(item_id)),None)
                    if not item: raise ValueError
                    item["expires_at"]=(datetime.now(timezone.utc)+timedelta(minutes=int(value_raw))).isoformat(); item["limit_type"]="time"; _save_items(session,get_social_items(session)); session.commit(); context.user_data.pop("social_pending",None)
                    await message.reply_text("✅ محدودیت زمان ذخیره شد.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت",callback_data=f"owner:social_edit_item:{item_id}:menu")]])); return

                if mode == "edit_delay":
                    value_raw=_enigma_normalize_digits(raw).replace(",","").replace("٬","").replace(" ","")
                    if not re.fullmatch(r"\d+", value_raw) or int(value_raw) <= 0:
                        await message.reply_text("❌ زمان باید یک عدد صحیح بزرگ‌تر از صفر و برحسب دقیقه باشد."); return
                    item_id=social_pending.get('item_id'); item=next((x for x in get_social_items(session) if str(x.get('id'))==str(item_id)),None)
                    if not item: raise ValueError
                    item["reward_delay_minutes"]=int(value_raw); _save_items(session,get_social_items(session)); session.commit(); context.user_data.pop("social_pending",None)
                    await message.reply_text("✅ زمان دریافت پاداش ذخیره شد.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت",callback_data=f"owner:social_edit_item:{item_id}:menu")]])); return

                if mode == "edit_reward":
                    rawn=_enigma_normalize_digits(raw).replace(",","").replace("٬","").replace(" ","")
                    if not re.fullmatch(r"\d+(?:[.]\d+)?",rawn): raise ValueError
                    item_id=social_pending.get('item_id'); item=next((x for x in get_social_items(session) if str(x.get('id'))==str(item_id)),None)
                    if not item: raise ValueError
                    item["reward"]=max(0,float(rawn)); _save_items(session,get_social_items(session)); session.commit(); context.user_data.pop("social_pending",None)
                    await message.reply_text("✅ پاداش ذخیره شد.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت",callback_data=f"owner:social_edit_item:{item_id}:menu")]])); return

                if mode == "reward_item":
                    rawn=_enigma_normalize_digits(raw).replace(",","").replace("٬","").replace(" ","")
                    if not re.fullmatch(r"\d+(?:[.]\d+)?",rawn): raise ValueError
                    if social_pending.get("item_id"):
                        item_id=social_pending.get("item_id"); item=next((x for x in get_social_items(session) if str(x.get("id"))==str(item_id)),None)
                        if not item: raise ValueError
                        item["reward"]=max(0,float(rawn)); _save_items(session,get_social_items(session)); session.commit(); context.user_data.pop("social_pending",None)
                        from keyboards.admin import owner_social_edit_keyboard
                        await message.reply_text("✅ پاداش ذخیره شد.",parse_mode="HTML",reply_markup=owner_social_edit_keyboard(item_id,item.get("type"))); return
                    social_pending["pending_reward"]=max(0,float(rawn))
                    draft=social_pending.get("draft") or {}
                    draft["reward"]=social_pending["pending_reward"]
                    social_pending["draft"]=draft
                    social_pending["mode"]="reward_delay_wait"
                    context.user_data["social_pending"]=social_pending
                    context.user_data[_waiting_scope_key("social_pending")] = int(message.chat_id)
                    await message.reply_text("⏳ <b>زمان دریافت پاداش</b>\n\nمدت عضویت لازم تا دریافت پاداش را به دقیقه ارسال کنید.\nمثلاً 60 برای یک ساعت.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت",callback_data="owner:social_reward_back")]])); return

                if mode == "reward_delay_wait":
                    value_raw=_enigma_normalize_digits(raw).replace(",","").replace("٬","").replace(" ","")
                    if not re.fullmatch(r"\d+", value_raw) or int(value_raw) <= 0:
                        await message.reply_text("❌ زمان باید یک عدد صحیح بزرگ‌تر از صفر و برحسب دقیقه باشد."); return
                    social_pending["reward_delay_minutes"]=int(value_raw)
                    social_pending["mode"]="add"
                    social_pending["constraint_stage"]="members"
                    context.user_data["social_pending"]=social_pending
                    context.user_data[_waiting_scope_key("social_pending")] = int(message.chat_id)
                    await message.reply_text("⚙️ <b>نوع محدودیت تبلیغ اختیاری را انتخاب کنید:</b>",parse_mode="HTML",reply_markup=social_constraint_keyboard()); return

                if mode == "add":
                    normalized_link=raw.strip()
                    if not (normalized_link.lower().startswith(("http://","https://","t.me/","telegram.me/")) or normalized_link.startswith("@")):
                        raise ValueError("link format")
                    target=public_chat_target(normalized_link)
                    target_chat=None
                    if target:
                        target_chat=await context.bot.get_chat(target)
                    else:
                        private_chat_id=private_message_link_chat_id(normalized_link)
                        if private_chat_id is not None:
                            target_chat=await context.bot.get_chat(private_chat_id)
                        else:
                            raise ValueError("private link")
                    bot_member=await context.bot.get_chat_member(target_chat.id,context.bot.id)
                    if getattr(bot_member,"status","") not in {"administrator","creator"}: raise ValueError("not admin")
                    if field=="channel" and getattr(target_chat,"type","")!="channel": raise ValueError("channel type")
                    if field=="chat" and getattr(target_chat,"type","") not in {"group","supergroup"}: raise ValueError("chat type")
                    social_pending["draft"]={"link":normalized_link,"chat_id":target_chat.id,"chat_type":getattr(target_chat,"type",None),"reward":float(social_pending.get("pending_reward",0) or 0)}
                    social_pending.pop("pending_reward",None)
                    context.user_data["social_pending"]=social_pending
                    context.user_data[_waiting_scope_key("social_pending")] = int(message.chat_id)
                    if field=="optional_ad":
                        social_pending["mode"]="optional_reward_wait"
                        context.user_data["social_pending"]=social_pending
                        context.user_data[_waiting_scope_key("social_pending")] = int(message.chat_id)
                        social_pending["mode"]="reward_item"; context.user_data["social_pending"]=social_pending
                        context.user_data[_waiting_scope_key("social_pending")] = int(message.chat_id)
                        await message.reply_text("☢️ <b>پاداش تبلیغ اختیاری</b>\n\nمقدار اورانیوم را ارسال کنید:",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت",callback_data="owner:social_add")]])); return
                    if field=="mandatory_ad":
                        social_pending["constraint_stage"]="members"
                        context.user_data["social_pending"]=social_pending
                        context.user_data[_waiting_scope_key("social_pending")] = int(message.chat_id)
                        await message.reply_text("👥 <b>محدودیت اعضا را ارسال کنید</b>\n\nحداکثر تعداد کاربرانی که می‌توانند این تبلیغ را دریافت کنند را به‌صورت عدد بفرستید:",parse_mode="HTML",reply_markup=social_members_constraint_keyboard()); return
                    await message.reply_text("📋 <b>ثبت نهایی</b>\n\nربات ادمین بودنش را تأیید کرد.\n\nبا تأیید Owner این مورد ثبت می‌شود.",parse_mode="HTML",reply_markup=social_add_confirm_keyboard()); return

                if mode == "legacy_edit":
                    if field=="optional_ad_reward":
                        rawn=_enigma_normalize_digits(raw).replace(",","").replace("٬","").replace(" ","")
                        if not re.fullmatch(r"\d+",rawn): raise ValueError
                        set_social_value(session,field,str(max(0,int(rawn))))
                    else:
                        set_social_value(session,field,raw)
                    session.commit(); context.user_data.pop("social_pending",None)
                    await message.reply_text("✅ مقدار با موفقیت ذخیره شد.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت",callback_data="owner:social_links")]])); return
            except Exception:
                await message.reply_text("❌ لینک قابل شناسایی نیست یا ربات ادمین آن چت/کانال نیست. برای لینک خصوصی، لینک یکی از پیام‌های همان چت/کانال را کپی و ارسال کنید."); return

        security_pending = context.user_data.get("security_pending")
        if security_pending:
            raw_input = _enigma_normalize_digits((message.text or "").strip()).replace(",", "").replace("٬", "").replace(" ", "")
            field = security_pending.get("field")
            try:
                if field == "backup_execution_time":
                    # هم «13» و هم «13:00» معتبرند؛ عدد تنها یعنی ساعت 13:00.
                    raw_time = (raw_input.replace("：", ":").replace("٫", ":")
                                .replace("∶", ":").replace("﹕", ":").replace("؛", ":"))
                    if re.fullmatch(r"\d{1,2}", raw_time):
                        hh, mm = int(raw_time), 0
                    elif re.fullmatch(r"\d{1,2}:\d{1,2}", raw_time):
                        hh, mm = map(int, raw_time.split(":", 1))
                    else:
                        raise ValueError
                    if not (0 <= hh <= 23 and 0 <= mm <= 59): raise ValueError
                    set_backup_execution_time(session, f"{hh:02d}:{mm:02d}")
                    session.flush()
                else:
                    raw_num = raw_input
                    if not re.fullmatch(r"\d+", raw_num): raise ValueError
                    value = int(raw_num)
                if field == "user_max": set_anti_spam_user_max(session, value)
                elif field == "user_window": set_anti_spam_user_window(session, value)
                elif field == "group_max": set_anti_spam_group_max(session, value)
                elif field == "group_window": set_anti_spam_group_window(session, value)
                elif field == "backup_interval": set_backup_interval(session, value)
                elif field == "backup_execution_time":
                    pass
                else: raise ValueError
                session.commit(); context.user_data.pop("security_pending", None)
                back = "owner:security_anti" if field in {"user_max", "user_window", "group_max", "group_window"} else "owner:security_backup"
                # بعد از ثبت مقدار، همان پنل قبلی به‌روز می‌شود تا یک پیامِ جدا با دکمه‌های پنل ایجاد نشود.
                if field in {"user_max", "user_window", "group_max", "group_window"} and security_pending.get("chat_id") and security_pending.get("message_id"):
                    try:
                        await context.bot.edit_message_text(
                            chat_id=int(security_pending["chat_id"]),
                            message_id=int(security_pending["message_id"]),
                            text=owner_anti_spam_panel_text(session),
                            parse_mode="HTML",
                            reply_markup=owner_anti_spam_keyboard(session),
                        )
                        return
                    except Exception:
                        pass
                if field in {"backup_interval", "backup_execution_time"} and security_pending.get("chat_id") and security_pending.get("message_id"):
                    try:
                        await context.bot.edit_message_text(
                            chat_id=int(security_pending["chat_id"]),
                            message_id=int(security_pending["message_id"]),
                            text=owner_backup_panel_text(session),
                            parse_mode="HTML",
                            reply_markup=owner_backup_keyboard(session),
                        )
                        return
                    except Exception:
                        pass
                await message.reply_text("✅ مقدار با موفقیت ذخیره شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data=back)]])); return
            except Exception:
                back = "owner:security_anti" if field in {"user_max", "user_window", "group_max", "group_window"} else "owner:security_backup"
                await message.reply_text("❌ مقدار نامعتبر است. ساعت را به شکل 13 یا 13:00 ارسال کنید.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data=back)]])); return

        # =====================================================
        # انیگما Owner input / mission bank management
        # =====================================================
        enigma_pending = context.user_data.get("enigma_pending")
        if enigma_pending:
            raw = (message.text or "").strip()
            kind = enigma_pending.get("kind")

            # ---------------- تنظیمات عمومی ----------------
            if kind == "config":
                cfg = enigma_ensure_settings(session)
                key = enigma_pending["key"]
                try:
                    if key in {"weekly_per_country", "min_gap_hours", "box_expiry_minutes", "expiry_minutes", "max_attempts", "operation_seconds"}:
                        value = _enigma_parse_int(raw)
                    else:
                        value = _enigma_parse_number(raw)
                    if value < 0:
                        raise ValueError
                except Exception:
                    await message.reply_text(
                        "❌ مقدار نامعتبر است. فقط یک عدد معتبر ارسال کنید.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="owner:enigma_settings")]])
                    ); return
                cfg[key] = value
                enigma_set_setting(session, "config", cfg)
                context.user_data.pop("enigma_pending", None)
                await message.reply_text(
                    f"✅ ذخیره شد. مقدار جدید: <b>{value}</b>", parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="owner:enigma_settings")]])
                ); return

            # ---------------- ساعت ارسال: کاملاً دو مرحله‌ای ----------------
            if kind == "hours":
                stage = enigma_pending.get("stage", "min")
                try:
                    # پذیرش ساعت به‌صورت 12، 12:30، ۱۲، ۱۲:۳۰ و با فاصله/دو نقطهٔ عربی
                    value = _enigma_normalize_digits(raw or "")
                    value = value.replace("：", ":").replace("﹕", ":").replace("∶", ":")
                    value = value.strip().replace(" ", "")
                    if ":" in value:
                        hh, mm = value.split(":", 1)
                        if not hh or not mm:
                            raise ValueError
                        h, m = _enigma_parse_int(hh), _enigma_parse_int(mm)
                    else:
                        h, m = _enigma_parse_int(value), 0
                    if not (0 <= h <= 23 and 0 <= m <= 59):
                        raise ValueError
                    normalized_hour = f"{h:02d}:{m:02d}"
                    cfg = enigma_ensure_settings(session)
                    if stage == "min":
                        enigma_pending.update({"stage": "max", "min_hour": normalized_hour})
                        context.user_data["enigma_pending"] = enigma_pending
                        context.user_data[_waiting_scope_key("enigma_pending")] = int(message.chat_id)
                        await message.reply_text(
                            f"🕐 <b>ساعت حداقل ثبت شد</b>\n\nحداقل جدید: <b>{normalized_hour}</b>\n\n"
                            "<b>مرحله ۲ از ۲</b>\nحالا فقط ساعت حداکثر را ارسال کنید.",
                            parse_mode="HTML",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="owner:enigma_settings")]])
                        ); return
                    min_hour = enigma_pending.get("min_hour", cfg.get("min_hour", "10:00"))
                    def minutes(x):
                        hh, mm = map(int, x.split(":")); return hh * 60 + mm
                    if minutes(normalized_hour) < minutes(min_hour):
                        await message.reply_text(
                            "❌ ساعت حداکثر نمی‌تواند قبل از ساعت حداقل باشد. دوباره فقط ساعت حداکثر را ارسال کنید.",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="owner:enigma_settings")]])
                        ); return
                    cfg["min_hour"], cfg["max_hour"] = min_hour, normalized_hour
                    enigma_set_setting(session, "config", cfg)
                    context.user_data.pop("enigma_pending", None)
                    await message.reply_text(
                        f"✅ بازه ساعت ذخیره شد.\n\nحداقل: <b>{min_hour}</b>\nحداکثر: <b>{normalized_hour}</b>",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="owner:enigma_settings")]])
                    ); return
                except Exception:
                    prompt = "ساعت حداقل" if stage == "min" else "ساعت حداکثر"
                    await message.reply_text(
                        f"❌ {prompt} نامعتبر است. فقط ساعت 00 تا 23 یا قالب ساعت:دقیقه مثل <code>10:30</code> را ارسال کنید.",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="owner:enigma_settings")]])
                    ); return

            # ---------------- تعداد تلاش ----------------
            if kind == "attempts":
                cfg = enigma_ensure_settings(session)
                try:
                    cfg["max_attempts"] = max(1, _enigma_parse_int(raw))
                except Exception:
                    await message.reply_text(
                        "❌ مقدار نامعتبر است. فقط یک عدد معتبر ارسال کنید.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="owner:enigma_attempts")]])
                    ); return
                enigma_set_setting(session, "config", cfg)
                context.user_data.pop("enigma_pending", None)
                await message.reply_text("✅ تعداد تلاش ذخیره شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="owner:enigma_attempts")]])); return

            # ---------------- سطح و نوع چالش ----------------
            if kind in {"level", "type", "type_level"}:
                cfg = enigma_ensure_settings(session)
                if kind == "level":
                    section = cfg["levels"]; obj = section[enigma_pending["level"]]
                elif kind == "type":
                    section = cfg["types"]; obj = section[enigma_pending["type"]]
                else:
                    section = cfg["types"][enigma_pending["type"]]["levels"]; obj = section[enigma_pending["level"]]
                field = enigma_pending["field"]
                try:
                    proposed = _enigma_parse_number(raw) if field in {"weight", "speed_factor"} else _enigma_parse_int(raw)
                    if proposed < (1 if field == "operation_seconds" else 0):
                        raise ValueError
                except Exception:
                    if kind == "level": back=f"owner:enigma_level:{enigma_pending['level']}"
                    elif kind == "type": back=f"owner:enigma_type:{enigma_pending['type']}"
                    else: back=f"owner:enigma_type_level:{enigma_pending['type']}:{enigma_pending['level']}"
                    await message.reply_text("❌ مقدار نامعتبر است. فقط یک عدد معتبر ارسال کنید.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data=back)]])); return
                enigma_pending["proposed_value"] = proposed
                context.user_data["enigma_pending"] = enigma_pending
                context.user_data[_waiting_scope_key("enigma_pending")] = int(message.chat_id)
                if kind == "level": back=f"owner:enigma_level:{enigma_pending['level']}"
                elif kind == "type": back=f"owner:enigma_type:{enigma_pending['type']}"
                else: back=f"owner:enigma_type_level:{enigma_pending['type']}:{enigma_pending['level']}"
                await message.reply_text(
                    f"✏️ <b>مقدار جدید</b>\n\nمقدار فعلی: <b>{enigma_pending.get('current')}</b>\nمقدار جدید: <b>{proposed:g}</b>\n\nآیا این مقدار تأیید شود؟",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ تأیید", callback_data="owner:enigma_value_confirm")],
                        [InlineKeyboardButton("✏️ ویرایش", callback_data="owner:enigma_value_edit")],
                        [InlineKeyboardButton("🔙 برگشت", callback_data="owner:enigma_value_cancel")],
                    ])
                ); return

            # ---------------- افزودن مأموریت: هر مقدار در یک مرحله ----------------
            if kind == "mission_add":
                data = enigma_pending.setdefault("data", {})
                stage = enigma_pending.get("stage", "type")
                valid_types = {"letter_shift", "morse", "memory_multi", "memory_text"}
                if stage == "type":
                    if raw not in valid_types:
                        await message.reply_text("❌ نوع نامعتبر است. نوع مأموریت را با دکمه‌های شیشه‌ای انتخاب کنید.", reply_markup=__import__('enigma.keyboards',fromlist=['owner_mission_type_keyboard']).owner_mission_type_keyboard()); return
                    data["type"] = raw; enigma_pending["stage"] = "level"; context.user_data["enigma_pending"] = enigma_pending
                    context.user_data[_waiting_scope_key("enigma_pending")] = int(message.chat_id)
                    await message.reply_text("<b>مرحله ۲ از ۵</b>\nسطح مأموریت را با دکمه‌های شیشه‌ای انتخاب کنید.", parse_mode="HTML", reply_markup=__import__('enigma.keyboards',fromlist=['owner_mission_level_keyboard']).owner_mission_level_keyboard()); return
                if stage == "level":
                    if raw not in {"easy","medium","hard"}:
                        await message.reply_text("❌ سطح نامعتبر است. سطح را با دکمه‌های شیشه‌ای انتخاب کنید.", reply_markup=__import__('enigma.keyboards',fromlist=['owner_mission_level_keyboard']).owner_mission_level_keyboard()); return
                    data["level"] = raw; enigma_pending["stage"] = "prompt"; context.user_data["enigma_pending"] = enigma_pending
                    context.user_data[_waiting_scope_key("enigma_pending")] = int(message.chat_id)
                    await message.reply_text("<b>مرحله ۳ از ۵</b>\nمتن چالش را جداگانه ارسال کنید.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="owner:enigma_bank")]])); return
                if stage == "prompt":
                    if not raw:
                        await message.reply_text("❌ متن چالش نمی‌تواند خالی باشد."); return
                    data["prompt"] = raw; enigma_pending["stage"] = "answer"; context.user_data["enigma_pending"] = enigma_pending
                    context.user_data[_waiting_scope_key("enigma_pending")] = int(message.chat_id)
                    await message.reply_text("<b>مرحله ۴ از ۵</b>\nپاسخ صحیح را جداگانه ارسال کنید.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="owner:enigma_bank")]])); return
                if stage == "answer":
                    answer = raw.upper()
                    import re as _re
                    if not _re.fullmatch(r"[A-Z0-9 ]+", answer):
                        await message.reply_text("❌ پاسخ نامعتبر است. فقط حروف بزرگ و اعداد را وارد کنید."); return
                    data["answer"] = answer; enigma_pending["stage"] = "hint"; context.user_data["enigma_pending"] = enigma_pending
                    context.user_data[_waiting_scope_key("enigma_pending")] = int(message.chat_id)
                    await message.reply_text("<b>مرحله ۵ از ۵</b>\nراهنمایی مأموریت را جداگانه ارسال کنید. اگر راهنمایی نمی‌خواهید، یک خط تیره ارسال کنید.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="owner:enigma_bank")]])); return
                if stage == "hint":
                    data["hint"] = "" if raw == "-" else raw
                    from enigma.challenges import ensure_missions
                    missions = ensure_missions(session)
                    ids = [int(x.get("id", 0)) for x in missions if x.get("type") == data["type"]]
                    mid = max(ids or [0]) + 1
                    missions.append({"id":mid,"type":data["type"],"level":data["level"],"prompt":data["prompt"],"answer":data["answer"],"hint":data.get("hint", ""),"enabled":True})
                    enigma_set_setting(session, "missions", missions)
                    context.user_data.pop("enigma_pending", None)
                    names={"letter_shift":"جابه‌جایی حروف","morse":"مورس","memory_multi":"حفظ چند اطلاعات","memory_text":"حفظ اطلاعات در متن"}
                    levels={"easy":"آسان","medium":"متوسط","hard":"سخت"}
                    await message.reply_text(f"✅ مأموریت {mid} اضافه شد.\nنوع: {names[data['type']]}\nسطح: {levels[data['level']]}\n☢️ جایزه بر اساس تنظیمات همین سطح محاسبه می‌شود.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="owner:enigma_bank")]])); return

            # ---------------- ویرایش مأموریت ----------------
            if kind == "mission_edit":
                from enigma.challenges import ensure_missions
                data=ensure_missions(session)
                typ=enigma_pending.get('type'); mid=int(enigma_pending.get('id',0)); field=enigma_pending.get('field')
                m=next((x for x in data if x.get('type')==typ and int(x.get('id',0))==mid),None)
                if not m:
                    context.user_data.pop('enigma_pending',None); await message.reply_text('❌ مأموریت پیدا نشد.'); return
                raw=(message.text or '').strip()
                if field=='level':
                    vals={'آسان':'easy','متوسط':'medium','سخت':'hard','easy':'easy','medium':'medium','hard':'hard'}
                    if raw.casefold() not in {k.casefold() for k in vals}:
                        await message.reply_text('❌ سطح نامعتبر است. از آسان، متوسط یا سخت استفاده کنید.'); return
                    raw=next(v for k,v in vals.items() if k.casefold()==raw.casefold())
                elif field=='answer':
                    raw=raw.upper()
                    import re as _re
                    if not _re.fullmatch(r'[A-Z0-9 ]+',raw):
                        await message.reply_text('❌ پاسخ نامعتبر است. فقط حروف بزرگ و اعداد را وارد کنید.'); return
                elif field=='prompt' and not raw:
                    await message.reply_text('❌ متن چالش نمی‌تواند خالی باشد.'); return
                elif field=='hint':
                    raw='' if raw == '-' else raw
                m[field]=raw; enigma_set_setting(session,'missions',data); context.user_data.pop('enigma_pending',None)
                await message.reply_text('✅ مأموریت با موفقیت ویرایش شد.',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 برگشت',callback_data=f'owner:enigma_mission:{typ}:{mid}')]])); return

            # ---------------- ویرایش جایزه مأموریت (جایزه وابسته به سطح) ----------------
            if kind == "mission_reward":
                cfg=enigma_ensure_settings(session)
                lev=enigma_pending.get('level','easy'); field=enigma_pending.get('field')
                try:
                    value=_enigma_parse_number(raw)
                    if value < 0: raise ValueError
                except Exception:
                    await message.reply_text('❌ مقدار نامعتبر است. فقط یک عدد معتبر ارسال کنید.',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 برگشت',callback_data=f"owner:enigma_mission_edit:{enigma_pending.get('type')}:{int(enigma_pending.get('id',0))}")]])); return
                if field not in {'min_reward','max_reward'}:
                    context.user_data.pop('enigma_pending',None); await message.reply_text('❌ گزینه نامعتبر است.'); return
                cfg['levels'][lev][field]=value
                if cfg['levels'][lev]['max_reward'] < cfg['levels'][lev]['min_reward']:
                    await message.reply_text('❌ حداکثر جایزه نمی‌تواند کمتر از حداقل جایزه باشد.'); return
                enigma_set_setting(session,'config',cfg); context.user_data.pop('enigma_pending',None)
                await message.reply_text('✅ جایزه سطح با موفقیت ویرایش شد.',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 برگشت',callback_data=f"owner:enigma_mission_edit:{enigma_pending.get('type')}:{int(enigma_pending.get('id',0))}")]])); return

            # ---------------- جستجوی مأموریت ----------------
            if kind == "enigma_bank_search":
                from enigma.challenges import ensure_missions, TYPE_NAMES
                data=ensure_missions(session); typ=enigma_pending.get('type')
                raw=(message.text or '').strip().translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹','0123456789'))
                if not raw.isdigit() or int(raw)<=0:
                    await message.reply_text('❌ شناسه مأموریت باید عدد باشد.',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 برگشت',callback_data='owner:enigma_bank')]])); return
                mid=int(raw); matches=[m for m in data if m.get('type')==typ and int(m.get('id',0))==mid]
                context.user_data.pop('enigma_pending',None)
                if not matches:
                    await message.reply_text('❌ هیچ چالشی با این شناسه موجود نیست.',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 برگشت',callback_data='owner:enigma_bank')]])); return
                m=matches[0]
                await message.reply_text(f"🔎 <b>نتیجه جستجو</b>\n\nمأموریت <b>{mid}</b> از نوع {TYPE_NAMES.get(typ,typ)} پیدا شد.",parse_mode='HTML',reply_markup=owner_mission_search_results_keyboard(matches)); return

        # =====================================================
        # دریافت کاربران برای تنظیم تجربه رهبری
        # =====================================================
        pending_lead = context.user_data.get("admin_pending")
        if pending_lead and pending_lead.get("action") == "leadership_select_users":
            raw = _normalize_search_value((message.text or "").strip())
            target = _search_user_by_any(session, raw, get_users(session))
            if target is None:
                await message.reply_text("❌ کاربر پیدا نشد. آیدی عددی، یوزرنیم با @، شماره تلفن یا نام کشور معتبر ارسال کنید.")
                return
            countries = get_user_countries(session, target)
            if not countries:
                await message.reply_text("⚠️ این کاربر هیچ کشوری ندارد.")
                return
            if pending_lead.get("mode") == "multiple":
                ids = pending_lead.setdefault("users", [])
                if int(target.telegram_id) not in [int(x) for x in ids]:
                    ids.append(int(target.telegram_id))
                context.user_data["admin_pending"] = pending_lead
                context.user_data[_waiting_scope_key("admin_pending")] = int(message.chat_id)
                from keyboards.admin import leadership_multiple_keyboard
                await message.reply_text(f"✅ <b>{escape(target.first_name or target.username or str(target.telegram_id))}</b> انتخاب شد.\n\nکاربر بعدی را با آیدی، یوزرنیم با @، شماره تلفن یا نام کشور ارسال کنید؛ یا «پایان انتخاب» را از دکمه بزنید.", parse_mode="HTML", reply_markup=leadership_multiple_keyboard(len(ids)))
                return
            # حالت تک‌نفره: ابتدا اطلاعات کامل کاربر نمایش داده می‌شود؛
            # سپس دکمه «تمام کشورها» و دکمه هر کشور برای انتخاب مقصد تغییر تجربه قرار می‌گیرد.
            pending_lead["target_user_id"] = int(target.telegram_id)
            context.user_data["admin_pending"] = pending_lead
            context.user_data[_waiting_scope_key("admin_pending")] = int(message.chat_id)
            role = "👑 مالک" if is_owner(target.telegram_id, OWNER_ID) else ("🛡 ادمین" if is_admin(session, target.telegram_id, OWNER_ID) else "👤 کاربر عادی")
            default_country = get_default_country(session, target)
            text = (
                "👤 <b>اطلاعات کاربر</b>\n\n"
                f"نام: <b>{escape(target.first_name or target.username or 'بدون نام')}</b>\n"
                f"🆔 آیدی: <code>{target.telegram_id}</code>\n"
                f"🔤 نام کاربری: {escape('@'+target.username if target.username else 'ثبت نشده')}\n"
                f"📱 شماره: {escape(target.phone_number or 'ثبت نشده')}\n"
                f"🎭 نقش: {role}\n"
                f"📅 تاریخ عضویت: {target.created_at.strftime('%Y/%m/%d — %H:%M') if target.created_at else 'ثبت نشده'}\n"
                f"🕒 آخرین فعالیت: {target.last_active_at.strftime('%Y/%m/%d — %H:%M') if target.last_active_at else 'ثبت نشده'}\n"
                f"🌍 کشور پیش‌فرض: {escape(default_country.title) if default_country else 'ثبت نشده'}\n"
                f"🌎 تعداد کشورها: <b>{len(countries)}</b>\n\n"
                "👑 <b>تجربه رهبری</b>\nکشور موردنظر را انتخاب کنید:"
            )
            await message.reply_text(text, parse_mode="HTML", reply_markup=__import__('keyboards.admin',fromlist=['user_leadership_country_keyboard']).user_leadership_country_keyboard(int(target.telegram_id), countries, "admin:leadership_change"))
            return

        # =====================================================
        # دریافت مقدار مدت بن (بعد از انتخاب ساعتی/روزانه و قبل از دلیل)
        # =====================================================
        pending_duration = context.user_data.get("admin_pending")
        if pending_duration and pending_duration.get("action") == "ban_duration_value" and _waiting_scope_matches(context, "admin_pending", message.chat_id):
            raw_duration = _normalize_search_value((message.text or "").strip())
            try:
                amount = float(raw_duration.replace(",", "").replace("٬", ""))
                if amount <= 0 or amount != int(amount):
                    raise ValueError
                amount = int(amount)
            except Exception:
                unit = "ساعت" if pending_duration.get("duration") == "hour" else "روز"
                await message.reply_text(f"❌ مقدار مدت بن باید یک عدد صحیح بیشتر از صفر باشد. مقدار را بر حسب {unit} ارسال کنید.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data=pending_duration.get("back_callback", "admin:user_access"))]]))
                return
            pending_duration["duration_amount"] = amount
            pending_duration["action"] = "ban_single_reason" if pending_duration.get("telegram_id") else "ban_multiple_reason"
            context.user_data["admin_pending"] = pending_duration
            context.user_data[_waiting_scope_key("admin_pending")] = int(message.chat_id)
            unit = "ساعت" if pending_duration.get("duration") == "hour" else "روز"
            await message.reply_text(f"🚫 <b>مدت بن ثبت شد</b>\n\n⏳ مدت: <b>{amount} {unit}</b>\n\nحالا دلیل بن را ارسال کنید یا «بدون دلیل» را بزنید.", parse_mode="HTML", reply_markup=ban_reason_keyboard())
            return

        # =====================================================
        # دریافت دلیل بن
        # =====================================================
        pending_reason = context.user_data.get("admin_pending")
        if pending_reason and pending_reason.get("action") in {"ban_single_wait_reason", "ban_multiple_reason"}:
            raw_reason = (message.text or "").strip()
            if normalized in command_names:
                context.user_data.pop("admin_pending", None)
            else:
                pending_reason["reason"] = raw_reason or None
                if pending_reason.get("action") == "ban_single_wait_reason":
                    pending_reason["action"] = "ban_single"
                    context.user_data["admin_pending"] = pending_reason
                    context.user_data[_waiting_scope_key("admin_pending")] = int(message.chat_id)
                    await message.reply_text((f"✅ <b>دلیل دریافت شد.</b>\n\n📝 دلیل: <b>{escape(raw_reason)}</b>\n\n⚠️ آیا از بن این کاربر با این دلیل مطمئن هستید؟" if raw_reason else "ℹ️ <b>بن بدون دلیل انتخاب شد.</b>\n\n⚠️ آیا از بن این کاربر مطمئن هستید؟"), parse_mode="HTML", reply_markup=user_confirm_keyboard("ban", back_callback=pending_reason.get("back_callback", "admin:user_access")))
                else:
                    pending_reason["action"] = "ban_multiple"
                    context.user_data["admin_pending"] = pending_reason
                    context.user_data[_waiting_scope_key("admin_pending")] = int(message.chat_id)
                    await message.reply_text((f"✅ <b>دلیل دریافت شد.</b>\n\n📝 دلیل: <b>{escape(raw_reason)}</b>\n\n⚠️ آیا از بن این کاربران با این دلیل مطمئن هستید؟" if raw_reason else "ℹ️ <b>بن بدون دلیل انتخاب شد.</b>\n\n⚠️ آیا از بن این کاربران مطمئن هستید؟"), parse_mode="HTML", reply_markup=user_multiple_confirm_keyboard("ban"))
                return

        # =====================================================
        # مدیریت ورود آیدی کاربران برای بن / رفع بن
        pending_admin = context.user_data.get("admin_pending")
        if pending_admin and pending_admin.get("action", "").startswith(("ban_", "unban_")):
            if normalized in command_names:
                context.user_data.pop("admin_pending", None)
            else:
                raw_value = (message.text or "").strip()
                mode = "ban" if pending_admin["action"].startswith("ban_") else "unban"
                multiple = pending_admin["action"].endswith("multiple")
                target_user = _search_user_by_any(session, raw_value, get_users(session))
                if target_user is None:
                    await message.reply_text("❌ کاربر پیدا نشد. آیدی عددی، یوزرنیم، شماره تلفن یا نام کشور را ارسال کنید.")
                    return
                target_id = int(target_user.telegram_id)
                if target_user is None:
                    await message.reply_text("❌ این کاربر در ربات ثبت نشده است.")
                    return
                if mode == "ban":
                    if is_owner(target_id, OWNER_ID):
                        await message.reply_text("⛔ مالک قابل بن شدن نیست.")
                        return
                    if is_admin(session, target_id, OWNER_ID):
                        await message.reply_text("⛔ ادمین قابل بن شدن نیست.")
                        return
                    if target_user.is_banned:
                        await message.reply_text("⚠️ این کاربر قبلاً بن شده است.")
                        return
                else:
                    if not target_user.is_banned:
                        await message.reply_text("⚠️ <b>این کاربر بن نیست.</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data=pending_admin.get("back_callback", "admin:user_access"))]]))
                        return

                if multiple:
                    ids = pending_admin.setdefault("telegram_ids", [])
                    if target_id in ids:
                        await message.reply_text("⚠️ این آیدی قبلاً اضافه شده است.")
                        return
                    ids.append(target_id)
                    context.user_data["admin_pending"] = pending_admin
                    context.user_data[_waiting_scope_key("admin_pending")] = int(message.chat_id)
                    if mode == "ban":
                        await message.reply_text(
                            f"✅ آیدی <code>{target_id}</code> دریافت شد.\n\n📋 تعداد آماده بن: <b>{len(ids)}</b>\n\nآیدی بعدی را ارسال کنید یا برای پایان دریافت آیدی‌ها دکمه «بدون دلیل» را بزنید.",
                            parse_mode="HTML", reply_markup=ban_multiple_ids_keyboard(pending_admin.get("back_callback", "admin:user_access")))
                    else:
                        await message.reply_text(
                            f"✅ آیدی <code>{target_id}</code> دریافت شد.\n\n📋 تعداد آماده رفع بن: <b>{len(ids)}</b>\n\nآیدی بعدی را ارسال کنید یا تأیید نهایی را بزنید.",
                            parse_mode="HTML", reply_markup=user_multiple_confirm_keyboard(mode))
                    return

                role="👑 مالک" if is_owner(target_id,OWNER_ID) else ("🛡 ادمین" if is_admin(session,target_id,OWNER_ID) else "👤 کاربر عادی")
                countries=get_user_countries(session,target_user); default_country=get_default_country(session,target_user)
                profile=("🔎 <b>کاربر پیدا شد</b>\n\n"
                    f"👤 نام: <b>{escape(target_user.first_name or target_user.username or 'بدون نام')}</b>\n"
                    f"🆔 آیدی: <code>{target_id}</code>\n"
                    f"🔤 نام کاربری: {escape('@'+target_user.username if target_user.username else 'ثبت نشده')}\n"
                    f"📱 شماره: {escape(target_user.phone_number or 'ثبت نشده')}\n"
                    f"🎭 نقش: {role}\n"
                    f"🌍 کشور پیش‌فرض: {escape(default_country.title) if default_country else 'ثبت نشده'}\n"
                    f"🌎 تعداد کشورها: <b>{len(countries)}</b>\n\n")
                if mode == "ban":
                    context.user_data["admin_pending"] = {"action": "ban_single_reason", "telegram_id": target_id, "awaiting_reason_button": False}
                    context.user_data[_waiting_scope_key("admin_pending")] = int(message.chat_id)
                    await message.reply_text(profile+"🚫 <b>دلیل بن کاربر</b>\n\nدلیل را ارسال کنید یا دکمه «بدون دلیل» را بزنید.", parse_mode="HTML", reply_markup=ban_reason_keyboard())
                else:
                    context.user_data["admin_pending"] = {"action": "unban_single", "telegram_id": target_id}
                    context.user_data[_waiting_scope_key("admin_pending")] = int(message.chat_id)
                    await message.reply_text(profile+"✅ <b>رفع بن کاربر</b>\n\nآیا مطمئن هستید؟", parse_mode="HTML", reply_markup=user_confirm_keyboard("unban"))
                return

        # =====================================================
        # جستجوی کاربران و کاربران بن‌شده
        pending_admin=context.user_data.get("admin_pending")
        if pending_admin and pending_admin.get("action") in {"search_users","search_banned_users"}:
            if normalized in command_names:
                context.user_data.pop("admin_pending",None)
            else:
                raw = (message.text or "").strip()
                banned = pending_admin.get("action") == "search_banned_users"
                users_all = get_users(session, banned=True if banned else None)
                target = _search_user_by_any(session, raw, users_all)
                if target is None:
                    await message.reply_text("❌ کاربری با این مشخصات پیدا نشد.", reply_markup=user_detail_back_keyboard("admin:user_access" if banned else "admin:users"))
                    return
                if banned and not target.is_banned:
                    await message.reply_text("⚠️ این کاربر بن نیست.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="admin:user_access")]]))
                    return
                owner_view=is_owner(user_tg.id,OWNER_ID); target_owner=is_owner(target.telegram_id,OWNER_ID); target_admin=is_admin(session,target.telegram_id,OWNER_ID)
                if not owner_view and (target_owner or (target_admin and target.telegram_id!=user_tg.id)):
                    await message.reply_text("⛔ این کاربر برای شما قابل جستجو نیست.",reply_markup=user_detail_back_keyboard("admin:user_access" if banned else "admin:users"))
                    return
                context.user_data.pop("admin_pending",None); context.user_data["search_scope"]="banned" if banned else "users"
                role="👑 مالک" if target_owner else ("🛡 ادمین" if target_admin else "👤 کاربر عادی")
                countries=get_user_countries(session,target); default_country=get_default_country(session,target)
                country_lines="\n".join(
                    f"  🌍 {escape(c.title)} — 🎖 {float(c.leadership_experience or 0):,.0f} تجربه — 💰 {'♾️' if c.infinite_money else f'{c.money:,.0f}'}"
                    for c in countries
                ) or "ندارد"
                full_text=(
                    "🔎 <b>کاربر پیدا شد — اطلاعات کامل</b>\n\n"
                    f"👤 نام: <b>{escape(target.first_name or target.username or 'بدون نام')}</b>\n"
                    f"🆔 آیدی: <code>{target.telegram_id}</code>\n"
                    f"🔤 نام کاربری: {escape('@'+target.username if target.username else 'ثبت نشده')}\n"
                    f"📱 شماره: {escape(target.phone_number or 'ثبت نشده')}\n"
                    f"🎭 نقش: {role}\n"
                    f"📅 تاریخ عضویت: {target.created_at.strftime('%Y/%m/%d — %H:%M') if target.created_at else 'ثبت نشده'}\n"
                    f"🕒 آخرین فعالیت: {target.last_active_at.strftime('%Y/%m/%d — %H:%M') if target.last_active_at else 'ثبت نشده'}\n"
                    f"🚫 وضعیت حساب: {'مسدود' if target.is_banned else 'فعال'}\n"
                    f"📝 دلیل بن: {escape(target.ban_reason or 'ندارد')}\n"
                    f"⏳ پایان بن: {target.ban_until.strftime('%Y/%m/%d — %H:%M') if target.ban_until else 'دائمی/ندارد'}\n"
                    f"🌍 کشور پیش‌فرض: {escape(default_country.title) if default_country else 'ثبت نشده'}\n"
                    f"🌎 تعداد کشورها: <b>{len(countries)}</b>\n\n"
                    f"🎮 <b>مشخصات بازی</b>\n{country_lines}\n\n"
                    "آیا این اطلاعات درست است؟"
                )
                await message.reply_text(full_text[:4096],parse_mode="HTML",reply_markup=user_search_confirm_keyboard(target.telegram_id,"admin:user_access" if banned else "admin:users")); return

        # ورود آیدی برای مدیریت Adminها. هر دستور جدید، این انتظار را نیز لغو می‌کند.
        # =====================================================
        # مدیریت ورود آیدی ادمین
        # =====================================================

        pending_admin = context.user_data.get(
            "admin_pending"
        )

        if pending_admin and normalized in command_names:
            context.user_data.pop(
                "admin_pending",
                None,
            )

        pending_admin = context.user_data.get(
            "admin_pending"
        )

        if pending_admin and normalized not in command_names:

            if not is_owner(
                user_tg.id,
                OWNER_ID,
            ):
                context.user_data.pop(
                    "admin_pending",
                    None,
                )

                session.commit()

                await message.reply_text(
                    "⛔ این عملیات فقط برای مالک است.",
                    reply_markup=command_keyboard(),
                )
                return

            action = pending_admin.get("action")
            if action == "search_admin":
                raw = (message.text or "").strip()
                admins = get_admins(session)
                ids = {a.telegram_id for a in admins}
                us = [u for u in get_users(session) if u.telegram_id in ids]
                target = _search_user_by_any(session, raw, us)
                if target is None:
                    await message.reply_text("❌ ادمینی با این مشخصات پیدا نشد.",reply_markup=admin_back_keyboard()); return
                context.user_data.pop("admin_pending",None)
                role="👑 مالک" if is_owner(target.telegram_id,OWNER_ID) else "🛡 ادمین"
                countries=get_user_countries(session,target); default_country=get_default_country(session,target)
                full_text=("🔎 <b>ادمین پیدا شد</b>\n\n"
                    f"👤 نام: <b>{escape(target.first_name or 'بدون نام')}</b>\n"
                    f"🔤 نام کاربری: {escape('@'+target.username if target.username else 'ثبت نشده')}\n"
                    f"🆔 آیدی تلگرام: <code>{target.telegram_id}</code>\n"
                    f"📱 شماره تلفن: {escape(target.phone_number or 'ثبت نشده')}\n"
                    f"📝 بیوگرافی: {escape(getattr(target,'bio',None) or 'ثبت نشده')}\n"
                    f"🎭 نقش: {role}\n"
                    f"📅 تاریخ عضویت: {target.created_at.strftime('%Y/%m/%d — %H:%M') if target.created_at else 'ثبت نشده'}\n"
                    f"🕒 آخرین فعالیت ثبت‌شده: {target.last_active_at.strftime('%Y/%m/%d — %H:%M') if target.last_active_at else 'ثبت نشده'}\n"
                    f"🚫 وضعیت حساب: {'مسدود' if target.is_banned else 'فعال'}\n"
                    f"🌍 کشور پیش‌فرض: {escape(default_country.title) if default_country else 'ثبت نشده'}\n"
                    f"🌎 تعداد کشورها: <b>{len(countries)}</b>\n\nآیا این مشخصات ادمین را تأیید می‌کنید؟")
                await message.reply_text(full_text,parse_mode="HTML",reply_markup=admin_search_result_keyboard(target.telegram_id)); return

            action = pending_admin.get("action")
            # مسیر سازگار با جستجوی ادمین: آیدی، یوزرنیم، شماره یا نام کشور.
            if action == "search_admin":
                raw=(message.text or "").strip()
                admins=get_admins(session); admin_ids={int(a.telegram_id) for a in admins}
                target=_search_user_by_any(session, raw, [u for u in get_users(session) if int(u.telegram_id) in admin_ids])
                if target is None:
                    await message.reply_text("❌ ادمینی با این مشخصات پیدا نشد.",reply_markup=admin_back_keyboard()); return
                context.user_data.pop("admin_pending",None)
                role="👑 مالک" if is_owner(target.telegram_id,OWNER_ID) else "🛡 ادمین"
                dc=get_default_country(session,target); countries=get_user_countries(session,target)
                full_text=("🔎 <b>ادمین پیدا شد</b>\n\n"
                    f"👤 نام: <b>{escape(target.first_name or 'بدون نام')}</b>\n"
                    f"🔤 نام کاربری: {escape('@'+target.username if target.username else 'ثبت نشده')}\n"
                    f"🆔 آیدی تلگرام: <code>{target.telegram_id}</code>\n"
                    f"📱 شماره تلفن: {escape(target.phone_number or 'ثبت نشده')}\n"
                    f"📝 بیوگرافی: {escape(getattr(target,'bio',None) or 'ثبت نشده')}\n"
                    f"🎭 نقش: {role}\n"
                    f"📅 تاریخ عضویت: {target.created_at.strftime('%Y/%m/%d — %H:%M') if target.created_at else 'ثبت نشده'}\n"
                    f"🕒 آخرین فعالیت ثبت‌شده: {target.last_active_at.strftime('%Y/%m/%d — %H:%M') if target.last_active_at else 'ثبت نشده'}\n"
                    f"🚫 وضعیت حساب: {'مسدود' if target.is_banned else 'فعال'}\n"
                    f"🌍 کشور پیش‌فرض: {escape(dc.title) if dc else 'ثبت نشده'}\n"
                    f"🌎 تعداد کشورها: <b>{len(countries)}</b>\n\nآیا این مشخصات ادمین را تأیید می‌کنید؟")
                await message.reply_text(full_text,parse_mode="HTML",reply_markup=admin_search_result_keyboard(target.telegram_id)); return

            # افزودن/حذف ادمین با هر چهار مشخصه: آیدی، یوزرنیم، شماره تلفن یا نام کشور.
            if action in {"add_single", "add_multiple", "remove_single", "remove_multiple"}:
                raw_lookup = (message.text or "").strip()
                target_user = _search_user_by_any(session, raw_lookup, get_users(session))
                if target_user is None:
                    await message.reply_text("❌ کاربری با این مشخصات پیدا نشد. با یوزرنیم، آیدی عددی، شماره تلفن یا نام کشور جستجو کنید.", reply_markup=admin_back_keyboard())
                    return
                target_id = int(target_user.telegram_id)
                if action in {"add_single", "add_multiple"}:
                    if is_owner(target_id, OWNER_ID):
                        await message.reply_text("⚠️ مالک قابل افزودن به لیست ادمین‌ها نیست.", reply_markup=admin_back_keyboard()); return
                    if is_admin(session, target_id, OWNER_ID):
                        await message.reply_text("⚠️ این کاربر قبلاً ادمین است.", reply_markup=admin_back_keyboard()); return
                    if action == "add_multiple":
                        pending_ids = pending_admin.setdefault("telegram_ids", [])
                        if target_id in pending_ids:
                            await message.reply_text("⚠️ این کاربر قبلاً انتخاب شده است.", reply_markup=admin_back_keyboard()); return
                        pending_ids.append(target_id); context.user_data["admin_pending"] = pending_admin
                        context.user_data[_waiting_scope_key("admin_pending")] = int(message.chat_id)
                        await message.reply_text(f"✅ <b>ادمین انتخاب شد.</b>\n\n👤 {escape(target_user.first_name or target_user.username or 'بدون نام')}\n🆔 <code>{target_id}</code>\n\nادمین بعدی را با یوزرنیم، آیدی عددی، شماره تلفن یا نام کشور ارسال کنید یا تأیید نهایی را بزنید.", parse_mode="HTML", reply_markup=admin_multiple_confirm_keyboard()); return
                    context.user_data["admin_pending"] = {"action":"add_admin", "telegram_id":target_id}
                    context.user_data[_waiting_scope_key("admin_pending")] = int(message.chat_id)
                    await message.reply_text(f"🔎 <b>کاربر پیدا شد</b>\n\n👤 نام: <b>{escape(target_user.first_name or target_user.username or 'بدون نام')}</b>\n🆔 آیدی: <code>{target_id}</code>\n🔤 نام کاربری: {escape('@'+target_user.username if target_user.username else 'ثبت نشده')}\n📱 شماره: {escape(target_user.phone_number or 'ثبت نشده')}\n\nآیا این کاربر به عنوان ادمین اضافه شود؟", parse_mode="HTML", reply_markup=admin_confirm_keyboard("add_admin")); return
                if is_owner(target_id, OWNER_ID):
                    await message.reply_text("⛔ مالک قابل حذف نیست.", reply_markup=admin_back_keyboard()); return
                if not is_admin(session, target_id, OWNER_ID):
                    await message.reply_text("❌ این کاربر ادمین نیست.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="owner:remove_admin")]])); return
                if action == "remove_single":
                    context.user_data["admin_pending"]={"action":"remove_admin","telegram_id":target_id}
                    context.user_data[_waiting_scope_key("admin_pending")] = int(message.chat_id)
                    await message.reply_text(f"⚠️ <b>حذف ادمین</b>\n\n👤 نام: <b>{escape(target_user.first_name or target_user.username or 'بدون نام')}</b>\n🆔 آیدی: <code>{target_id}</code>\n\nآیا از حذف این ادمین مطمئن هستید؟", parse_mode="HTML", reply_markup=admin_confirm_keyboard("remove_admin")); return
                pending_ids = pending_admin.setdefault("telegram_ids", [])
                if target_id in pending_ids:
                    await message.reply_text("⚠️ این کاربر قبلاً انتخاب شده است.", reply_markup=admin_back_keyboard()); return
                pending_ids.append(target_id); context.user_data["admin_pending"]=pending_admin
                context.user_data[_waiting_scope_key("admin_pending")] = int(message.chat_id)
                await message.reply_text(f"✅ ادمین انتخاب شد: <code>{target_id}</code>\n\nادمین بعدی را با یوزرنیم، آیدی، شماره تلفن یا نام کشور ارسال کنید.", parse_mode="HTML", reply_markup=admin_back_keyboard()); return

            raw_id = (
                (message.text or "")
                .strip()
                .translate(
                    str.maketrans(
                        "۰۱۲۳۴۵۶۷۸۹",
                        "0123456789",
                    )
                )
            )

            if not raw_id.isdigit():
                await message.reply_text(
                    "❌ فقط آیدی عددی Telegram را ارسال کنید.",
                    reply_markup=admin_back_keyboard(),
                )
                return

            target_id = int(raw_id)

            if target_id <= 0:
                await message.reply_text(
                    "❌ آیدی واردشده معتبر نیست.",
                    reply_markup=admin_back_keyboard(),
                )
                return

            action = pending_admin.get(
                "action"
            )

            # =================================================
            # جستجوی ادمین
            # =================================================

            if action == "search_admin":

                admin_record = session.scalar(
                    select(Admin).where(
                        Admin.telegram_id == target_id
                    )
                )

                if admin_record is None:
                    await message.reply_text(
                        "❌ این آیدی ادمین نیست.",
                        reply_markup=admin_back_keyboard(),
                    )
                    return

                u = get_admin_user(
                    session,
                    target_id,
                )

                name = (
                    u.first_name
                    if u and u.first_name
                    else (
                        u.username
                        if u and u.username
                        else "ثبت‌نشده"
                    )
                )

                context.user_data.pop(
                    "admin_pending",
                    None,
                )

                session.commit()

                await message.reply_text(
                    "🔎 <b>ادمین پیدا شد</b>\n\n"
                    f"👤 نام: <b>{name}</b>\n"
                    f"🆔 آیدی عددی: <code>{target_id}</code>",
                    parse_mode="HTML",
                    reply_markup=admin_search_result_keyboard(target_id),
                )
                return

            # =================================================
            # افزودن تکی
            # =================================================

            if action == "add_single":

                # اول همان لحظه دیتابیس را چک می‌کنیم
                target_user = get_admin_user(
                    session,
                    target_id,
                )

                if target_user is None:
                    await message.reply_text(
                        "❌ این کاربر در ربات ثبت نشده است.\n\n"
                        "ابتدا کاربر باید ربات را /start کند.",
                        reply_markup=admin_back_keyboard(),
                    )
                    return

                # Owner
                if is_owner(
                    target_id,
                    OWNER_ID,
                ):
                    await message.reply_text(
                        "⚠️ مالک قابل افزودن به لیست ادمین‌ها نیست.",
                        reply_markup=admin_back_keyboard(),
                    )
                    return

                # قبلاً ادمین است
                if is_admin(
                    session,
                    target_id,
                    OWNER_ID,
                ):
                    await message.reply_text(
                        "⚠️ این کاربر قبلاً ادمین است.",
                        reply_markup=admin_back_keyboard(),
                    )
                    return

                # فقط حالا اطلاعات موقت ذخیره شود
                context.user_data["admin_pending"] = {
                    "action": "add_admin",
                    "telegram_id": target_id,
                }
                context.user_data[_waiting_scope_key("admin_pending")] = int(message.chat_id)

                session.commit()

                await message.reply_text(
                    "👤 <b>کاربر معتبر است.</b>\n\n"
                    f"🆔 آیدی: <code>{target_id}</code>\n\n"
                    "آیا این کاربر به عنوان ادمین اضافه شود؟",
                    parse_mode="HTML",
                    reply_markup=admin_confirm_keyboard(
                        "add_admin"
                    ),
                )
                return

            # =================================================
            # حذف ادمین
            # =================================================

            if action in {"remove_single", "remove_multiple"}:

                admin_record = session.scalar(
                    select(Admin).where(Admin.telegram_id == target_id)
                )

                if admin_record is None:
                    await message.reply_text(
                        "❌ این آیدی ادمین نیست.",
                        reply_markup=admin_back_keyboard(),
                    )
                    return

                if is_owner(target_id, OWNER_ID):
                    await message.reply_text(
                        "⛔ مالک قابل حذف نیست.",
                        reply_markup=admin_back_keyboard(),
                    )
                    return

                if action == "remove_single":
                    context.user_data["admin_pending"] = {
                        "action": "remove_admin",
                        "telegram_id": target_id,
                    }
                    context.user_data[_waiting_scope_key("admin_pending")] = int(message.chat_id)
                    session.commit()
                    await message.reply_text(
                        "⚠️ <b>حذف ادمین</b>\n\n"
                        f"🆔 آیدی: <code>{target_id}</code>\n\n"
                        "آیا از حذف این ادمین مطمئن هستید؟",
                        parse_mode="HTML",
                        reply_markup=admin_confirm_keyboard("remove_admin"),
                    )
                    return

                pending_ids = pending_admin.setdefault("telegram_ids", [])
                if target_id in pending_ids:
                    await message.reply_text(
                        "⚠️ این آیدی قبلاً در فهرست حذف قرار گرفته است.",
                        reply_markup=admin_back_keyboard(),
                    )
                    return

                pending_ids.append(target_id)
                context.user_data["admin_pending"] = pending_admin
                context.user_data[_waiting_scope_key("admin_pending")] = int(message.chat_id)
                session.commit()

                await message.reply_text(
                    "✅ <b>آیدی برای حذف دریافت شد.</b>\n\n"
                    f"🆔 <code>{target_id}</code>\n"
                    f"📋 تعداد آماده حذف: <b>{len(pending_ids)}</b>\n\n"
                    "آیدی ادمین بعدی را ارسال کنید یا تأیید نهایی را بزنید.",
                    parse_mode="HTML",
                    reply_markup=remove_multiple_confirm_keyboard(),
                )
                return

            # =================================================
            # افزودن چندتایی
            # =================================================

            if action == "add_multiple":

                pending_ids = pending_admin.setdefault(
                    "telegram_ids",
                    [],
                )

                # Owner
                if is_owner(
                    target_id,
                    OWNER_ID,
                ):
                    await message.reply_text(
                        "⛔ مالک قابل افزودن نیست.",
                        reply_markup=admin_back_keyboard(),
                    )
                    return

                # بررسی وجود در دیتابیس
                target_user = get_admin_user(
                    session,
                    target_id,
                )

                if target_user is None:
                    await message.reply_text(
                        "❌ این کاربر در ربات ثبت نشده است.\n\n"
                        "این آیدی به فهرست موقت اضافه نشد.",
                        reply_markup=admin_back_keyboard(),
                    )
                    return

                # تکراری داخل لیست موقت
                if target_id in pending_ids:
                    await message.reply_text(
                        "⚠️ این آیدی قبلاً در فهرست موقت قرار گرفته است.",
                        reply_markup=admin_back_keyboard(),
                    )
                    return

                # قبلاً ادمین است
                if is_admin(
                    session,
                    target_id,
                    OWNER_ID,
                ):
                    await message.reply_text(
                        "⚠️ این کاربر قبلاً ادمین است.\n\n"
                        "این آیدی به فهرست موقت اضافه نشد.",
                        reply_markup=admin_back_keyboard(),
                    )
                    return

                # اضافه به فهرست موقت
                pending_ids.append(
                    target_id
                )

                context.user_data["admin_pending"] = pending_admin
                context.user_data[_waiting_scope_key("admin_pending")] = int(message.chat_id)

                session.commit()

                count = len(pending_ids)

                await message.reply_text(
                    "✅ <b>آیدی دریافت شد.</b>\n\n"
                    f"🆔 <code>{target_id}</code>\n\n"
                    f"📋 تعداد ادمین‌های آماده افزودن: <b>{count}</b>\n\n"
                    "اگر ادمین دیگری می‌خواهید اضافه کنید، "
                    "آیدی نفر بعدی را ارسال کنید.\n\n"
                    "وقتی تمام شد، تأیید نهایی را از دکمه پایین بزنید.",
                    parse_mode="HTML",
                    reply_markup=admin_multiple_confirm_keyboard(),
                )
                return

        # انتخاب کشور پیش‌فرض با دستور آماده
        if normalized in {
            "انتخابکشورپیشفرض", "🌍انتخابکشورپیشفرض",
            "تغییرکشورپیشفرض", "🔄تغییرکشورپیشفرض",
            "انتخابگروهپیشفرض", "🌍انتخابگروهپیشفرض",
            "تغییرگروهپیشفرض", "🔄تغییرگروهپیشفرض", "چت و کانال", "💬 چت و کانال",
        }:
            from keyboards.main import country_list_keyboard
            countries = get_user_countries(session, user)
            session.commit()
            if not countries:
                await message.reply_text(
                    "❌ هنوز هیچ کشوری برای شما ثبت نشده است.",
                    reply_markup=command_keyboard(),
                )
                return
            await message.reply_text(
                "🌍 <b>کشور پیش‌فرض را انتخاب کنید:</b>",
                parse_mode="HTML",
                reply_markup=country_list_keyboard(countries),
            )
            await message.reply_text("⌨️", reply_markup=country_command_keyboard())
            return

        # برگشت فروشگاه: هر مرحله فقط یک سطح به عقب برمی‌گردد.
        if normalized in ("برگشت", "🔙برگشت"):
            context.user_data.pop("pending_exchange", None)
            context.user_data.pop("shield_purchase_pending", None)
            store_nav = context.user_data.get("store_nav")
            if store_nav == "purchase_list":
                context.user_data["store_nav"] = "purchase_types"
                context.user_data[_waiting_scope_key("store_nav")] = int(message.chat_id)
                await message.reply_text("🚀 <b>خرید موشک</b>\n\nنوع موشک را انتخاب کنید:", parse_mode="HTML", reply_markup=missile_purchase_type_keyboard())
                return
            if store_nav == "shield_list" or (isinstance(store_nav, str) and store_nav.startswith("shield_list:")):
                context.user_data["store_nav"] = "store"
                context.user_data[_waiting_scope_key("store_nav")] = int(message.chat_id)
                await message.reply_text("🏪 <b>فروشگاه تسلیحات</b>\n\nبرای خرید، گزینه زیر را انتخاب کنید:", parse_mode="HTML", reply_markup=store_command_keyboard())
                return
            if store_nav == "shield_types":
                context.user_data["store_nav"] = "store"
                context.user_data[_waiting_scope_key("store_nav")] = int(message.chat_id)
                await message.reply_text("🏪 <b>فروشگاه تسلیحات</b>\n\nبرای خرید، گزینه زیر را انتخاب کنید:", parse_mode="HTML", reply_markup=store_command_keyboard())
                return
            if store_nav == "purchase_types":
                context.user_data["store_nav"] = "store"
                context.user_data[_waiting_scope_key("store_nav")] = int(message.chat_id)
                await message.reply_text("🏪 <b>فروشگاه تسلیحات</b>\n\nبرای خرید، گزینه زیر را انتخاب کنید:", parse_mode="HTML", reply_markup=store_command_keyboard())
                return
            if store_nav == "store":
                context.user_data.pop("store_nav", None)
                await message.reply_text("🔙 به منوی اصلی برگشتید.", reply_markup=command_keyboard())
                return
            session.commit()
            await message.reply_text("🔙 به منوی اصلی برگشتید.", reply_markup=command_keyboard())
            return

        # نرخ تبادل یک دستور است و انتظار قبلی را لغو می‌کند.
        if normalized in ("نرختبادل", "📊نرختبادل"):
            context.user_data.pop("pending_exchange", None)
            session.commit()
            await message.reply_text(
                exchange_rate_text(session),
                parse_mode="HTML",
                reply_markup=exchange_command_keyboard(),
            )
            return

        # ورود به بخش تبادل
        if normalized in ("تبادل", "💱تبادل"):
            context.user_data.pop("pending_exchange", None)
            if country is None:
                session.commit()
                await message.reply_text(
                    "❌ ابتدا یک کشور را به‌عنوان کشور پیش‌فرض انتخاب کنید.",
                    reply_markup=command_keyboard(),
                )
                return
            session.commit()
            await message.reply_text(
                exchange_rate_text(session),
                parse_mode="HTML",
                reply_markup=exchange_command_keyboard(),
            )
            return

        # انتخاب نوع تبادل؛ چون در بالا pending قبلی پاک شده، دستور جدید همیشه فعال است.
        if normalized in exchange_commands:
            exchange_type = exchange_commands[normalized]

            if country is None:
                session.commit()
                await message.reply_text(
                    "❌ ابتدا یک کشور را به‌عنوان کشور پیش‌فرض انتخاب کنید.",
                    reply_markup=command_keyboard(),
                )
                return

            rate = get_exchange_rates(session)[exchange_type]
            from_names = {
                "money": "💰 پول",
                "metal": "🔩 فلز",
                "fuel": "⛽ سوخت",
                "uranium": "☢️ اورانیوم",
            }
            context.user_data["pending_exchange"] = {"type": exchange_type}
            context.user_data[_waiting_scope_key("pending_exchange")] = int(message.chat_id)
            session.commit()
            await message.reply_text(
                f"💱 <b>{rate['title']}</b>\n\n"
                f"مقدار {from_names[rate['from_resource']]} را وارد کنید.\n\n"
                f"📌 حداقل مقدار: <b>1</b>\n"
                f"📈 نرخ پایه: <b>{rate['input_unit']:,}</b> {from_names[rate['from_resource']]} ➜ "
                f"<b>{rate['output_unit']:,}</b> {from_names[rate['to_resource']]}\n\n"
                "هر مقدار صحیح مثبت را می‌توانید وارد کنید؛ نیاز به مضرب بودن ندارد.\n\n"
                f"مثال: <code>1</code>، <code>3</code>، <code>7</code>",
                parse_mode="HTML",
                reply_markup=exchange_input_keyboard(),
            )
            return

        # دریافت مقدار تبادل
        pending_exchange = context.user_data.get("pending_exchange")
        if pending_exchange:
            if country is None:
                context.user_data.pop("pending_exchange", None)
                session.commit()
                await message.reply_text(
                    "❌ ابتدا یک کشور را به‌عنوان کشور پیش‌فرض انتخاب کنید.",
                    reply_markup=command_keyboard(),
                )
                return

            raw_amount = (
                (message.text or "")
                .strip()
                .replace(",", "")
                .replace("٬", "")
                .replace("٫", ".")
                .translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
            )

            try:
                amount = float(raw_amount)
            except ValueError:
                await message.reply_text(
                    "❌ مقدار باید یک عدد مثبت باشد.\n\nمثال: <code>1000</code> یا <code>12.50</code>",
                    parse_mode="HTML",
                    reply_markup=exchange_input_keyboard(),
                )
                return
            if amount <= 0 or round(amount, 2) != amount:
                await message.reply_text(
                    "❌ مقدار باید بیشتر از صفر و حداکثر دو رقم اعشار داشته باشد.",
                    parse_mode="HTML",
                    reply_markup=exchange_input_keyboard(),
                )
                return
            amount = round(amount, 2)

            exchange_type = pending_exchange["type"]
            ok, result = calculate_exchange(country, exchange_type, amount, session)

            if not ok:
                if result == "INVALID_AMOUNT":
                    error = "❌ مقدار باید بیشتر از صفر باشد."
                elif result == "OUTPUT_TOO_SMALL":
                    error = "❌ این مقدار برای دریافت حداقل یک واحد از منبع مقصد کافی نیست."
                else:
                    rate = get_exchange_rates(session)[exchange_type]
                    error = (
                        f"❌ موجودی {rate['title'].split(' ➜ ')[0]} کافی نیست.\n"
                        f"مقدار کمبود: <b>{result[1]:,}</b>"
                    )
                await message.reply_text(
                    error,
                    parse_mode="HTML",
                    reply_markup=exchange_input_keyboard(),
                )
                return

            rate = get_exchange_rates(session)[exchange_type]
            pending_exchange["amount"] = amount
            pending_exchange["output"] = result["output"]
            context.user_data["pending_exchange"] = pending_exchange
            context.user_data[_waiting_scope_key("pending_exchange")] = int(message.chat_id)

            await message.reply_text(
                "🧾 <b>تأیید تبادل</b>\n\n"
                f"🔄 {rate['title']}\n\n"
                f"📥 مقدار ورودی: <b>{amount:,}</b>\n"
                f"📤 مقدار دریافتی: <b>{result['output']:,}</b>\n\n"
                "آیا این معامله را تأیید می‌کنید؟",
                parse_mode="HTML",
                reply_markup=exchange_confirm_keyboard(),
            )
            return

        # زرادخانه
        if normalized in {command_key("زرادخانه"), command_key("🏭 زرادخانه")}:
            if country is None:
                await message.reply_text("❌ ابتدا یک کشور را به‌عنوان کشور پیش‌فرض انتخاب کنید.", reply_markup=command_keyboard())
                return
            from services.economy import get_arsenal_config
            from services.game import arsenal_info, can_upgrade_arsenal
            cfg = get_arsenal_config(session)
            finalize_construction(country)
            session.commit()
            level = int(getattr(country, "arsenal_level", 0))
            next_level = level + 1
            next_data = cfg.get("levels", {}).get(next_level, {})
            build_uranium = float(cfg.get("build_cost", {}).get("uranium", 0)) > 0
            upgrade_uranium = float(next_data.get("uranium", 0)) > 0
            construction_text = construction_label(country, "arsenal")
            finish_uranium_cost = arsenal_instant_finish_uranium_cost(country, cfg)
            await message.reply_text(
                arsenal_info(country, cfg),
                parse_mode="HTML",
                reply_markup=__import__("keyboards.main", fromlist=["arsenal_keyboard"]).arsenal_keyboard(
                    can_build=(level == 0),
                    can_upgrade=can_upgrade_arsenal(country, cfg)[0],
                    can_build_uranium=build_uranium,
                    can_upgrade_uranium=upgrade_uranium,
                    construction_text=construction_text,
                    finish_uranium_cost=finish_uranium_cost,
                ),
            )
            # صفحه‌کلید آمادهٔ این بخش باید با «🔙 برگشت» جایگزین شود.
            # پیام «⌨️» عمداً باقی می‌ماند تا Reply Keyboard تلگرام پایدار بماند.
            await message.reply_text("🏭", reply_markup=arsenal_command_keyboard())
            return

        # مرکز فرماندهی
        if normalized in {command_key("مرکز فرماندهی"), command_key("🏛️ مرکز فرماندهی")}:
            if country is None:
                session.commit()
                await message.reply_text(
                    "❌ ابتدا یک کشور را به‌عنوان کشور پیش‌فرض انتخاب کنید.",
                    reply_markup=command_keyboard(),
                )
                return
            session.commit()
            hq_cfg = get_hq_config(session)
            hq_status = construction_label(country, "command_center")
            await message.reply_text(
                hq_info(country, hq_cfg),
                parse_mode="HTML",
                reply_markup=hq_keyboard(can_upgrade_hq(country, hq_cfg)[0], built=int(country.command_center_level)>0, construction_text=hq_status, in_progress=bool(hq_status), finish_uranium_cost=hq_instant_finish_uranium_cost(country,hq_cfg), build_uranium=float(hq_cfg.get("build_cost",{}).get("uranium",0))>0, upgrade_uranium=float((hq_cfg.get("levels",{}).get(int(country.command_center_level)+1,{}) or {}).get("uranium",0))>0),
            )
            await message.reply_text("🏛️", reply_markup=hq_command_keyboard())
            return

        # معدن فلز
        if normalized in {command_key("معدن فلز"), command_key("⛏️ معدن فلز")}:
            if country is None:
                session.commit()
                await message.reply_text(
                    "❌ ابتدا یک کشور را به‌عنوان کشور پیش‌فرض انتخاب کنید.",
                    reply_markup=command_keyboard(),
                )
                return
            mine_cfg = get_metal_mine_config(session)
            mine_status = construction_label(country, "metal_mine")
            can_upgrade = can_upgrade_metal_mine(country, mine_cfg)[0]
            can_collect = True
            session.commit()
            await message.reply_text(
                metal_mine_info(country, mine_cfg),
                parse_mode="HTML",
                reply_markup=metal_mine_keyboard(
                    can_build=(country.metal_mine_level == 0),
                    can_collect=can_collect,
                    can_upgrade=can_upgrade,
                    can_build_uranium=(float(mine_cfg.get("build_cost_uranium", 0) or 0) > 0 or float(mine_cfg.get("build_cost", {}).get("uranium", 0) or 0) > 0),
                    can_upgrade_uranium=(float(mine_cfg.get("levels", {}).get(country.metal_mine_level + 1, {}).get("uranium", 0)) > 0),
                    construction_text=mine_status,
                    finish_uranium_cost=metal_mine_instant_finish_uranium_cost(country, mine_cfg),
                ),
            )
            await message.reply_text("⛏️", reply_markup=mine_command_keyboard())
            return

        if country is None:
            session.commit()
            await message.reply_text(
                "❌ ابتدا باید یک کشور را به‌عنوان کشور پیش‌فرض انتخاب کنید.",
                reply_markup=command_keyboard(),
            )
            return

        session.commit()

