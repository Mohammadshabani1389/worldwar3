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
    """Check once per minute and send one reminder per loan per due date."""
    while True:
        try:
            with SessionLocal() as session:
                reminder_time = get_bank_loan_reminder_time(session)
                now_utc = datetime.utcnow()
                now_local = datetime.now(TZ)
                if now_local.strftime("%H:%M") == reminder_time:
                    loans = session.scalars(
                        select(BankLoan, Country).join(Country, Country.id == BankLoan.country_id).where(BankLoan.status == "active")
                    ).all()
                    for loan, country in loans:
                        due_local = _local_dt(loan.next_payment_at)
                        if due_local is None or due_local.date() > now_local.date():
                            continue
                        # One reminder per exact installment due time (not per calendar day),
                        # so 12-hour schedules can receive two reminders on the same day.
                        if loan.last_reminder_for is not None and loan.next_payment_at is not None:
                            last_utc=loan.last_reminder_for
                            if last_utc.tzinfo is None: last_utc=last_utc.replace(tzinfo=timezone.utc)
                            due_utc=loan.next_payment_at
                            if due_utc.tzinfo is None: due_utc=due_utc.replace(tzinfo=timezone.utc)
                            if abs((last_utc-due_utc).total_seconds()) < 1:
                                continue
                        leader_id = int(getattr(country, "leader_user_id", 0) or 0)
                        if not leader_id:
                            continue
                        remaining = max(0.0, float(loan.total_due or 0) - float(loan.paid or 0))
                        try:
                            from keyboards.main import central_bank_loan_detail_keyboard
                            await app.bot.send_message(
                                chat_id=leader_id,
                                text=(
                                    f"🔔 <b>یادآوری قسط وام بانک مرکزی</b>\n\n"
                                    f"💳 وام شماره: <b>#{loan.id}</b>\n"
                                    f"💵 مبلغ قسط: <b>{float(loan.installment_amount or 0):,.0f}</b>\n"
                                    f"🧾 قسط: <b>{int(loan.installments_paid or 0) + 1}/{int(loan.installments or 0)}</b>\n"
                                    f"💰 کل باقی‌مانده: <b>{remaining:,.0f}</b>\n"
                                    f"📅 سررسید: <b>{due_local.strftime('%Y-%m-%d')}</b>"
                                ),
                                parse_mode="HTML",
                                reply_markup=central_bank_loan_detail_keyboard(loan.id),
                            )
                            loan.last_reminder_for = loan.next_payment_at
                            session.commit()
                        except Exception:
                            # Failed delivery must not mark the reminder as sent.
                            session.rollback()
        except Exception:
            pass
        await asyncio.sleep(30)
