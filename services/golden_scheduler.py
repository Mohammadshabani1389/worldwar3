from __future__ import annotations
import asyncio, json
from datetime import datetime, timedelta
from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database.db import SessionLocal
from database.models import Country, BotSetting
from services.golden_boxes import load_config, load_state, save_state, choose_type, weights_valid, make_challenge, challenge_image, BOXES

DAY_KEY='golden:schedule:'

def _scheduled(session,date,cfg):
    key=DAY_KEY+date.strftime('%Y-%m-%d')
    row=session.scalar(select(BotSetting).where(BotSetting.key==key))
    if row:
        try:return [datetime.fromisoformat(x) for x in json.loads(row.value)]
        except Exception: pass
    from services.golden_boxes import schedule_times
    times=schedule_times(cfg,date)
    raw=json.dumps([x.isoformat() for x in times])
    if row: row.value=raw
    else: session.add(BotSetting(key=key,value=raw))
    session.commit(); return times

async def _publish(app,country,cfg):
    if not weights_valid(cfg): return
    session=SessionLocal()
    try:
        state=load_state(session,country.id)
        if state.get('active'): return
        box=choose_type(cfg); answer,opts=make_challenge(int(cfg.get('challenge_digits',5)), int(cfg.get('options_count',4))); token=f'{country.id}-{int(datetime.utcnow().timestamp()*1000)}'
        state['active']={'token':token,'box':box,'answer':answer,'options':opts,'wrong':[],'created_at':datetime.utcnow().isoformat(),'status':'open','message_id':None,'chat_id':int(country.chat_id)}
        save_state(session,country.id,state)
        icon,name=BOXES[box]
        kb=InlineKeyboardMarkup([[InlineKeyboardButton(x,callback_data=f'golden:answer:{country.id}:{token}:{x}',style='primary') for x in opts[:2]], [InlineKeyboardButton(x,callback_data=f'golden:answer:{country.id}:{token}:{x}',style='primary') for x in opts[2:]]])
        img=challenge_image(answer)
        msg=await app.bot.send_photo(chat_id=country.chat_id,photo=img,caption=f'{icon} <b>جعبه {name}</b>\n\n⚡ اولین نفری که رمز درست را پیدا کند، جایزه را می‌برد.\n\nیکی از گزینه‌های زیر پاسخ صحیح است.',parse_mode='HTML',reply_markup=kb)
        session=SessionLocal(); state=load_state(session,country.id); active=state.get('active') or {}; active['message_id']=msg.message_id; active['chat_id']=int(country.chat_id); state['active']=active; save_state(session,country.id,state)
    except Exception: pass
    finally:
        session.close()

async def golden_scheduler(app):
    while True:
        session=SessionLocal()
        try:
            cfg=load_config(session)
            now=datetime.utcnow(); today=now.date(); countries=session.scalars(select(Country)).all()
            if cfg.get('enabled') and weights_valid(cfg):
                times=_scheduled(session,today,cfg)
                for t in times:
                    if abs((now-t).total_seconds())<35:
                        for c in countries: await _publish(app,c,cfg)
            for c in countries:
                    state=load_state(session,c.id)
                    upgrades=state.get('upgrades',{}) or {}
                    changed=False
                    for box,pending in list(upgrades.items()):
                        try: finish=datetime.fromisoformat(str(pending.get('finish_at')))
                        except Exception: continue
                        if now>=finish and box in BOXES:
                            target=int(pending.get('target',state['levels'].get(box,1)))
                            state['levels'][box]=max(int(state['levels'].get(box,1)),target)
                            upgrades.pop(box,None); changed=True
                    state['upgrades']=upgrades
                    if changed: save_state(session,c.id,state)
                    active=state.get('active')
                    if not active: continue
                    created=datetime.fromisoformat(active.get('created_at'))
                    limit=timedelta(seconds=int(cfg.get('unanswered_delete_seconds',60)))
                    if active.get('status')=='open' and now-created>=limit:
                        mid=active.get('message_id')
                        if mid:
                            try: await app.bot.delete_message(chat_id=c.chat_id,message_id=int(mid))
                            except Exception: pass
                        active['status']='expired'; state['history'].append(active); state['active']=None; save_state(session,c.id,state)
        except Exception: pass
        finally: session.close()
        await asyncio.sleep(20)
