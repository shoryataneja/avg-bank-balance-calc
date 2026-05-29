import re
import io
import logging
from datetime import date
from typing import Optional
import pdfplumber

logger = logging.getLogger(__name__)

# Sentinel key used to store opening balance rows that have no date.
# The calculator reads this to use as a Day 1 fallback.
OPENING_BALANCE_KEY = "__opening_balance__"

# ---------------------------------------------------------------------------
# Amount and date parsing
# ---------------------------------------------------------------------------

# Matches Indian/standard currency: 1,25,000.50 or 93,003.03 (with optional CR/DR)
_AMOUNT_RE = re.compile(r"^-?[\d,]+\.\d{2}\s*(?:CR|DR)?$", re.IGNORECASE)


def parse_amount(value: str) -> Optional[float]:
    """Parse Indian/standard number formats like 1,25,000.50 or 1000.00 CR/DR."""
    if not value:
        return None
    v = value.strip().upper().replace(",", "")
    is_dr = v.endswith("DR")
    v = re.sub(r"(CR|DR)$", "", v).strip()
    try:
        amount = float(v)
        return -amount if is_dr else amount
    except ValueError:
        return None


def is_valid_amount(value: str) -> bool:
    """Return True if the cell looks like a currency amount."""
    return bool(value and _AMOUNT_RE.match(value.strip()))


def parse_date(value: str) -> Optional[date]:
    """Try multiple date formats and return a date object or None."""
    formats = [
        "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y",
        "%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%b-%y",
    ]
    value = value.strip()
    for fmt in formats:
        try:
            import datetime
            return datetime.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Column detection
# ---------------------------------------------------------------------------

_DATE_KEYWORDS     = ("date", "dt", "value date", "txn date", "trans date", "value\ndate", "tran date")
_WITHDRAW_KEYWORDS = ("withdrawal", "debit", "dr.", "dr)", "withdrawl", "debit amount", "dr amount")
_DEPOSIT_KEYWORDS  = ("deposit", "credit", "cr.", "cr)", "credit amount", "cr amount")
_DESC_KEYWORDS     = ("description", "narration", "particulars", "details", "remarks", "transaction")


def detect_columns(headers: list[str]) -> dict[str, Optional[int]]:
    """
    Scan the header row and return a dict of column indices:
        {date, balance, withdrawal, deposit, description}
    """
    cols: dict[str, Optional[int]] = {
        "date": None, "balance": None,
        "withdrawal": None, "deposit": None, "description": None,
    }

    for i, h in enumerate(headers):
        h_lower = (h or "").lower().strip()

        if cols["date"] is None and any(k in h_lower for k in _DATE_KEYWORDS):
            cols["date"] = i

        if cols["description"] is None and any(k in h_lower for k in _DESC_KEYWORDS):
            cols["description"] = i

        if any(k in h_lower for k in _WITHDRAW_KEYWORDS):
            cols["withdrawal"] = i

        if any(k in h_lower for k in _DEPOSIT_KEYWORDS):
            cols["deposit"] = i

        # Balance: must contain 'balance', must NOT be a withdrawal/deposit cell.
        # Always overwrite — keeps the LAST (rightmost) balance column.
        if "balance" in h_lower and not any(k in h_lower for k in _WITHDRAW_KEYWORDS + _DEPOSIT_KEYWORDS):
            cols["balance"] = i

    logger.debug("detect_columns → %s from headers %s", cols, headers)
    return cols


def _infer_columns_from_data(table: list[list]) -> dict[str, Optional[int]]:
    """
    Heuristic fallback when no header row is found.
    Scans the first few data rows to locate date and balance columns.
    Balance is taken as the LAST column that consistently contains amounts.
    """
    date_pattern   = re.compile(r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{1,2}\s+\w{3}\s+\d{4}")
    amount_pattern = re.compile(r"[\d,]+\.\d{2}")

    date_idx: Optional[int] = None
    amount_cols: dict[int, int] = {}   # col_index → hit count

    for row in table[:15]:
        for i, cell in enumerate(row or []):
            cell = cell or ""
            if date_idx is None and date_pattern.search(cell):
                date_idx = i
            if amount_pattern.search(cell):
                amount_cols[i] = amount_cols.get(i, 0) + 1

    # Balance = rightmost column that had amounts in multiple rows
    bal_idx: Optional[int] = None
    if amount_cols:
        # Filter to columns seen in at least 2 rows, then take the rightmost
        candidates = [c for c, cnt in amount_cols.items() if cnt >= 2]
        bal_idx = max(candidates) if candidates else max(amount_cols)

    logger.debug("_infer_columns_from_data → date=%s balance=%s", date_idx, bal_idx)
    return {"date": date_idx, "balance": bal_idx, "withdrawal": None, "deposit": None}


# ---------------------------------------------------------------------------
# Row parsing
# ---------------------------------------------------------------------------

def get_balance_value(row: list[str], bal_idx: int) -> Optional[float]:
    """
    Extract the balance from the confirmed balance column index.
    Returns None if the cell is empty or not a valid amount.
    This is the ONLY function that should be used to read balance values —
    withdrawal and deposit columns are never touched here.
    """
    if bal_idx >= len(row):
        return None
    cell = (row[bal_idx] or "").strip()
    if not is_valid_amount(cell):
        return None
    return parse_amount(cell)


def parse_transaction_row(
    row: list[str],
    cols: dict[str, Optional[int]],
) -> tuple[Optional[date], Optional[float]]:
    """
    Extract (date, balance) from a single table row.

    Validation rules:
    - Row must be long enough to reach the balance column.
    - Date cell must parse to a valid date (skips continuation/description rows).
    - Balance cell must be a valid amount (skips subtotal/header rows).
    """
    date_idx = cols["date"]
    bal_idx  = cols["balance"]

    if date_idx is None or bal_idx is None:
        return None, None
    if len(row) <= max(date_idx, bal_idx):
        return None, None

    d = parse_date(row[date_idx] or "")
    if d is None:
        # Empty date cell = multiline description continuation row — skip it
        return None, None

    b = get_balance_value(row, bal_idx)
    return d, b


# ---------------------------------------------------------------------------
# Table-based extraction
# ---------------------------------------------------------------------------

def extract_via_tables(pdf) -> dict[date, list[float]]:
    """
    Primary extraction path.
    For each page, extract all tables, detect the header row, identify the
    Balance column index, then parse every transaction row.

    Key guarantee: ONLY the Balance column value is ever recorded.
    Withdrawal (Dr.) and Deposit (Cr.) columns are identified but ignored.

    Also detects opening balance rows (rows whose description contains
    'opening balance' and have no date) and stores them under the special
    key OPENING_BALANCE_KEY so the calculator can use them for Day 1 fallback.
    """
    daily: dict[date, list[float]] = {}

    for page_num, page in enumerate(pdf.pages, start=1):
        tables = page.extract_tables()
        if not tables:
            logger.debug("Page %d: no tables found", page_num)
            continue

        for tbl_num, table in enumerate(tables, start=1):
            if not table or len(table) < 2:
                continue

            # --- Locate header row ---
            # The header row is the first row that contains a cell with 'balance'
            # (case-insensitive). Fall back to the first non-empty row.
            header_row_idx = 0
            for i, row in enumerate(table):
                if row and any("balance" in (c or "").lower() for c in row):
                    header_row_idx = i
                    break

            header_row = table[header_row_idx]
            cols = detect_columns([c or "" for c in header_row])

            # If header detection failed, try heuristic inference on data rows
            if cols["date"] is None or cols["balance"] is None:
                cols = _infer_columns_from_data(table)

            if cols["date"] is None or cols["balance"] is None:
                logger.debug(
                    "Page %d table %d: could not detect date/balance columns, skipping",
                    page_num, tbl_num,
                )
                continue

            logger.debug(
                "Page %d table %d: headers=%s | date_col=%s balance_col=%s",
                page_num, tbl_num,
                [c or "" for c in header_row],
                cols["date"], cols["balance"],
            )

            # --- Parse data rows (everything after the header row) ---
            for row in table[header_row_idx + 1:]:
                # Check for opening balance row: description contains 'opening'
                # and date cell is empty — store under sentinel key
                desc_idx = cols.get("description")
                date_cell = (row[cols["date"]] or "").strip() if cols["date"] is not None and cols["date"] < len(row) else ""
                desc_cell = (row[desc_idx] or "").lower() if desc_idx is not None and desc_idx < len(row) else ""

                if not date_cell and "opening" in desc_cell:
                    b = get_balance_value(row, cols["balance"])
                    if b is not None:
                        daily.setdefault(OPENING_BALANCE_KEY, []).append(b)
                        logger.debug("  opening balance row detected: %.2f", b)
                    continue

                d, b = parse_transaction_row(row, cols)
                if d is not None and b is not None:
                    daily.setdefault(d, []).append(b)
                    logger.debug("  row date=%s balance=%.2f", d, b)

    return daily


# ---------------------------------------------------------------------------
# Regex fallback extraction
# ---------------------------------------------------------------------------

# Kotak-style line pattern:
#   <date>  <description>  <ref>  [withdrawal]  [deposit]  <balance>
#
# The balance is the LAST amount on the line.
# To avoid picking up withdrawal/deposit as balance we require the line to
# contain at least one date AND end with an amount that is preceded by
# at least one other amount (i.e. there are multiple amounts on the line).
_DATE_PAT   = r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{1,2}\s+\w{3}\s+\d{4})"
_AMOUNT_PAT = r"[\d,]+\.\d{2}\s*(?:CR|DR)?"

# Matches a line that starts with a date and ends with an amount (the balance).
# We no longer require two amounts on the line because HDFC rows often have
# only the balance when withdrawal/deposit is blank.
_REGEX_LINE = re.compile(
    _DATE_PAT
    + r".*?(" + _AMOUNT_PAT + r")\s*$",
    re.IGNORECASE,
)


def extract_via_regex(pdf) -> dict[date, list[float]]:
    """
    Fallback when table extraction yields nothing.
    Scans raw text lines; takes the LAST amount on each line as the balance.
    """
    daily: dict[date, list[float]] = {}
    for page_num, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        for line in text.splitlines():
            m = _REGEX_LINE.search(line)
            if not m:
                continue
            d = parse_date(m.group(1))
            b = parse_amount(m.group(2))
            if d and b is not None:
                daily.setdefault(d, []).append(b)
                logger.debug("regex page %d: date=%s balance=%.2f | line: %s", page_num, d, b, line[:80])
    return daily


# Matches any standalone amount token (used in word-scan fallback)
_WORD_AMOUNT_RE = re.compile(r"^-?[\d,]+\.\d{2}$")


def extract_via_word_scan(pdf) -> dict[date, list[float]]:
    """
    Last-resort fallback using pdfplumber word-level extraction.
    Groups words by their vertical position (same line = same y-coordinate),
    reconstructs rows, then applies the same date + last-amount logic.
    Handles PDFs where extract_text() merges columns incorrectly.
    """
    daily: dict[date, list[float]] = {}

    for page_num, page in enumerate(pdf.pages, start=1):
        words = page.extract_words() or []
        if not words:
            continue

        # Group words into lines by rounding their top-y coordinate
        lines_map: dict[int, list[str]] = {}
        for w in words:
            y_key = round(float(w.get("top", 0)))
            lines_map.setdefault(y_key, []).append(w["text"])

        for y_key in sorted(lines_map):
            tokens = lines_map[y_key]
            line_str = " ".join(tokens)

            # Need at least a date token somewhere in the line
            d = None
            for tok in tokens:
                d = parse_date(tok)
                if d:
                    break
            if d is None:
                continue

            # Last amount token on the line = balance
            b = None
            for tok in reversed(tokens):
                clean = tok.replace(",", "")
                if _WORD_AMOUNT_RE.match(clean):
                    b = parse_amount(tok)
                    break
            if b is not None:
                daily.setdefault(d, []).append(b)
                logger.debug("word-scan page %d: date=%s balance=%.2f", page_num, d, b)

    return daily


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_pdf(
    file_bytes: bytes, password: Optional[str] = None
) -> tuple[dict[date, list[float]], str]:
    """
    Parse a bank statement PDF.

    Returns:
        (raw_transactions, pdf_text)

        raw_transactions: {date: [balances in PDF row order]}
            Balances are stored in the order they appeared in the PDF.
            IMPORTANT: this is raw/unsorted — call normalizer.normalize()
            before passing to the calculator so that ascending and descending
            PDFs (e.g. HDFC) produce identical results.

        pdf_text: full concatenated text of all pages, used for bank detection.

    Strategy:
    1. Table extraction with strict Balance-column detection (primary).
    2. Regex line scanning with multi-amount guard (fallback).
    """
    open_kwargs: dict = {"password": password} if password else {}

    try:
        with pdfplumber.open(io.BytesIO(file_bytes), **open_kwargs) as pdf:
            pdf_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            daily = extract_via_tables(pdf)
            if not daily:
                logger.info("Table extraction yielded no results, trying regex fallback")
                daily = extract_via_regex(pdf)
            if not daily:
                logger.info("Regex fallback yielded no results, trying word-scan fallback")
                daily = extract_via_word_scan(pdf)
    except Exception as exc:
        raise ValueError(f"Could not open PDF: {exc}") from exc

    if not daily:
        raise ValueError(
            "No transaction data found in the PDF. "
            "The file may be image-based (scanned), encrypted, or in an unsupported format. "
            "Try the /debug-pdf endpoint to inspect what pdfplumber can extract."
        )

    real_dates = [d for d in daily if d != OPENING_BALANCE_KEY]
    logger.info(
        "parse_pdf complete: %d unique dates, date range %s → %s",
        len(real_dates),
        min(real_dates) if real_dates else "N/A",
        max(real_dates) if real_dates else "N/A",
    )
    return daily, pdf_text
