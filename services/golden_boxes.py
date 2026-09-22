from __future__ import annotations
import json, random, math
from datetime import datetime, timedelta
from io import BytesIO
from sqlalchemy import select
from database.models import BotSetting

PREFIX='golden:'
BOXES={
 'money':('💰','پول'), 'fuel':('⛽','سوخت'), 'metal':('🔩','فلز'), 'uranium':('☢️','اورانیوم')
}
MAX_LEVEL=100


def _default():
    cfg={'enabled':False,'daily_count':5,'start':'10:00','end':'23:00','active_days':[0,1,2,3,4,5,6],
         'weights':{k:25.0 for k in BOXES},'opened_delete_seconds':30,'unanswered_delete_seconds':60,
         'challenge_digits':5,'options_count':4,'levels':{}}
    bases={'money':50000,'fuel':100,'metal':100,'uranium':10}
    costs={'money':100000,'fuel':100000,'metal':100000,'uranium':100000}
    for k in BOXES:
        cfg['levels'][k]={'max_level':100,'upgrade_seconds':0,'rewards':{str(i):bases[k]*i for i in range(1,101)},'costs':{str(i):costs[k]*i for i in range(1,101)}}
    return cfg

def _row(session):
    return session.scalar(select(BotSetting).where(BotSetting.key==PREFIX+'config'))

def load_config(session):
    row=_row(session)
    try: cfg=json.loads(row.value) if row else None
    except Exception: cfg=None
    d=_default()
    if not isinstance(cfg,dict): cfg=d
    def merge(dst,src):
        for k,v in src.items():
            if isinstance(v,dict):
                if not isinstance(dst.get(k),dict): dst[k]={}
                merge(dst[k],v)
            elif k not in dst: dst[k]=v
    merge(cfg,d)
    cfg['daily_count']=max(0,int(cfg.get('daily_count',5) or 0))
    cfg['opened_delete_seconds']=max(0,int(cfg.get('opened_delete_seconds',30) or 0))
    cfg['unanswered_delete_seconds']=max(1,int(cfg.get('unanswered_delete_seconds',60) or 60))
    cfg['active_days']=[int(x) for x in cfg.get('active_days',list(range(7))) if int(x) in range(7)]
    cfg['weights']={k:max(0.0,float(cfg.get('weights',{}).get(k,0) or 0)) for k in BOXES}
    for k in BOXES:
        lv=cfg['levels'].setdefault(k,{'max_level':100,'upgrade_seconds':0,'rewards':{},'costs':{}})
        lv.setdefault('upgrade_seconds',0)
        lv['upgrade_seconds']=max(0,int(lv.get('upgrade_seconds',0) or 0))
        lv['max_level']=max(1,min(100,int(lv.get('max_level',100) or 100)))
        for i in range(1,101):
            lv['rewards'].setdefault(str(i),_default()['levels'][k]['rewards'][str(i)])
            lv['costs'].setdefault(str(i),_default()['levels'][k]['costs'][str(i)])
    save_config(session,cfg)
    return cfg

def save_config(session,cfg):
    row=_row(session)
    raw=json.dumps(cfg,ensure_ascii=False)
    if row: row.value=raw
    else: session.add(BotSetting(key=PREFIX+'config',value=raw))
    session.commit()

def _state_row(session,country_id): return session.scalar(select(BotSetting).where(BotSetting.key==f'{PREFIX}state:{int(country_id)}'))
def load_state(session,country_id):
    row=_state_row(session,country_id)
    try: s=json.loads(row.value) if row else None
    except Exception: s=None
    if not isinstance(s,dict): s={}
    s.setdefault('levels',{k:1 for k in BOXES}); s.setdefault('active',None); s.setdefault('history',[]); s.setdefault('upgrades',{})
    for k in BOXES: s['levels'][k]=max(1,min(100,int(s['levels'].get(k,1) or 1)))
    return s

def save_state(session,country_id,s):
    row=_state_row(session,country_id); raw=json.dumps(s,ensure_ascii=False)
    if row: row.value=raw
    else: session.add(BotSetting(key=f'{PREFIX}state:{int(country_id)}',value=raw))
    session.commit()

def choose_type(cfg):
    items=[(k,float(cfg['weights'].get(k,0) or 0)) for k in BOXES]
    total=sum(w for _,w in items)
    if total<=0: return 'money'
    return random.choices([k for k,w in items],[w for _,w in items])[0]

def weights_valid(cfg): return abs(sum(float(cfg['weights'].get(k,0) or 0) for k in BOXES)-100.0)<1e-6

def reward_for(cfg,box,level): return float(cfg['levels'][box]['rewards'].get(str(level),0) or 0)
def cost_for(cfg,box,next_level): return float(cfg['levels'][box]['costs'].get(str(next_level),0) or 0)

def apply_reward(country,box,amount):
    if box=='money': country.money=float(country.money or 0)+amount
    elif box=='fuel': country.fuel=float(country.fuel or 0)+amount
    elif box=='metal': country.metal=float(country.metal or 0)+amount
    else: country.uranium=float(country.uranium or 0)+amount

def make_challenge(digits=5,n=4):
    low=10**(max(1,int(digits))-1); high=(10**max(1,int(digits)))-1
    answer=f'{random.randint(low,high)}'
    vals={answer}
    while len(vals)<max(2,int(n)):
        x=list(answer); random.shuffle(x)
        v=''.join(x)
        if v!=answer and v.isdigit(): vals.add(v)
    opts=list(vals); random.shuffle(opts)
    return answer,opts

def challenge_image(answer):
    from PIL import Image,ImageDraw,ImageFont
    im=Image.new('RGB',(900,280),'white'); d=ImageDraw.Draw(im)
    try: font=ImageFont.truetype('DejaVuSans-Bold.ttf',120)
    except Exception: font=ImageFont.load_default()
    box=d.textbbox((0,0),answer,font=font); w=box[2]-box[0]; h=box[3]-box[1]
    d.text(((900-w)//2,(280-h)//2-10),answer,font=font,fill='black')
    out=BytesIO(); im.save(out,'PNG'); out.seek(0); return out

def parse_hhmm(v):
    h,m=map(int,str(v).split(':')); return max(0,min(23,h))*60+max(0,min(59,m))

def schedule_times(cfg,date):
    count=int(cfg.get('daily_count',0) or 0)
    if count<=0 or date.weekday() not in cfg.get('active_days',[]): return []
    a=parse_hhmm(cfg.get('start','10:00')); b=parse_hhmm(cfg.get('end','23:00'))
    if b<=a: return []
    span=b-a
    points=sorted(random.sample(range(span+1),min(count,span+1)))
    return [datetime(date.year,date.month,date.day)+timedelta(minutes=a+p) for p in points]
