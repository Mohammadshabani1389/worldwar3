from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import date, datetime, timedelta
from io import BytesIO

from sqlalchemy import select
from database.models import BotSetting

PREFIX = 'golden:'
BOXES = {
    'money': ('💰', 'پول'),
    'fuel': ('⛽', 'سوخت'),
    'metal': ('🔩', 'فلز'),
    'uranium': ('☢️', 'اورانیوم'),
}
MAX_LEVEL = 100


def _default():
    cfg = {
        'enabled': False,
        'daily_count': 5,
        'start': '10:00',
        'end': '23:00',
        'active_days': [0, 1, 2, 3, 4, 5, 6],
        'weights': {k: 25.0 for k in BOXES},
        'opened_delete_seconds': 30,
        'unanswered_delete_seconds': 60,
        'challenge_digits': 5,
        'options_count': 4,
        'levels': {},
    }
    bases = {'money': 50000, 'fuel': 100, 'metal': 100, 'uranium': 10}
    costs = {'money': 100000, 'fuel': 100000, 'metal': 100000, 'uranium': 100000}
    for k in BOXES:
        rewards_min = {str(i): float(bases[k] * i) for i in range(1, MAX_LEVEL + 1)}
        rewards_max = dict(rewards_min)
        cfg['levels'][k] = {
            'max_level': MAX_LEVEL,
            'upgrade_times': {str(i): 0 for i in range(1, MAX_LEVEL + 1)},
            'reward_min': rewards_min,
            'reward_max': rewards_max,
            # Legacy field is retained only for compatibility with older DB data.
            'rewards': dict(rewards_min),
            'costs': {str(i): float(costs[k] * i) for i in range(1, MAX_LEVEL + 1)},
        }
    return cfg


def _row(session):
    return session.scalar(select(BotSetting).where(BotSetting.key == PREFIX + 'config'))


def _migrate_reward_range(level_cfg: dict, level: int, default_value: float):
    """Normalize old scalar rewards and new min/max reward ranges."""
    mins = level_cfg.setdefault('reward_min', {})
    maxs = level_cfg.setdefault('reward_max', {})
    legacy = level_cfg.get('rewards', {})
    key = str(level)
    if key not in mins:
        value = legacy.get(key, default_value) if isinstance(legacy, dict) else default_value
        if isinstance(value, dict):
            mins[key] = float(value.get('min', value.get('minimum', default_value)) or 0)
            maxs.setdefault(key, float(value.get('max', value.get('maximum', mins[key])) or 0))
        else:
            mins[key] = float(value or 0)
    if key not in maxs:
        value = legacy.get(key, mins[key]) if isinstance(legacy, dict) else mins[key]
        if isinstance(value, dict):
            maxs[key] = float(value.get('max', value.get('maximum', mins[key])) or mins[key])
        else:
            maxs[key] = float(value or mins[key])
    mins[key] = max(0.0, float(mins[key] or 0))
    maxs[key] = max(mins[key], float(maxs[key] or 0))


def load_config(session):
    row = _row(session)
    try:
        cfg = json.loads(row.value) if row else None
    except Exception:
        cfg = None
    defaults = _default()
    if not isinstance(cfg, dict):
        cfg = defaults

    def merge(dst, src):
        for k, v in src.items():
            if isinstance(v, dict):
                if not isinstance(dst.get(k), dict):
                    dst[k] = {}
                merge(dst[k], v)
            elif k not in dst:
                dst[k] = v

    merge(cfg, defaults)
    cfg['daily_count'] = max(0, int(cfg.get('daily_count', 5) or 0))
    cfg['opened_delete_seconds'] = max(0, int(cfg.get('opened_delete_seconds', 30) or 0))
    cfg['unanswered_delete_seconds'] = max(1, int(cfg.get('unanswered_delete_seconds', 60) or 60))
    cfg['active_days'] = [int(x) for x in cfg.get('active_days', list(range(7))) if int(x) in range(7)]
    cfg['weights'] = {k: max(0.0, float(cfg.get('weights', {}).get(k, 0) or 0)) for k in BOXES}

    for k in BOXES:
        lv = cfg['levels'].setdefault(k, defaults['levels'][k].copy())
        lv.setdefault('upgrade_times', {})
        lv.setdefault('costs', {})
        lv.setdefault('reward_min', {})
        lv.setdefault('reward_max', {})
        legacy_time = max(0, int(lv.get('upgrade_seconds', 0) or 0))
        for i in range(1, MAX_LEVEL + 1):
            key = str(i)
            lv['upgrade_times'].setdefault(key, legacy_time)
            lv['upgrade_times'][key] = max(0, int(lv['upgrade_times'].get(key, 0) or 0))
            lv['costs'].setdefault(key, defaults['levels'][k]['costs'][key])
            lv['costs'][key] = max(0.0, float(lv['costs'].get(key, 0) or 0))
            _migrate_reward_range(lv, i, defaults['levels'][k]['reward_min'][key])
        lv['max_level'] = max(1, min(MAX_LEVEL, int(lv.get('max_level', MAX_LEVEL) or MAX_LEVEL)))

    save_config(session, cfg)
    return cfg


def save_config(session, cfg):
    row = _row(session)
    raw = json.dumps(cfg, ensure_ascii=False)
    if row:
        row.value = raw
    else:
        session.add(BotSetting(key=PREFIX + 'config', value=raw))
    session.commit()


def _state_row(session, country_id):
    return session.scalar(select(BotSetting).where(BotSetting.key == f'{PREFIX}state:{int(country_id)}'))


def load_state(session, country_id):
    row = _state_row(session, country_id)
    try:
        state = json.loads(row.value) if row else None
    except Exception:
        state = None
    if not isinstance(state, dict):
        state = {}

    state.setdefault('levels', {k: 1 for k in BOXES})
    state.setdefault('history', [])
    state.setdefault('upgrades', {})
    state.setdefault('actives', {})
    state.setdefault('daily_sent', {})

    # Migrate the old single-active schema to multiple independently tracked boxes.
    legacy_active = state.pop('active', None)
    if legacy_active and isinstance(legacy_active, dict) and legacy_active.get('token'):
        state['actives'].setdefault(str(legacy_active['token']), legacy_active)

    if not isinstance(state['actives'], dict):
        state['actives'] = {}
    if not isinstance(state['daily_sent'], dict):
        state['daily_sent'] = {}

    for k in BOXES:
        state['levels'][k] = max(1, min(MAX_LEVEL, int(state['levels'].get(k, 1) or 1)))

    # Keep only a few recent days of sent-index bookkeeping.
    today_key = datetime.utcnow().date().isoformat()
    keep_dates = sorted(state['daily_sent'].keys())[-3:]
    state['daily_sent'] = {k: state['daily_sent'][k] for k in keep_dates if k <= today_key}
    return state


def save_state(session, country_id, state):
    row = _state_row(session, country_id)
    raw = json.dumps(state, ensure_ascii=False)
    if row:
        row.value = raw
    else:
        session.add(BotSetting(key=f'{PREFIX}state:{int(country_id)}', value=raw))
    session.commit()


def weights_valid(cfg):
    weights = [max(0.0, float(cfg.get('weights', {}).get(k, 0) or 0)) for k in BOXES]
    return bool(weights) and abs(sum(weights) - 100.0) < 1e-6


def daily_box_types(cfg, count: int, for_date: date):
    """Build a real weighted daily mix, then randomize its order.

    The configured percentages become actual daily quotas as closely as integers allow.
    Example: 50 boxes + Uranium 10% => exactly 5 Uranium boxes that day.
    """
    count = max(0, int(count or 0))
    if count <= 0:
        return []
    weights = {k: max(0.0, float(cfg.get('weights', {}).get(k, 0) or 0)) for k in BOXES}
    total = sum(weights.values())
    if total <= 0:
        return ['money'] * count
    raw = {k: count * weights[k] / total for k in BOXES}
    quotas = {k: int(math.floor(v)) for k, v in raw.items()}
    remaining = count - sum(quotas.values())
    remainders = sorted(BOXES, key=lambda k: (raw[k] - quotas[k], k), reverse=True)
    for k in remainders[:remaining]:
        quotas[k] += 1

    seed_material = f"{for_date.isoformat()}|{count}|" + '|'.join(f'{k}:{weights[k]:.8f}' for k in BOXES)
    seed = int.from_bytes(hashlib.sha256(seed_material.encode('utf-8')).digest()[:8], 'big')
    rng = random.Random(seed)
    sequence = [k for k in BOXES for _ in range(quotas[k])]
    rng.shuffle(sequence)
    return sequence


def choose_type(cfg):
    # Kept for compatibility with callers outside the scheduler.
    sequence = daily_box_types(cfg, 1, datetime.utcnow().date())
    return sequence[0] if sequence else 'money'


def reward_range_for(cfg, box, level):
    data = cfg['levels'][box]
    key = str(level)
    lo = float(data.get('reward_min', {}).get(key, data.get('rewards', {}).get(key, 0)) or 0)
    hi = float(data.get('reward_max', {}).get(key, lo) or lo)
    lo = max(0.0, lo)
    hi = max(lo, hi)
    return lo, hi


def reward_for(cfg, box, level):
    lo, hi = reward_range_for(cfg, box, level)
    if math.isclose(lo, hi):
        return lo
    return random.SystemRandom().uniform(lo, hi)


def cost_for(cfg, box, next_level):
    return float(cfg['levels'][box]['costs'].get(str(next_level), 0) or 0)


def apply_reward(country, box, amount):
    if box == 'money':
        country.money = float(country.money or 0) + amount
    elif box == 'fuel':
        country.fuel = float(country.fuel or 0) + amount
    elif box == 'metal':
        country.metal = float(country.metal or 0) + amount
    else:
        country.uranium = float(country.uranium or 0) + amount


def make_challenge(digits=5, n=4):
    digits = max(1, int(digits))
    n = max(2, int(n))
    low = 10 ** (digits - 1) if digits > 1 else 0
    high = (10 ** digits) - 1
    answer = f'{random.randint(low, high):0{digits}d}'
    vals = {answer}
    max_unique = 10 ** digits
    target = min(n, max_unique)
    attempts = 0
    while len(vals) < target and attempts < target * 30:
        vals.add(f'{random.randint(low, high):0{digits}d}')
        attempts += 1
    if len(vals) < target:
        for value in range(max(0, low), high + 1):
            vals.add(f'{value:0{digits}d}')
            if len(vals) >= target:
                break
    opts = list(vals)
    random.shuffle(opts)
    return answer, opts


def challenge_image(answer):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new('RGB', (900, 280), 'white')
    draw = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype('DejaVuSans-Bold.ttf', 120)
    except Exception:
        font = ImageFont.load_default()
    box = draw.textbbox((0, 0), answer, font=font)
    w = box[2] - box[0]
    h = box[3] - box[1]
    draw.text(((900 - w) // 2, (280 - h) // 2 - 10), answer, font=font, fill='black')
    out = BytesIO()
    im.save(out, 'PNG')
    out.seek(0)
    return out


def parse_hhmm(v):
    h, m = map(int, str(v).split(':'))
    # 24:00 is a valid end-of-day value; 24:01+ is not.
    if h == 24 and m == 0:
        return 24 * 60
    return max(0, min(23, h)) * 60 + max(0, min(59, m))


def iran_weekday(d: date) -> int:
    """Map Python Monday=0 to Persian UI Saturday=0 ... Friday=6."""
    return (d.weekday() + 2) % 7


def schedule_times(cfg, date_value):
    """Create exactly daily_count evenly spaced send times inside the window."""
    count = max(0, int(cfg.get('daily_count', 0) or 0))
    if count <= 0 or iran_weekday(date_value) not in cfg.get('active_days', []):
        return []
    start_seconds = parse_hhmm(cfg.get('start', '10:00')) * 60
    end_seconds = parse_hhmm(cfg.get('end', '23:00')) * 60
    if end_seconds <= start_seconds:
        return []
    span = end_seconds - start_seconds
    # Midpoints ensure every item is strictly inside [start, end).
    return [
        datetime(date_value.year, date_value.month, date_value.day) + timedelta(seconds=start_seconds + span * ((i + 0.5) / count))
        for i in range(count)
    ]
