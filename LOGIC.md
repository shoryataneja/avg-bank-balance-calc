# LOGIC.md — Average Bank Balance Calculator

A complete technical reference for how this application works, from PDF upload to final average output.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Tech Stack & Libraries](#2-tech-stack--libraries)
3. [Data Flow — End to End](#3-data-flow--end-to-end)
4. [Backend Modules](#4-backend-modules)
   - [parser.py](#41-parserpy)
   - [normalizer.py](#42-normalizerpy)
   - [calculator.py](#43-calculatorpy)
   - [utils.py](#44-utilspy)
   - [main.py](#45-mainpy)
5. [Frontend Modules](#5-frontend-modules)
6. [Average Calculation Rules](#6-average-calculation-rules)
   - [5 Series Average](#61-5-series-average)
   - [10 Series Average](#62-10-series-average)
   - [Closing Balance Rule](#63-closing-balance-rule)
   - [Daily Fill / Carry-Forward Rule](#64-daily-fill--carry-forward-rule)
   - [Backward Fallback Rule](#65-backward-fallback-rule)
   - [Day 1 Special Logic](#66-day-1-special-logic)
7. [Bank Detection & Sort Order Normalization](#7-bank-detection--sort-order-normalization)
8. [PDF Extraction Strategy](#8-pdf-extraction-strategy)
9. [API Reference](#9-api-reference)
10. [Edge Cases Handled](#10-edge-cases-handled)

---

## 1. System Overview

This application accepts a bank statement PDF, extracts all transaction rows from it, determines the closing balance for every calendar day of the statement month, and then computes two standard average bank balance metrics used by Indian banks — the **5 Series Average** and the **10 Series Average**.

The pipeline has four distinct stages:

```
PDF Upload
    │
    ▼
[parser.py]       — Extract raw {date: [balances]} from PDF tables or text
    │
    ▼
[normalizer.py]   — Detect bank, detect sort order, reverse descending PDFs
    │
    ▼
[calculator.py]   — Build daily balance map, apply Day 1 logic, compute averages
    │
    ▼
[main.py]         — Serve results via FastAPI; optionally export PDF via utils.py
```

---

## 2. Tech Stack & Libraries

### Backend

| Library | Version | Purpose |
|---|---|---|
| `fastapi` | 0.111.0 | REST API framework |
| `uvicorn` | 0.29.0 | ASGI server to run FastAPI |
| `python-multipart` | 0.0.9 | Multipart form parsing for file uploads |
| `pdfplumber` | 0.11.0 | PDF table extraction and text extraction |
| `pandas` | 2.2.2 | Available for data manipulation (imported in requirements) |
| `pypdf` | 4.2.0 | PDF utility / password-protected PDF support |
| `reportlab` | 4.2.0 | PDF report generation for the export feature |

**Language:** Python 3.11+

### Frontend

| Library | Version | Purpose |
|---|---|---|
| `react` | 19.x | UI framework |
| `react-dom` | 19.x | DOM rendering |
| `recharts` | 3.x | Chart components (available, used for balance visualization) |
| `vite` | 8.x | Build tool and dev server |
| `tailwindcss` | 3.x | Utility-first CSS styling |
| `postcss` | 8.x | CSS processing |
| `autoprefixer` | 10.x | CSS vendor prefixing |

**Language:** JavaScript (ES Modules, JSX)

---

## 3. Data Flow — End to End

```
1. User uploads PDF via UploadZone (drag-drop or click)
        │
        ▼
2. Frontend calls POST /upload (multipart/form-data: file + optional password)
        │
        ▼
3. parse_pdf() opens the PDF with pdfplumber
   → Tries table extraction first (extract_via_tables)
   → Falls back to regex line scan (extract_via_regex)
   → Falls back to word-level scan (extract_via_word_scan)
   → Returns: raw_txns = {date: [balances in PDF row order]}
        │
        ▼
4. detect_bank(pdf_text) scans text for known bank signatures → "KOTAK", "HDFC", etc.
        │
        ▼
5. detect_sort_order(raw_txns) checks date key insertion order → "asc" or "desc"
        │
        ▼
6. normalize(raw_txns, bank) reverses within-day transaction lists for descending PDFs
   → Returns: txns = {date: [balances in chronological order]}
        │
        ▼
7. group_by_month(txns) splits into {(year, month): {date: [balances]}}
        │
        ▼
8. For each month:
   a. _fill_daily_from_txns() → {day_number: closing_balance} using last txn per day + carry-forward
   b. get_day1_balance() → resolves Day 1 via 4-step priority logic
   c. _get_balance_with_fallback() → resolves each series date with backward walk
   d. calculate_averages() → returns average5, average10, selected_balances_5, selected_balances_10
        │
        ▼
9. Response JSON returned to frontend
        │
        ▼
10. Frontend renders SummaryCards (averages) + BreakdownTable (per-day selected balances)
        │
        ▼
11. Optional: user clicks Export PDF → POST /export-pdf → reportlab generates PDF report
```

---

## 4. Backend Modules

### 4.1 `parser.py`

Responsible for extracting raw transaction data from the PDF. Returns a dict of `{date: [list of balance floats in PDF row order]}`.

**Key functions:**

**`parse_pdf(file_bytes, password)`**
- Opens the PDF using `pdfplumber`
- Calls `extract_via_tables()` first
- If that returns nothing, calls `extract_via_regex()`
- If that also returns nothing, calls `extract_via_word_scan()`
- Raises `ValueError` if no data is found at all

**`extract_via_tables(pdf)`**
- Iterates every page and every table on that page
- Uses `_is_header_row()` to find the column header row — requires BOTH a date column AND a balance column to be present (prevents "Balance Brought Forward" rows from being mistaken for headers)
- Uses `detect_columns()` to map column names to indices
- Falls back to `_infer_columns_from_data()` if header detection fails
- For each data row: calls `parse_transaction_row()` to extract `(date, balance)`
- Opening balance rows (no date, description contains "opening" or "brought forward") are stored under the sentinel key `OPENING_BALANCE_KEY`
- Summary rows (closing balance, totals) are skipped via `_is_summary_row()`

**`extract_via_regex(pdf)`**
- Extracts raw text from each page
- Applies `_REGEX_LINE` pattern: matches lines starting with a date and ending with an amount
- Takes the last amount on each line as the balance

**`extract_via_word_scan(pdf)`**
- Uses `pdfplumber`'s word-level extraction
- Groups words by their vertical Y position (same line = same Y coordinate)
- Reconstructs each line, finds a date token, takes the last amount token as balance

**`detect_columns(headers)`**
- Scans header row cells for known keywords
- Date column: "date", "dt", "value date", "txn date", etc.
- Balance column: must contain "balance", must NOT contain withdrawal/deposit keywords, always takes the rightmost match
- Withdrawal column: "withdrawal", "debit", "dr.", etc.
- Deposit column: "deposit", "credit", "cr.", etc.

**`parse_amount(value)`**
- Strips commas, handles Indian number format (1,25,000.50)
- Handles CR/DR suffix — DR amounts are returned as negative

**`parse_date(value)`**
- Tries multiple formats: `%d/%m/%Y`, `%d-%m-%Y`, `%d/%m/%y`, `%d-%m-%y`, `%Y-%m-%d`, `%d %b %Y`, `%d %B %Y`, `%d-%b-%Y`, `%d-%b-%y`

---

### 4.2 `normalizer.py`

Converts raw parser output (PDF row order) into chronologically ordered transaction lists. This is the layer that makes descending PDFs (like HDFC) produce the same results as ascending PDFs.

**Key functions:**

**`detect_bank(pdf_text)`**
- Scans full PDF text for known bank name signatures
- Returns: `"HDFC"`, `"KOTAK"`, `"SBI"`, `"ICICI"`, `"AXIS"`, `"PNB"`, or `"UNKNOWN"`

**`detect_sort_order(raw_txns)`**
- Inspects the insertion order of date keys in the raw dict (which reflects PDF row order)
- Counts consecutive ascending vs descending date pairs
- Returns `"asc"`, `"desc"`, or `"single"`

**`normalize(raw_txns, bank)`**
- Expands `{date: [balances]}` into flat `Transaction` objects with `pdf_row_index`
- Groups by date
- For each date, sorts transactions by `pdf_row_index`:
  - Ascending PDF: sort ASC → lower index = earlier transaction
  - Descending PDF: sort DESC → higher index = earlier transaction (because the PDF is reversed)
- Re-groups into `{date: [balances in chronological order]}`
- After normalization: `txns[d][0]` = first transaction of day, `txns[d][-1]` = closing balance

**`Transaction` dataclass**
```
date: date
balance: float
pdf_row_index: int    # global row counter in PDF order
day_sequence: int     # 0 = chronologically first after normalization
```

---

### 4.3 `calculator.py`

Contains all the business logic for computing daily balances and averages.

**`group_by_month(all_txns)`**
- Splits `{date: [balances]}` into `{(year, month): {date: [balances]}}`
- Skips the `OPENING_BALANCE_KEY` sentinel

**`get_last_transaction(txns, d)`**
- Returns `txns[d][-1]` — the closing balance for a date
- Used for all normal date calculations

**`get_first_transaction_of_day(txns, d)`**
- Returns `txns[d][0]` — the opening state of a date
- Used ONLY in the Day 1 forward-search fallback

**`_fill_daily_from_txns(txns, year, month)`**
- Iterates every calendar day of the month (1 to N)
- For each day: if transactions exist, `last_balance = txns[d][-1]`; otherwise carry forward `last_balance`
- Returns `{day_number: closing_balance}` for every day that has a balance
- Day 1 is intentionally left to be overwritten by `get_day1_balance()`

**`_get_balance_with_fallback(filled, target_day)`**
- Returns `filled[target_day]` if it exists
- Otherwise walks backward (target_day - 1, target_day - 2, ...) until a day with a balance is found
- Used for all series date lookups except Day 1

**`get_day1_balance(month_txns, all_txns, year, month)`**
- 4-step priority logic (see Section 6.6)

**`calculate_averages(month_txns, all_txns)`**
- Calls `_fill_daily_from_txns()` to build the daily map
- Overwrites Day 1 with `get_day1_balance()`
- Resolves each series date using `_get_balance_with_fallback()`
- Computes and returns both averages

---

### 4.4 `utils.py`

**`format_inr(amount)`**
- Formats a float into Indian Rupee notation: `1,25,000.50`
- Handles the Indian grouping system (last 3 digits, then groups of 2)

**`build_pdf_report(payload)`**
- Uses `reportlab` to generate a multi-month PDF summary
- Includes summary table (5 Series Average, 10 Series Average) and per-day breakdown table for each month
- Returns raw bytes

---

### 4.5 `main.py`

FastAPI application with four endpoints:

| Endpoint | Method | Purpose |
|---|---|---|
| `/upload` | POST | Main pipeline: parse → normalize → calculate → return JSON |
| `/export-pdf` | POST | Accept result JSON, return downloadable PDF report |
| `/health` | GET | Health check |
| `/debug-pdf` | POST | Full pipeline diagnostic with raw table dump, normalization output, daily timeline, and final averages |
| `/audit` | POST | Kotak-specific audit mode — prints every stage (raw extraction, date grouping, closing balance map, daily fill, series selection) with source tracing |

---

## 5. Frontend Modules

### `src/services/api.js`
- `uploadStatement(file, password)` — POSTs to `/upload`, returns result JSON
- `exportPDF(result)` — POSTs to `/export-pdf`, triggers browser download

### `src/pages/Home.jsx`
- Main page component
- Manages state: `file`, `password`, `loading`, `error`, `result`, `exporting`
- Renders `UploadZone`, password toggle, upload button, error display, and per-month `MonthCard` components

### `src/components/UploadZone.jsx`
- Drag-and-drop + click-to-browse PDF upload area
- Accepts only `.pdf` files
- Calls `onFile(File)` prop on selection

### `src/components/SummaryCards.jsx`
- Displays 5 Series Average and 10 Series Average as gradient cards
- `formatINR(amount)` uses `Intl.NumberFormat` with `en-IN` locale and INR currency

### `src/components/BreakdownTable.jsx`
- Side-by-side tables showing the selected balance for each date in the 5 Series and 10 Series
- Displays `—` for any date where no balance was resolved

---

## 6. Average Calculation Rules

### 6.1 5 Series Average

**Selected dates:** 1, 5, 10, 15, 20, 25, 30

**Formula:**
```
5 Series Average = (Balance_1 + Balance_5 + Balance_10 + Balance_15 + Balance_20 + Balance_25 + Balance_30) / 7
```

The divisor is always 7, regardless of how many dates actually had transactions. If a date has no transaction, the backward fallback rule applies (see Section 6.5).

---

### 6.2 10 Series Average

**Selected dates:** 1, 10, 20, 30

**Formula:**
```
10 Series Average = (Balance_1 + Balance_10 + Balance_20 + Balance_30) / 4
```

The divisor is always 4. Same fallback rules apply.

---

### 6.3 Closing Balance Rule

When a date has multiple transactions, the **last transaction's balance** is used as the closing balance for that date.

```
Example — June 30 has 5 transactions:
  Txn 1: 1,06,265.24  ← oldest (first chronologically)
  Txn 2:    94,985.24
  Txn 3:    93,417.24
  Txn 4: 1,03,417.24
  Txn 5: 1,03,422.24  ← most recent (closing balance) ✓
```

This is implemented in `get_last_transaction()` which returns `txns[d][-1]` after normalization ensures chronological order.

---

### 6.4 Daily Fill / Carry-Forward Rule

Days with no transaction inherit the **previous day's closing balance**.

```
Example:
  June 5  → transaction exists → closing balance = 15,000.00
  June 6  → no transaction     → balance = 15,000.00 (carried from June 5)
  June 7  → no transaction     → balance = 15,000.00 (carried from June 5)
  June 8  → transaction exists → closing balance = 18,500.00
  June 9  → no transaction     → balance = 18,500.00 (carried from June 8)
```

This is implemented in `_fill_daily_from_txns()`.

---

### 6.5 Backward Fallback Rule

When a series date (e.g. the 25th) has no balance in the filled map, the system walks **backward** day by day until it finds a day that does have a balance.

```
Example:
  Day 25 → not in filled map
  Day 24 → not in filled map
  Day 23 → balance = 12,000.00 ✓ → use this for Day 25
```

This is implemented in `_get_balance_with_fallback()`. Note: because `_fill_daily_from_txns()` already applies carry-forward, this fallback is mainly relevant for months where the statement starts mid-month (e.g. no transactions before the 10th).

---

### 6.6 Day 1 Special Logic

Day 1 requires special handling because it cannot use the backward fallback (there is no Day 0). The system uses a 4-step priority order:

**Step 1 — Transactions exist on Day 1:**
Use the last transaction balance of Day 1 (standard closing balance).

**Step 2a — No Day 1 transactions, previous month available:**
Walk backward from the last day of the previous month and use the last transaction balance of the most recent day that has transactions. This is the natural carry-forward from the prior month.

**Step 2b — No previous month data, opening balance in statement:**
Some bank statements print an explicit "Opening Balance" row with no date. The parser stores this under `OPENING_BALANCE_KEY`. Use the last such value.

**Step 3/4 — No prior context at all:**
Search forward from Day 2 within the same month. Use the **first** transaction of the first day found. The first transaction represents the balance before any activity on that day — the best available proxy for what the balance was on Day 1.

```
Priority order:
  Day 1 transactions exist?          → use last txn of Day 1
  Previous month has transactions?   → use last txn of previous month's last active day
  Statement has opening balance row? → use that value
  Any transaction in the month?      → use first txn of the earliest active day
  Nothing found?                     → Day 1 balance = None
```

---

## 7. Bank Detection & Sort Order Normalization

### Why this is needed

Different banks print statements in different orders:
- **Kotak (ascending):** oldest transactions first, newest last
- **HDFC (descending):** newest transactions first, oldest last
- **Kotak (descending):** some Kotak statements are also descending

If a descending PDF is processed without reversal, the "last" transaction of a date in the list is actually the **oldest** transaction, not the closing balance. This produces wrong results.

### How it works

1. `detect_sort_order()` counts consecutive ascending vs descending date pairs in the raw dict key order (which reflects PDF row order). Returns `"asc"` or `"desc"`.

2. `normalize()` expands all transactions into flat objects with a `pdf_row_index` (global counter in PDF order). For each date:
   - Ascending PDF: sort by `pdf_row_index` ASC → lower index = earlier transaction
   - Descending PDF: sort by `pdf_row_index` DESC → higher index = earlier transaction

3. After normalization, `txns[d][-1]` is always the chronologically last (closing) transaction regardless of the original PDF direction.

---

## 8. PDF Extraction Strategy

Three extraction methods are tried in order:

### Method 1: Table Extraction (`extract_via_tables`)
Uses `pdfplumber`'s `extract_tables()`. Best accuracy for structured PDFs with clear table borders. Detects the header row using `_is_header_row()` which requires both a date column and a balance column to be present simultaneously — this prevents rows like "Balance Brought Forward" from being mistaken for the table header.

### Method 2: Regex Line Scan (`extract_via_regex`)
Uses `pdfplumber`'s `extract_text()` and scans each line with a regex pattern that matches a date at the start and an amount at the end. Used when table extraction fails (e.g. borderless tables, text-only PDFs).

### Method 3: Word-Level Scan (`extract_via_word_scan`)
Uses `pdfplumber`'s `extract_words()` which returns individual word bounding boxes. Groups words by their Y coordinate to reconstruct lines, then applies the same date + last-amount logic. Used when `extract_text()` merges columns incorrectly.

---

## 9. API Reference

### `POST /upload`
**Request:** `multipart/form-data` with `file` (PDF) and optional `password` (string)

**Response:**
```json
{
  "months": [
    {
      "average5": 15220.50,
      "average10": 14110.00,
      "selected_balances_5": {"1": 12000.00, "5": 15000.00, "10": 18000.00, "15": 14000.00, "20": 16000.00, "25": 13500.00, "30": 17500.00},
      "selected_balances_10": {"1": 12000.00, "10": 18000.00, "20": 16000.00, "30": 17500.00},
      "month": "June",
      "year": 2021
    }
  ],
  "bank": "KOTAK",
  "sort_order": "desc"
}
```

### `POST /export-pdf`
**Request:** JSON body — the full result object from `/upload`
**Response:** Binary PDF file download

### `GET /health`
**Response:** `{"status": "ok"}`

### `POST /debug-pdf`
Full pipeline diagnostic. Returns raw table dump, normalized transactions, daily timeline, and final averages. Useful for debugging extraction issues.

### `POST /audit`
Kotak-specific audit mode. Returns 5 stages:
- `stage_A_raw_extraction` — every transaction with PDF row number
- `stage_B_date_grouping` — per-date transaction list with first/last selection
- `stage_C_closing_balance_per_date` — only dates with real transactions
- `stage_D_daily_balance_fill` — every day of month with source (transaction vs carry-forward)
- `stage_E_series_selection` — each series date with balance used, source date, and whether fallback was triggered

---

## 10. Edge Cases Handled

| Edge Case | Handling |
|---|---|
| Multiple transactions on the same date | Last transaction = closing balance |
| Days with no transactions | Carry-forward from previous day |
| February (28 or 29 days) | `calendar.monthrange()` used everywhere — never hardcodes month length |
| Missing 30th (e.g. February) | Backward fallback from Day 30 finds Day 28/29 |
| Descending PDFs (HDFC, some Kotak) | `normalize()` reverses within-day transaction order |
| Password-protected PDFs | `pdfplumber.open(password=...)` |
| Opening balance row with no date | Stored under `OPENING_BALANCE_KEY`, used as Day 1 fallback |
| "Balance Brought Forward" rows | Detected by `_is_summary_row()` and skipped |
| "Closing Balance" rows | Detected by `_is_summary_row()` and skipped |
| Table extraction fails | Falls back to regex, then word-scan |
| Image-based / scanned PDFs | Raises a clear error message (pdfplumber cannot OCR) |
| Multi-month statements | `group_by_month()` splits and calculates each month independently |
| Indian number format (1,25,000.50) | `parse_amount()` strips commas before parsing |
| CR / DR suffix on balances | `parse_amount()` handles — DR returns negative value |
