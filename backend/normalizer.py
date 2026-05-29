"""
normalizer.py — Transaction normalization layer.

Core principle (per Kotak descending format):
    Transactions are kept in EXACT PDF row order.
    The sort direction is detected and passed to the calculator.
    The calculator uses it to pick the correct closing balance index:

        ASCENDING  → closing balance = transactions[-1]  (last row = latest)
        DESCENDING → closing balance = transactions[0]   (first row = latest)

    For Kotak descending:
        Sl.1  30/06  103422  ← newest = closing balance → use [0]
        Sl.2  30/06  103417
        Sl.3  30/06   93417
        Sl.4  30/06   94985
        Sl.5  30/06  106265  ← oldest

    DO NOT reverse transactions. DO NOT reorder anything.
    Just detect direction and let the calculator pick the right index.

Flow:
    parse_pdf() → normalize() → group_by_month() → calculate_averages()
"""

import logging
from datetime import date

from parser import OPENING_BALANCE_KEY

logger = logging.getLogger(__name__)

# Type aliases
RawTransactions  = dict[date, list[float]]
NormTransactions = dict[date, list[float]]


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
    Compare the first date key seen in the PDF against the last date key seen.

    Python dicts preserve insertion order. The parser inserts date keys in the
    order rows are encountered, so keys[0] = first date in PDF,
    keys[-1] = last date in PDF.

    first_date > last_date  →  DESCENDING  (newest date printed first)
    first_date < last_date  →  ASCENDING   (oldest date printed first)

    Returns 'asc', 'desc', or 'single'.
    """
    keys = [d for d in raw if d != OPENING_BALANCE_KEY]
    if len(keys) < 2:
        return "single"

    first_seen = keys[0]
    last_seen  = keys[-1]
    order = "desc" if first_seen > last_seen else "asc"

    logger.info(
        "detect_sort_order: first_date_in_pdf=%s  last_date_in_pdf=%s  →  %s",
        first_seen, last_seen, order.upper(),
    )
    return order


# ---------------------------------------------------------------------------
# Normalize — keep PDF order, just pass sort_order through
# ---------------------------------------------------------------------------

def normalize(raw: RawTransactions, bank: str = "UNKNOWN") -> NormTransactions:
    """
    Return transactions in exact PDF row order with sort_order embedded.

    Transactions are NOT reordered. The sort_order is stored under the
    special key '__sort_order__' so the calculator can read it and pick
    the correct closing balance index per date:

        ASCENDING  → closing = txns[d][-1]
        DESCENDING → closing = txns[d][0]

    Per-date debug log shows raw balances and which one is selected as closing.
    """
    sort_order = detect_sort_order(raw)
    opening    = raw.get(OPENING_BALANCE_KEY)

    normalized: NormTransactions = {}

    for d, balances in raw.items():
        if d == OPENING_BALANCE_KEY:
            continue
        normalized[d] = balances  # exact PDF order, no changes

        # Debug: show raw balances and selected closing for this date
        closing = balances[0] if sort_order == "desc" else balances[-1]
        logger.debug(
            "Date: %s | statement_order: %s | raw_balances: %s | selected_closing: %.2f",
            d, sort_order.upper(),
            [round(b, 2) for b in balances],
            closing,
        )

    # Embed sort_order so calculator can read it without a separate argument
    normalized["__sort_order__"] = sort_order  # type: ignore[assignment]

    if opening is not None:
        normalized[OPENING_BALANCE_KEY] = opening

    real_dates = sorted(d for d in normalized
                        if d not in (OPENING_BALANCE_KEY, "__sort_order__"))
    total_txns = sum(len(normalized[d]) for d in real_dates)

    logger.info(
        "normalize [bank=%s order=%s]: %d txns across %d dates | %s → %s",
        bank, sort_order, total_txns, len(real_dates),
        real_dates[0] if real_dates else "N/A",
        real_dates[-1] if real_dates else "N/A",
    )

    return normalized
