"""Central Bank repayment and overdue-lock rules."""
from __future__ import annotations
from datetime import datetime, timedelta
from math import floor
from services.settings import get_bank_loan_lock_days, get_bank_loan_overdue_multiplier


def due_cycles(loan, now=None):
    now = now or datetime.utcnow()
    if loan.status != "active" or not loan.next_payment_at or now < loan.next_payment_at:
        return 0
    interval = max(0.1, float(loan.installment_interval_days or 1.0)) * 86400.0
    elapsed = max(0.0, (now - loan.next_payment_at).total_seconds())
    cycles = 1 + int(floor(elapsed / interval))
    remaining = max(0, int(loan.installments or 0) - int(loan.installments_paid or 0))
    return min(cycles, remaining)


def due_amount(loan, cycles):
    base = max(0.0, float(loan.installment_amount or 0.0))
    # Current installment is 1x; each earlier missed installment is multiplied
    # by the Owner-configured overdue multiplier. With the default ×2, two
    # consecutive due installments cost 2x + 1x, then 4x + 2x + 1x, etc.
    multiplier=getattr(loan, "_overdue_multiplier", None)
    if multiplier is None:
        multiplier=2.0
    multiplier=max(1.0,float(multiplier))
    if abs(multiplier-1.0)<1e-9:
        return base*int(cycles)
    return base*((multiplier**int(cycles))-1.0)/(multiplier-1.0)


def process_due_loan(session, loan, country, now=None):
    now = now or datetime.utcnow()
    cycles = due_cycles(loan, now)
    setattr(loan, "_overdue_multiplier", get_bank_loan_overdue_multiplier(session))
    if cycles <= 0:
        return {"status": "not_due", "cycles": 0, "amount": 0.0}
    amount = due_amount(loan, cycles)
    if amount <= 0:
        return {"status": "invalid", "cycles": cycles, "amount": amount}
    infinite = bool(getattr(country, "infinite_money", False))
    if not infinite and float(country.money or 0) + 1e-9 < amount:
        lock_days = get_bank_loan_lock_days(session)
        until = now + timedelta(days=lock_days) if lock_days > 0 else None
        # Do not repeatedly extend the same lock on every worker tick.
        acc = getattr(country, "_bank_account_for_repayment", None)
        if acc is not None and until is not None:
            if not acc.bank_locked_until or acc.bank_locked_until <= now:
                acc.bank_locked_until = until
        return {"status": "locked", "cycles": cycles, "amount": amount, "locked_until": until}

    if not infinite:
        country.money = float(country.money or 0) - amount
    loan.paid = float(loan.paid or 0) + amount
    loan.installments_paid = int(loan.installments_paid or 0) + cycles
    interval_days = max(0.1 / 24.0, float(loan.installment_interval_days or 1.0))
    old_due = loan.next_payment_at
    if loan.installments_paid >= int(loan.installments or 0):
        loan.status = "paid"
        loan.next_payment_at = None
        loan.last_reminder_for = None
    else:
        loan.next_payment_at = old_due + timedelta(days=interval_days * cycles)
        loan.last_reminder_for = None
    # The missed installments create additional repayment obligation. Keep the
    # original scheduled future installments plus the geometric overdue charge.
    future_count = max(0, int(loan.installments or 0) - int(loan.installments_paid or 0))
    loan.total_due = float(loan.paid or 0) + future_count * float(loan.installment_amount or 0)
    return {"status": "paid", "cycles": cycles, "amount": amount}
