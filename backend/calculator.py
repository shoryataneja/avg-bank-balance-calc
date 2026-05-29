import calendar
import logging
from datetime import date
from typing import Optional
from collections import defaultdict

from parser import OPENING_BALANCE_KEY

logger = logging.getLogger(__name__)

_SORT_ORDER_KEY = "__sort_order__"

# Type alias
Transactions = dict[date, list[float]]


# ---------------------------------------------------------------------------
# Closing balance accessor — direction-aware
# ---------------------------------------------------------------------------

def _closing(balances: list[float], is_desc: bool) -> float:
    """
    Return the closing balance from a day's transaction list.

    ASCENDING  → last row in PDF = latest transaction → balances[-1]
    DESCENDING → first row in PDF = latest transaction → balances[0]
    """
    return balances[0] if is_desc else balances[-1]


# ---------------------------------------------------------------------------
# Month grouping
# ---------------------------------------------------------------------------

def group_by_month(all_txns: Transactions) -> dict[tuple[int, int], Transactions]:
    """Split {date: [balances]} into {(year, month): {date: [balances]}}."""
    _SKIP = {OPENING_BALANCE_KEY, _SORT_ORDER_KEY}
    groups: dict[tuple[int, int], Transactions] = defaultdict(dict)
    for d, balances in all_txns.items():
        if d in _SKIP:
            continue
        groups[(d.year, d.month)][d] = balances
    return dict(sorted(groups.items()))


# ---------------------------------------------------------------------------
# Single-day accessors
# ---------------------------------------------------------------------------

def get_last_transaction(txns: Transactions, d: date, is_desc: bool = False) -> Optional[float]:
    """Closing balance for a date, respecting statement direction."""
    balances = txns.get(d)
    if not balances:
        return None
    return _closing(balances, is_desc)


def get_first_transaction_of_day(txns: Transactions, d: date, is_desc: bool = False) -> Optional[float]:
    """
    Opening state of a date — used ONLY in Day 1 forward-search fallback.
    Opposite index from closing: represents balance BEFORE the day's activity.
    """
    balances = txns.get(d)
    if not balances:
        return None
    # Opening = the chronologically FIRST transaction = opposite of closing
    return balances[-1] if is_desc else balances[0]


# ---------------------------------------------------------------------------
# Day 1 fallback helpers
# ---------------------------------------------------------------------------

def get_previous_month_balance(
    all_txns: Transactions, year: int, month: int, is_desc: bool
) -> Optional[float]:
    """Walk backward from end of previous month, return closing balance of last active day."""
    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    _, days_in_prev = calendar.monthrange(prev_year, prev_month)
    for day in range(days_in_prev, 0, -1):
        d = date(prev_year, prev_month, day)
        bal = get_last_transaction(all_txns, d, is_desc)
        if bal is not None:
            logger.debug("Day 1 [Step 2a] prev month closing: %s → %.2f", d, bal)
            return bal
    return None


def get_opening_balance(all_txns: Transactions) -> Optional[float]:
    """Opening balance row stored by parser under OPENING_BALANCE_KEY."""
    balances = all_txns.get(OPENING_BALANCE_KEY)
    if balances:
        bal = balances[-1]
        logger.debug("Day 1 [Step 2b] statement opening balance: %.2f", bal)
        return bal
    return None


def search_forward_for_first_transaction(
    month_txns: Transactions, year: int, month: int, is_desc: bool
) -> Optional[float]:
    """
    Forward search from Day 2 — returns the opening state of the first active day.
    Used as last resort for Day 1 when no prior context exists.
    """
    _, days_in_month = calendar.monthrange(year, month)
    for day in range(2, days_in_month + 1):
        d = date(year, month, day)
        bal = get_first_transaction_of_day(month_txns, d, is_desc)
        if bal is not None:
            logger.debug("Day 1 [Step 3/4] forward search Day %d first txn: %.2f", day, bal)
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
    is_desc: bool,
) -> Optional[float]:
    """
    4-step priority for Day 1:
      1. Transactions on Day 1 → closing balance of Day 1
      2a. Previous month closing balance
      2b. Statement opening balance row
      3/4. First transaction of earliest active day in month
    """
    day1 = date(year, month, 1)

    bal = get_last_transaction(month_txns, day1, is_desc)
    if bal is not None:
        logger.info("Day 1 [Step 1] %s: closing = %.2f", day1, bal)
        return bal

    bal = get_previous_month_balance(all_txns, year, month, is_desc)
    if bal is not None:
        logger.info("Day 1 [Step 2a] %s: prev month closing = %.2f", day1, bal)
        return bal

    bal = get_opening_balance(all_txns)
    if bal is not None:
        logger.info("Day 1 [Step 2b] %s: statement opening balance = %.2f", day1, bal)
        return bal

    bal = search_forward_for_first_transaction(month_txns, year, month, is_desc)
    if bal is not None:
        logger.info("Day 1 [Step 3/4] %s: forward search = %.2f", day1, bal)
        return bal

    logger.warning("Day 1 %s: no balance found", day1)
    return None


# ---------------------------------------------------------------------------
# Daily balance fill
# ---------------------------------------------------------------------------

def _fill_daily_from_txns(
    txns: Transactions, year: int, month: int, is_desc: bool
) -> dict[int, float]:
    """
    Build {day_number: closing_balance} for every day of the month.

    - Each day with transactions: closing balance = _closing(balances, is_desc)
    - Days without transactions: carry forward previous day's closing balance
    - Day 1 is overwritten afterward by get_day1_balance()
    """
    _, days_in_month = calendar.monthrange(year, month)
    filled: dict[int, float] = {}
    last_balance: Optional[float] = None

    for day in range(1, days_in_month + 1):
        d = date(year, month, day)
        bal = get_last_transaction(txns, d, is_desc)
        if bal is not None:
            last_balance = bal
            logger.debug(
                "Day %2d (%s): transaction found, closing=%.2f", day, d, bal
            )
        elif last_balance is not None:
            logger.debug(
                "Day %2d (%s): no transaction, carry-forward=%.2f", day, d, last_balance
            )
        if last_balance is not None:
            filled[day] = last_balance

    return filled


def _get_balance_with_fallback(filled: dict[int, float], target_day: int) -> Optional[float]:
    """
    Return balance for target_day.
    If not present, walk backward until one is found.
    Each series date searches independently — no value is propagated forward.
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
    Compute 5-Series (days 1,5,10,15,20,25,30) and 10-Series (days 1,10,20,30).

    Reads sort_order from the '__sort_order__' key embedded by normalize().
    Uses direction-aware closing balance throughout.
    """
    sample   = next(iter(month_txns))
    year, month = sample.year, sample.month

    # Read sort direction embedded by normalizer
    sort_order = all_txns.get(_SORT_ORDER_KEY, "asc")
    is_desc    = (sort_order == "desc")

    logger.info(
        "calculate_averages %d-%02d: sort_order=%s is_desc=%s",
        year, month, sort_order, is_desc,
    )

    # Build daily closing balance map
    filled = _fill_daily_from_txns(month_txns, year, month, is_desc)

    # Overwrite Day 1 with priority-based logic
    day1_bal = get_day1_balance(month_txns, all_txns, year, month, is_desc)
    if day1_bal is not None:
        filled[1] = day1_bal
        logger.debug("Day 1 overwritten: %.2f", day1_bal)

    # Log the full daily map for verification
    logger.debug("── Daily balance map ──")
    for day in sorted(filled):
        logger.debug("  %04d-%02d-%02d → %.2f", year, month, day, filled[day])

    dates_5s  = [1, 5, 10, 15, 20, 25, 30]
    dates_10s = [1, 10, 20, 30]

    selected_5s:  dict[str, float] = {}
    selected_10s: dict[str, float] = {}

    logger.debug("── Series selection ──")
    for d in dates_5s:
        bal = _get_balance_with_fallback(filled, d)
        if bal is not None:
            selected_5s[str(d)] = round(bal, 2)
            logger.debug("  5-Series Day %2d → %.2f", d, bal)

    for d in dates_10s:
        bal = _get_balance_with_fallback(filled, d)
        if bal is not None:
            selected_10s[str(d)] = round(bal, 2)
            logger.debug("  10-Series Day %2d → %.2f", d, bal)

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
