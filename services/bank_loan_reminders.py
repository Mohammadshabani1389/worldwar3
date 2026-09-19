"""Daily Central Bank loan installment reminders."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from database.db import SessionLocal
from database.models import BankLoan, Country
from services.settings import get_bank_loan_reminder_time

TZ = ZoneInfo("Asia/Tehran")


def _local_dt(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(TZ)


async def bank_loan_reminder_worker(app):
    """Process due installments automatically and send reminders at Owner time."""
    from services.economy import ensure_bank_account
    from services.bank_loan_repayment import process_due_loan
    from services.settings import get_bank_loan_lock_days
    while True:
        try:
            with SessionLocal() as session:
                now_utc=datetime.utcnow()
                loans=session.scalars(select(BankLoan).where(BankLoan.status=="active")).all()
                for loan in loans:
                    country=session.get(Country,int(loan.country_id))
                    if country is None:
                        continue
                    acc=ensure_bank_account(session,country)
                    setattr(country,"_bank_account_for_repayment",acc)
                    result=process_due_loan(session,loan,country,now_utc)
                    leader_id=int(getattr(country,"leader_user_id",0) or 0)
                    if result.get("status")=="paid":
                        if leader_id:
                            try:
                                await app.bot.send_message(chat_id=leader_id,text=(
                                    f"💳 <b>بازپرداخت خودکار وام</b>\n\nوام #{loan.id}\n"
                                    f"💰 مبلغ پرداخت‌شده: <b>{float(result.get('amount',0)):,.0f}</b> پول\n"
                                    f"🧾 تعداد اقساط تسویه‌شده: <b>{int(result.get('cycles',0))}</b>"),parse_mode="HTML")
                            except Exception:
                                pass
                        continue
                    if result.get("status")=="locked":
                        if leader_id:
                            try:
                                await app.bot.send_message(chat_id=leader_id,text=(
                                    f"🔒 <b>بانک مرکزی بسته شد</b>\n\nوام #{loan.id}\n"
                                    f"💰 مبلغ سررسیدشده: <b>{float(result.get('amount',0)):,.0f}</b> پول\n"
                                    f"⏳ مدت بسته بودن: <b>{get_bank_loan_lock_days(session):g} روز</b>\n"
                                    "علت: موجودی پول برای بازپرداخت کافی نبود."),parse_mode="HTML")
                            except Exception:
                                pass
                        continue
                session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(30)
