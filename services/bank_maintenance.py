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
                    # Result is a uniformly sampled outcome between configured worst loss and best profit.
                    pct=random.uniform(-abs(float(inv.loss_percent or 0)), max(0.0,float(inv.profit_percent or 0)))
                    result=float(inv.principal or 0)*(1.0+pct/100.0)
                    delta=result-float(inv.principal or 0)
                    inv.result=delta
                    inv.status="won" if delta>0.000001 else ("lost" if delta< -0.000001 else "settled")
                    country=session.get(Country, int(inv.country_id))
                    if country is not None:
                        country.money=float(country.money or 0)+max(0.0,result)
                        leader_id=int(getattr(country,"leader_user_id",0) or 0)
                        if app is not None and leader_id:
                            try:
                                sign="سود" if delta>0 else ("زیان" if delta<0 else "بدون تغییر")
                                await app.bot.send_message(chat_id=leader_id,text=(f"📈 <b>نتیجه سرمایه‌گذاری بانک مرکزی</b>\n\n"
                                    f"طرح: <b>{inv.plan_name}</b>\n"
                                    f"💰 سرمایه اولیه: <b>{float(inv.principal or 0):,.0f}</b>\n"
                                    f"📊 نتیجه: <b>{sign}</b>\n"
                                    f"💵 مبلغ نهایی: <b>{max(0.0,result):,.0f}</b>\n"
                                    f"📌 تغییر: <b>{delta:+,.0f}</b>"),parse_mode="HTML")
                            except Exception:
                                pass
                session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(30)
