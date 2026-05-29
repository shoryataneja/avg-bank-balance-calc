"""
normalizer.py - Transaction normalization layer.

Converts raw {date: [balances-in-PDF-order]} into a structure where every
date's balance list is in true chronological order, regardless of whether
the source PDF is ascending or descending.

Core principle:
    Within a single date, transactions appear in the PDF in the same order
    as the overall statement direction. If the statement is descending
    (newest-first), then within each date the transactions are also listed
    newest-first and must be reversed to get chronological order.

    We detect the statement direction from the date key order (reliable),
    then apply a simple reverse for descending PDFs (correct and deterministic).
    No heuristics, no permutations.

Flow:
    parse_pdf() -> normalize() -> group_by_month() -> calculate_averages()
"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional
from collections import defaultdict

from parser import OPENING_BALANCE_KEY

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Transaction:
    """A single parsed transaction with its PDF provenance."""
    date: date
    balance: float
    pdf_row_index: int    # 0-based global row counter reflecting PDF position
    day_sequence: int = 0 # assigned after normalization: 0 = chronologically first


@dataclass
class DailyBalance:
    """Normalized summary for a single calendar day."""
    date: date
    first_balance: float   # chronologically FIRST transaction balance
    last_balance: float    # chronologically LAST transaction balance (closing)
    transaction_count: int


# Type aliases
RawTransactions  = dict[date, list[float]]  # parser output: PDF row order
NormTransactions = dict[date, list[float]]  # normalized: chronological order


# ---------------------------------------------------------------------------
# Bank detection
# ---------------------------------------------------------------------------

_BANK_SIGNATURES: dict[str, str] = {
    "hdfc bank":           "HDFC",
    "hdfc":                "HDFC",
    "kotak mahindra bank": "KOTAK",
    "kotak":               "KOTAK",
    "state bank of india": "SBI",
    "sbi":                 "SBI",
    "icici bank":          "ICICI",
    "axis bank":           "AXIS",
    "punjab national":     "PNB",
}


def detect_bank(pdf_text: str) -> str:
    """Scan PDF text for known bank signatures. Returns label or 'UNKNOWN'."""
    lower = pdf_text.lower()
    for signature, label in _BANK_SIGNATURES.items():
        if signature in lower:
            logger.info("Bank detected: %s (matched '%s')", label, signature)
            return label
    logger.info("Bank detected: UNKNOWN")
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Sort-direction detection
# ---------------------------------------------------------------------------

def detect_sort_order(raw: RawTransactions) -> str:
    """
    Determine whether the PDF presents dates in ascending or descending order
    by inspecting the insertion order of date keys (which reflects PDF row order).

    Returns 'asc', 'desc', or 'single'.

    This is reliable because date keys are inserted in the order rows are
    encountered in the PDF. If the first date key is later than the last,
    the PDF is descending.
    """
    keys = [d for d in raw if d != OPENING_BALANCE_KEY]
    if len(keys) < 2:
        return "single"

    # Count consecutive ascending vs descending date pairs
    asc_pairs  = sum(1 for a, b in zip(keys, keys[1:]) if a <= b)
    desc_pairs = sum(1 for a, b in zip(keys, keys[1:]) if a >= b)
    order = "desc" if desc_pairs > asc_pairs else "asc"

    real_dates = sorted(keys)
    logger.info(
        "Statement order detected: %s | first key=%s | last key=%s | date range %s to %s",
        order.upper(), keys[0], keys[-1], real_dates[0], real_dates[-1],
    )
    return order


# ---------------------------------------------------------------------------
# Core normalization
# ---------------------------------------------------------------------------

def normalize(raw: RawTransactions, bank: str = "UNKNOWN") -> NormTransactions:
    """
    Convert raw parser output into a NormTransactions dict where every date's
    balance list is in true chronological order (oldest transaction first).

    Algorithm:
    1. Detect statement direction (asc or desc) from date key order.
    2. Expand {date: [balances]} into flat Transaction objects with pdf_row_index.
    3. Sort all transactions by date ascending (unambiguous — dates are absolute).
    4. Within each date, sort by pdf_row_index:
         - Ascending PDF:  lower pdf_row_index = earlier transaction -> sort ASC
         - Descending PDF: lower pdf_row_index = later transaction   -> sort DESC
           (because the whole PDF is reversed, so the first row of a date in a
            descending PDF is the LAST transaction of that day chronologically)
    5. Assign day_sequence (0 = first, N-1 = last/closing).
    6. Re-group into {date: [balances in chronological order]}.
    7. Log per-day transaction details for validation.

    After normalization:
        txns[d][0]  = FIRST transaction of day d  (chronologically earliest)
        txns[d][-1] = LAST  transaction of day d  (closing balance)
    """
    opening    = raw.get(OPENING_BALANCE_KEY)
    sort_order = detect_sort_order(raw)
    is_desc    = (sort_order == "desc")

    # ── Step 1: Expand into flat Transaction list ────────────────────────────
    all_txns: list[Transaction] = []
    pdf_row = 0
    for d, balances in raw.items():
        if d == OPENING_BALANCE_KEY:
            continue
        for bal in balances:
            all_txns.append(Transaction(
                date=d,
                balance=bal,
                pdf_row_index=pdf_row,
            ))
            pdf_row += 1

    # ── Step 2: Group by date ────────────────────────────────────────────────
    by_date: dict[date, list[Transaction]] = defaultdict(list)
    for txn in all_txns:
        by_date[txn.date].append(txn)

    # ── Step 3: Order each day's transactions chronologically ────────────────
    #
    # Key insight: within a single date, transactions appear in the PDF in the
    # same direction as the overall statement.
    #
    # Ascending PDF (e.g. Kotak):
    #   Date rows appear oldest-first. Within a date, pdf_row_index increases
    #   with time. Sort ASC by pdf_row_index -> chronological order.
    #
    # Descending PDF (e.g. HDFC):
    #   Date rows appear newest-first. Within a date, pdf_row_index increases
    #   going BACKWARD in time. Sort DESC by pdf_row_index -> chronological order.
    #   (Equivalently: sort ASC then reverse.)
    #
    ordered_txns: list[Transaction] = []

    for d in sorted(by_date.keys()):
        day_txns = sorted(by_date[d], key=lambda t: t.pdf_row_index, reverse=is_desc)

        # Assign day_sequence: 0 = chronologically first, N-1 = chronologically last
        for seq, txn in enumerate(day_txns):
            txn.day_sequence = seq

        ordered_txns.extend(day_txns)

        # ── Per-day validation log ───────────────────────────────────────────
        logger.debug("Date: %s | Transactions Found:", d)
        for txn in day_txns:
            logger.debug("  Txn %d -> Balance %.2f", txn.day_sequence + 1, txn.balance)
        logger.debug(
            "  Detected FIRST: %.2f | Detected LAST: %.2f",
            day_txns[0].balance, day_txns[-1].balance,
        )

    # ── Step 4: Re-group into NormTransactions ───────────────────────────────
    normalized: NormTransactions = {}
    for txn in ordered_txns:
        normalized.setdefault(txn.date, []).append(txn.balance)

    if opening is not None:
        normalized[OPENING_BALANCE_KEY] = opening

    # ── Summary log ─────────────────────────────────────────────────────────
    real_dates = sorted(d for d in normalized if d != OPENING_BALANCE_KEY)
    total_txns = sum(len(v) for k, v in normalized.items() if k != OPENING_BALANCE_KEY)
    logger.info(
        "normalize [bank=%s, order=%s]: %d transactions | %d dates | %s to %s",
        bank, sort_order, total_txns, len(real_dates),
        real_dates[0] if real_dates else "N/A",
        real_dates[-1] if real_dates else "N/A",
    )
    return normalized


# ---------------------------------------------------------------------------
# Daily balance summary
# ---------------------------------------------------------------------------

def build_daily_summary(normalized: NormTransactions) -> dict[date, DailyBalance]:
    """
    Build a {date: DailyBalance} map from normalized transactions.
    first_balance and last_balance are always chronologically correct after normalize().
    """
    summary: dict[date, DailyBalance] = {}
    for d, balances in normalized.items():
        if d == OPENING_BALANCE_KEY:
            continue
        summary[d] = DailyBalance(
            date=d,
            first_balance=balances[0],
            last_balance=balances[-1],
            transaction_count=len(balances),
        )
    return summary
