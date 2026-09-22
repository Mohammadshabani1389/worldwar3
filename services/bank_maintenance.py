"""Background maintenance for Central Bank population and investments."""
from __future__ import annotations
import asyncio
import random
from datetime import datetime, timedelta
from sqlalchemy import select
from database.db import SessionLocal
from database.models import Country, BankAccount, BankInvestment
from services.economy import get_bank_config, accrue_bank_tax

async def bank_maintenance_worker(app=None):
    await asyncio.sleep(2)
    while True:
        try:
            with SessionLocal() as session:
                now=datetime.utcnow()
                cfg=get_bank_config(session)
                growth=max(0.0,float(cfg.get("population_growth_per_hour",0) or 0))
                if growth > 0:
                    accounts=session.scalars(select(BankAccount)).all()
                    for acc in accounts:
                        country=session.get(Country, int(acc.country_id))
                        if country is not None:
                            accrue_bank_tax(session,country)
                        last=getattr(acc,"population_last_growth_at",None) or now
                        # Reuse the account timestamp as a durable population tick anchor.
                        elapsed=max(0.0,(now-last).total_seconds()/3600.0)
                        if elapsed >= 0.01:
                            acc.citizens=max(0,int(acc.citizens or 0)+int(elapsed*growth))
                            acc.population_last_growth_at=now
                if growth <= 0:
                    accounts=session.scalars(select(BankAccount)).all()
                    for acc in accounts:
                        country=session.get(Country, int(acc.country_id))
                        if country is not None:
                            accrue_bank_tax(session,country)
                investments=session.scalars(select(BankInvestment).where(BankInvestment.status=="active", BankInvestment.ends_at <= now)).all()
                for inv in investments:
                    country=session.get(Country, int(inv.country_id))
                    if country is None:
                        inv.status="settled"
                        continue
                    return_type=str(inv.return_type or "money")
                    if return_type == "money":
                        pmin=float(inv.profit_min_percent if inv.profit_min_percent is not None else inv.profit_percent or 0)
                        pmax=float(inv.profit_max_percent if inv.profit_max_percent is not None else inv.profit_percent or 0)
                        lmin=float(inv.loss_min_percent if inv.loss_min_percent is not None else inv.loss_percent or 0)
                        lmax=float(inv.loss_max_percent if inv.loss_max_percent is not None else inv.loss_percent or 0)
                        if random.choice((True, False)):
                            pct=random.uniform(max(0.0,pmin),max(0.0,pmax)); delta=float(inv.principal or 0)*pct/100.0
                            inv.result=delta; inv.status="won"
                        else:
                            pct=random.uniform(max(0.0,lmin),max(0.0,lmax)); delta=-float(inv.principal or 0)*pct/100.0
                            inv.result=delta; inv.status="lost"
                        if country is not None:
                            country.money=float(country.money or 0)+float(inv.principal or 0)+delta
                    else:
                        pmin=float(inv.profit_min_percent or 0); pmax=float(inv.profit_max_percent or 0)
                        lmin=float(inv.loss_min_percent or 0); lmax=float(inv.loss_max_percent or 0)
                        if pmin == 0 and pmax == 0 and lmin == 0 and lmax == 0:
                            cfg=get_bank_config(session); level_cfg=cfg.get("levels",{}).get(str(getattr(country,"bank_level",1) or 1),{}) or {}
                            plan_name=str(inv.plan_name or "")
                            plan=next((x for x in (level_cfg.get("investments",[]) or []) if str(x.get("name"))==plan_name),{})
                            pmin=float(plan.get("profit_min_value",0) or 0); pmax=float(plan.get("profit_max_value",0) or 0)
                            lmin=float(plan.get("loss_min_value",0) or 0); lmax=float(plan.get("loss_max_value",0) or 0)
                        if random.choice((True, False)):
                            amount=random.uniform(max(0.0,pmin),max(0.0,pmax)); delta=amount; inv.status="won"
                        else:
                            amount=random.uniform(max(0.0,lmin),max(0.0,lmax)); delta=-amount; inv.status="lost"
                        inv.result=delta
                        if country is not None:
                            field={"population":"bank_population","fuel":"fuel","metal":"metal","uranium":"uranium","leadership_experience":"leadership_experience"}.get(return_type)
                            if field=="bank_population":
                                acc=session.scalar(select(BankAccount).where(BankAccount.country_id==country.id))
                                if acc is not None: acc.citizens=max(0,int(acc.citizens or 0)+int(delta))
                            elif field and hasattr(country,field):
                                current=float(getattr(country,field,0) or 0)
                                setattr(country,field,max(0.0,current+delta))
                        pct=0.0
                        if country is not None:
                            leader_id=int(getattr(country,"leader_user_id",0) or 0)
                            if app is not None and leader_id:
                                try:
                                    sign="سود" if delta>0 else "زیان"
                                    return_names={"money":"پول","population":"جمعیت","fuel":"سوخت","metal":"فلز","uranium":"اورانیوم","leadership_experience":"تجربه رهبری"}
                                    return_name=return_names.get(return_type,"پول")
                                    await app.bot.send_message(chat_id=leader_id,text=(f"📈 <b>نتیجه سرمایه‌گذاری بانک مرکزی</b>\n\nطرح: <b>{inv.plan_name}</b>\n💰 سرمایه اولیه: <b>{float(inv.principal or 0):,.0f}</b>\n📊 نتیجه: <b>{sign}</b>\n🎁 نوع بازده: <b>{return_name}</b>\n💵 مقدار بازده: <b>{abs(delta):,.0f}</b>\n📌 تغییر: <b>{delta:+,.0f}</b>"),parse_mode="HTML")
                                except Exception:
                                    pass
                session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(30)
