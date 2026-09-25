from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from database.db import SessionLocal
from database.models import Country, BotSetting
from services.golden_boxes import (
    BOXES,
    challenge_image,
    daily_box_types,
    iran_weekday,
    load_config,
    load_state,
    make_challenge,
    save_state,
    schedule_times,
    weights_valid,
)

DAY_KEY = 'golden:schedule:'


def _scheduled(session, day: date, cfg):
    """Persist a complete daily plan: exact times + randomized weighted box types."""
    key = DAY_KEY + day.strftime('%Y-%m-%d')
    row = session.scalar(select(BotSetting).where(BotSetting.key == key))
    if row:
        try:
            payload = json.loads(row.value)
            existing = None
            if isinstance(payload, dict) and isinstance(payload.get('events'), list):
                existing = payload['events']
            elif isinstance(payload, list):
                times = [datetime.fromisoformat(x) for x in payload]
                types = daily_box_types(cfg, len(times), day)
                existing = [{'index': i, 'at': t.isoformat(), 'box': types[i]} for i, t in enumerate(times)]

            desired = len(schedule_times(cfg, day))
            if isinstance(existing, list) and len(existing) == desired:
                return existing
            if isinstance(existing, list) and len(existing) != desired:
                # Rebuild today's plan when Owner changes the daily count/window.
                # Already-sent ordinal indexes remain marked sent, so a published old
                # event is not duplicated merely because the schedule was resized.
                pass
        except Exception:
            pass

    times = schedule_times(cfg, day)
    types = daily_box_types(cfg, len(times), day)
    events = [{'index': i, 'at': t.isoformat(), 'box': types[i]} for i, t in enumerate(times)]
    raw = json.dumps({'events': events}, ensure_ascii=False)
    if row:
        row.value = raw
    else:
        session.add(BotSetting(key=key, value=raw))
    session.commit()
    return events


async def _publish(app, session, country, cfg, box):
    """Publish one real box message to the country's actual Telegram group."""
    try:
        chat = await app.bot.get_chat(int(country.chat_id))
        if getattr(chat, 'type', None) not in {'group', 'supergroup'}:
            return False
        if getattr(country, 'chat_type', None) != getattr(chat, 'type', None):
            country.chat_type = chat.type
            session.flush()

        state = load_state(session, country.id)
        answer, opts = make_challenge(int(cfg.get('challenge_digits', 5)), int(cfg.get('options_count', 4)))
        token = f'{country.id}-{int(datetime.utcnow().timestamp() * 1000)}-{len(state.get("history", []))}-{len(state.get("actives", {}))}'
        icon, name = BOXES[box]
        option_width = max(1, min(4, (len(opts) + 1) // 2))
        rows = []
        for i in range(0, len(opts), option_width):
            rows.append([
                InlineKeyboardButton(
                    x,
                    callback_data=f'golden:answer:{country.id}:{token}:{x}',
                    style='primary',
                ) for x in opts[i:i + option_width]
            ])
        kb = InlineKeyboardMarkup(rows)
        img = challenge_image(answer)
        msg = await app.bot.send_photo(
            chat_id=int(country.chat_id),
            photo=img,
            caption=(
                f'{icon} <b>جعبه {name}</b>\n\n'
                '⚡ اولین نفری که رمز درست را پیدا کند، جایزه را می‌برد.\n\n'
                'یکی از گزینه‌های زیر پاسخ صحیح است.'
            ),
            parse_mode='HTML',
            reply_markup=kb,
        )
        state['actives'][token] = {
            'token': token,
            'box': box,
            'answer': answer,
            'options': opts,
            'wrong': [],
            'created_at': datetime.utcnow().isoformat(),
            'status': 'open',
            'message_id': int(msg.message_id),
            'chat_id': int(country.chat_id),
        }
        save_state(session, country.id, state)
        return True
    except Exception:
        return False


def _mark_sent(state, day_key, index):
    sent = state.setdefault('daily_sent', {}).setdefault(day_key, [])
    if index not in sent:
        sent.append(index)
        sent.sort()


async def golden_scheduler(app):
    while True:
        now = datetime.utcnow()
        session = SessionLocal()
        try:
            cfg = load_config(session)
            today = now.date()
            countries = session.scalars(select(Country)).all()
            if cfg.get('enabled') and weights_valid(cfg) and iran_weekday(today) in cfg.get('active_days', []):
                events = _scheduled(session, today, cfg)
                day_key = today.isoformat()
                for country in countries:
                    state = load_state(session, country.id)
                    sent = set(state.setdefault('daily_sent', {}).get(day_key, []))
                    pending_events = []
                    for event in events:
                        idx = int(event.get('index', 0))
                        if idx in sent:
                            continue
                        try:
                            at = datetime.fromisoformat(str(event.get('at')))
                        except Exception:
                            continue
                        if now >= at:
                            pending_events.append(event)

                    # Catch up every overdue event. There is intentionally no single-active-box block:
                    # every scheduled box must still be published inside the configured daily window.
                    for event in pending_events:
                        ok = await _publish(app, session, country, cfg, str(event.get('box') or 'money'))
                        if ok:
                            _mark_sent(state, day_key, int(event.get('index', 0)))
                            save_state(session, country.id, state)

                    # Reload after publishing: _publish writes the new active box into the DB.
                    state = load_state(session, country.id)

                    # Upgrade completion.
                    upgrades = state.get('upgrades', {}) or {}
                    changed = False
                    for box, pending in list(upgrades.items()):
                        try:
                            finish = datetime.fromisoformat(str(pending.get('finish_at')))
                        except Exception:
                            continue
                        if now >= finish and box in BOXES:
                            target = int(pending.get('target', state['levels'].get(box, 1)))
                            state['levels'][box] = max(int(state['levels'].get(box, 1)), target)
                            upgrades.pop(box, None)
                            changed = True
                    state['upgrades'] = upgrades
                    if changed:
                        save_state(session, country.id, state)

                    # Expire every open box independently.
                    expire_after = timedelta(seconds=int(cfg.get('unanswered_delete_seconds', 60)))
                    actives = state.get('actives', {}) or {}
                    active_changed = False
                    for token, active in list(actives.items()):
                        if active.get('status') != 'open':
                            actives.pop(token, None)
                            active_changed = True
                            continue
                        try:
                            created = datetime.fromisoformat(str(active.get('created_at')))
                        except Exception:
                            continue
                        if now - created >= expire_after:
                            mid = active.get('message_id')
                            if mid:
                                try:
                                    await app.bot.delete_message(chat_id=int(country.chat_id), message_id=int(mid))
                                except Exception:
                                    pass
                            active['status'] = 'expired'
                            active['expired_at'] = now.isoformat()
                            state['history'].append(active)
                            actives.pop(token, None)
                            active_changed = True
                    state['actives'] = actives
                    if active_changed:
                        save_state(session, country.id, state)
        except Exception:
            # Never stop the background scheduler because one country/chat has an API or DB error.
            pass
        finally:
            session.close()
        await asyncio.sleep(5)
