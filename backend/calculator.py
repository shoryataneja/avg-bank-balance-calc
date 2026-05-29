import calendar
import logging
from datetime import date
from typing import Optional
from collections import defaultdict

from parser import OPENING_BALANCE_KEY

logger = logging.getLogger(__name__)

# Type alias: each date maps to an ordered list of transaction balances (PDF order)
Transactions = dict[date, list[float]]


# ---------------------------------------------------------------------------
# Month grouping
# ---------------------------------------------------------------------------

def group_by_month(all_txns: Transactions) -> dict[tuple[int, int], Transactions]:
    """Split a flat {date: [balances]} dict into {(year, month): {date: [balances]}}."""
    groups: dict[tuple[int, int], Transactions] = defaultdict(dict)
    for d, balances in all_txns.items():
        if d == OPENING_BALANCE_KEY:
            continue  # sentinel key — not a real date, skip grouping
        groups[(d.year, d.month)][d] = balances
    return dict(sorted(groups.items()))


# ---------------------------------------------------------------------------
# Single-day transaction accessors
# ---------------------------------------------------------------------------

def get_last_transaction(txns: Transactions, d: date) -> Optional[float]:
    """
    Return the LAST transaction balance for a date.
    This is the standard closing balance used for all normal date calculations.
    """
    balances = txns.get(d)
    return balances[-1] if balances else None


def get_first_transaction_of_day(txns: Transactions, d: date) -> Optional[float]:
    """
    Return the FIRST transaction balance for a date.
    Used ONLY in the Day 1 forward-search fallback (Step 3/4).
    The first transaction of a day represents the opening state before
    any activity on that day, making it the best proxy for the prior day's
    closing balance when no earlier data exists.
    """
    balances = txns.get(d)
    return balances[0] if balances else None


# ---------------------------------------------------------------------------
# Day 1 fallback helpers
# ---------------------------------------------------------------------------

def get_previous_month_balance(
    all_txns: Transactions, year: int, month: int
) -> Optional[float]:
    """
    STEP 2a — Previous month closing balance.

    Walk backward from the last day of the previous month and return the
    LAST transaction balance of the most recent day that has transactions.
    This is the natural carry-forward balance into the new month.
    """
    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    _, days_in_prev = calendar.monthrange(prev_year, prev_month)

    for day in range(days_in_prev, 0, -1):
        d = date(prev_year, prev_month, day)
        bal = get_last_transaction(all_txns, d)
        if bal is not None:
            logger.debug(
                "Day 1 [Step 2a] previous month closing: %s → %.2f", d, bal
            )
            return bal

    return None


def get_opening_balance(all_txns: Transactions) -> Optional[float]:
    """
    STEP 2b — Opening balance from statement.

    Some bank statements print an explicit 'Opening Balance' row with no date.
    The parser stores these under OPENING_BALANCE_KEY.
    We take the LAST such value (in case multiple pages repeat it).
    """
    balances = all_txns.get(OPENING_BALANCE_KEY)
    if balances:
        bal = balances[-1]
        logger.debug("Day 1 [Step 2b] opening balance from statement: %.2f", bal)
        return bal
    return None


def search_forward_for_first_transaction(
    month_txns: Transactions, year: int, month: int
) -> Optional[float]:
    """
    STEP 3/4 — Forward search within the month.

    Starting from Day 2, scan forward day-by-day until a day with transactions
    is found. Return the FIRST transaction of that day (not the last).

    Using the FIRST transaction is intentional: it represents the balance
    BEFORE any activity on that day, which is the best available proxy for
    what the balance was on Day 1 when no earlier data exists.
    """
    _, days_in_month = calendar.monthrange(year, month)

    for day in range(2, days_in_month + 1):
        d = date(year, month, day)
        bal = get_first_transaction_of_day(month_txns, d)
        if bal is not None:
            logger.debug(
                "Day 1 [Step 3/4] forward search found Day %d first txn: %.2f", day, bal
            )
            return bal

    return None


# ---------------------------------------------------------------------------
# Day 1 orchestrator
# ---------------------------------------------------------------------------

def get_day1_balance(
    month_txns: Transactions,
    all_txns: Transactions,
    year: int,
    month: int,
) -> Optional[float]:
    """
    Resolve the balance for Day 1 using a strict 4-step priority order.

    STEP 1 — Transactions exist on Day 1:
        Use the LAST transaction balance of Day 1 (standard closing balance).

    STEP 2 — Day 1 is missing, look for prior context:
        2a. Use the LAST transaction balance from the previous month.
        2b. If previous month unavailable, use the opening balance
            detected in the statement (if any).
        Prefer 2a over 2b when both are available.

    STEP 3/4 — No prior context available:
        Search FORWARD from Day 2 onward within the same month.
        Use the FIRST transaction of the first day found.
        (First transaction = balance before that day's activity.)

    Returns None only if the entire month has no transactions at all.
    """
    day1 = date(year, month, 1)

    # ── STEP 1 ───────────────────────────────────────────────────────────────
    bal = get_last_transaction(month_txns, day1)
    if bal is not None:
        logger.info(
            "Day 1 [Step 1] %s: transactions exist, using last txn = %.2f", day1, bal
        )
        return bal

    logger.debug("Day 1 [Step 1] %s: no transactions on Day 1, trying Step 2", day1)

    # ── STEP 2a ──────────────────────────────────────────────────────────────
    bal = get_previous_month_balance(all_txns, year, month)
    if bal is not None:
        logger.info(
            "Day 1 [Step 2a] %s: using previous month closing balance = %.2f", day1, bal
        )
        return bal

    # ── STEP 2b ──────────────────────────────────────────────────────────────
    bal = get_opening_balance(all_txns)
    if bal is not None:
        logger.info(
            "Day 1 [Step 2b] %s: using statement opening balance = %.2f", day1, bal
        )
        return bal

    logger.debug(
        "Day 1 [Step 2] %s: no previous month or opening balance, trying forward search",
        day1,
    )

    # ── STEP 3/4 ─────────────────────────────────────────────────────────────
    bal = search_forward_for_first_transaction(month_txns, year, month)
    if bal is not None:
        logger.info(
            "Day 1 [Step 3/4] %s: using forward-search first transaction = %.2f", day1, bal
        )
        return bal

    logger.warning("Day 1 %s: all fallback steps exhausted, no balance found", day1)
    return None


# ---------------------------------------------------------------------------
# Daily balance fill (all days except Day 1)
# ---------------------------------------------------------------------------

def _fill_daily_from_txns(txns: Transactions, year: int, month: int) -> dict[int, float]:
    """
    Build a {day: closing_balance} map for every day of the month.

    Rules:
    - Each day's balance = LAST transaction of that day (closing balance).
    - Days with no transaction carry forward the previous day's closing balance.
    - Day 1 is intentionally left to be overwritten by get_day1_balance().
    """
    _, days_in_month = calendar.monthrange(year, month)
    filled: dict[int, float] = {}
    last_balance: Optional[float] = None

    for day in range(1, days_in_month + 1):
        d = date(year, month, day)
        bal = get_last_transaction(txns, d)
        if bal is not None:
            last_balance = bal
        if last_balance is not None:
            filled[day] = last_balance

    return filled


def _get_balance_with_fallback(filled: dict[int, float], target_day: int) -> Optional[float]:
    """
    Return balance for target_day.
    If missing, walk BACKWARD day-by-day until one is found.

    This backward search applies to ALL dates except Day 1.
    Day 1 uses get_day1_balance() which has its own forward-search fallback.
    """
    for day in range(target_day, 0, -1):
        if day in filled:
            return filled[day]
    return None


# ---------------------------------------------------------------------------
# Average calculation
# ---------------------------------------------------------------------------

def calculate_averages(month_txns: Transactions, all_txns: Transactions) -> dict:
    """
    Compute 5-Series average (dates 1, 5, 10, 15, 20, 25, 30) and
    10-Series average (dates 1, 10, 20, 30).

    Day 1 balance is resolved via the 4-step priority logic.
    All other dates use last-transaction closing balance with backward fallback.
    """
    sample = next(iter(month_txns))
    year, month = sample.year, sample.month

    # Build daily map using last-transaction per day + carry-forward
    filled = _fill_daily_from_txns(month_txns, year, month)

    # Overwrite Day 1 with the special priority-based balance
    day1_balance = get_day1_balance(month_txns, all_txns, year, month)
    if day1_balance is not None:
        filled[1] = day1_balance
        logger.debug("calculate_averages: Day 1 set to %.2f", day1_balance)

    dates_5s  = [1, 5, 10, 15, 20, 25, 30]
    dates_10s = [1, 10, 20, 30]

    selected_5s:  dict[str, float] = {}
    selected_10s: dict[str, float] = {}

    for d in dates_5s:
        bal = _get_balance_with_fallback(filled, d)
        if bal is not None:
            selected_5s[str(d)] = round(bal, 2)
            logger.debug("5-Series Day %d → %.2f", d, bal)

    for d in dates_10s:
        bal = _get_balance_with_fallback(filled, d)
        if bal is not None:
            selected_10s[str(d)] = round(bal, 2)
            logger.debug("10-Series Day %d → %.2f", d, bal)

    avg5s  = round(sum(selected_5s.values())  / len(selected_5s),  2) if selected_5s  else 0.0
    avg10s = round(sum(selected_10s.values()) / len(selected_10s), 2) if selected_10s else 0.0

    logger.info(
        "calculate_averages %d-%02d: 5-Series=%.2f  10-Series=%.2f",
        year, month, avg5s, avg10s,
    )

    return {
        "average5":             avg5s,
        "average10":            avg10s,
        "selected_balances_5":  selected_5s,
        "selected_balances_10": selected_10s,
    }
