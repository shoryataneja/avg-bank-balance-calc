from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from typing import Optional
import calendar
import io
import pdfplumber

from parser import parse_pdf, detect_columns, _infer_columns_from_data, OPENING_BALANCE_KEY
from normalizer import detect_bank, detect_sort_order, normalize
from calculator import calculate_averages, group_by_month
from utils import build_pdf_report

app = FastAPI(title="Average Bank Balance Calculator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/upload")
async def upload_statement(
    file: UploadFile = File(...),
    password: Optional[str] = Form(None),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # ── 1. Parse raw transactions from PDF ───────────────────────────────────
    try:
        raw_txns, pdf_text = parse_pdf(contents, password=password or None)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # ── 2. Detect bank format and sort order, then normalize ─────────────────
    bank       = detect_bank(pdf_text)
    sort_order = detect_sort_order(raw_txns)
    txns       = normalize(raw_txns, bank=bank)

    # ── 3. Group by month and calculate averages ─────────────────────────────
    monthly_groups = group_by_month(txns)
    results = []
    for (year, month), month_txns in monthly_groups.items():
        data = calculate_averages(month_txns, txns)
        data["month"] = calendar.month_name[month]
        data["year"]  = year
        results.append(data)

    return {
        "months":     results,
        "bank":       bank,
        "sort_order": sort_order,
    }


@app.post("/export-pdf")
async def export_pdf(payload: dict):
    """Generate and return a PDF report from a previously computed result."""
    try:
        pdf_bytes = build_pdf_report(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=bank_balance_report.pdf"},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/debug-pdf")
async def debug_pdf(
    file: UploadFile = File(...),
    password: Optional[str] = Form(None),
):
    """
    Full pipeline diagnostic — shows every stage of extraction and calculation.
    POST your PDF here to see exactly what is being extracted and why.
    """
    contents = await file.read()
    open_kwargs = {"password": password} if password else {}
    out: dict = {}

    # ── STAGE 0: raw pdfplumber table dump (first 2 pages) ───────────────────
    out["stage0_raw_tables"] = []
    try:
        with pdfplumber.open(io.BytesIO(contents), **open_kwargs) as pdf:
            out["total_pages"] = len(pdf.pages)
            for i, page in enumerate(pdf.pages[:2], start=1):
                page_info: dict = {"page": i, "text_sample": "", "tables": []}
                page_info["text_sample"] = (page.extract_text() or "")[:400]
                for j, tbl in enumerate(page.extract_tables() or []):
                    if not tbl:
                        continue
                    page_info["tables"].append({
                        "table_index": j,
                        "row_count": len(tbl),
                        "all_rows": tbl,
                    })
                out["stage0_raw_tables"].append(page_info)
    except Exception as e:
        out["stage0_error"] = str(e)
        return out

    # ── STAGE 1: raw extraction ───────────────────────────────────────────────
    try:
        raw_txns, pdf_text = parse_pdf(contents, password=password or None)
        out["stage1_bank"]       = detect_bank(pdf_text)
        out["stage1_sort_order"] = detect_sort_order(raw_txns)
        out["stage1_raw_dates"]  = [
            {"date": str(d), "balances": v}
            for d, v in sorted(
                ((d, v) for d, v in raw_txns.items() if d != OPENING_BALANCE_KEY),
                key=lambda x: x[0]
            )
        ]
        out["stage1_total_dates"]  = len(out["stage1_raw_dates"])
        out["stage1_opening_bal"]  = raw_txns.get(OPENING_BALANCE_KEY)
    except Exception as e:
        out["stage1_error"] = str(e)
        return out

    # ── STAGE 2: normalize ────────────────────────────────────────────────────
    try:
        txns = normalize(raw_txns, bank=out["stage1_bank"])
        out["stage2_normalized"] = [
            {"date": str(d), "balances": v,
             "first": v[0], "last": v[-1], "count": len(v)}
            for d, v in sorted(
                ((d, v) for d, v in txns.items() if d != OPENING_BALANCE_KEY),
                key=lambda x: x[0]
            )
        ]
    except Exception as e:
        out["stage2_error"] = str(e)
        return out

    # ── STAGE 3: monthly groups + daily timeline ──────────────────────────────
    try:
        from calculator import _fill_daily_from_txns, get_day1_balance
        monthly_groups = group_by_month(txns)
        out["stage3_months"] = []
        for (year, month), month_txns in monthly_groups.items():
            filled = _fill_daily_from_txns(month_txns, year, month)
            d1 = get_day1_balance(month_txns, txns, year, month)
            if d1 is not None:
                filled[1] = d1
            out["stage3_months"].append({
                "month": f"{calendar.month_name[month]} {year}",
                "dates_in_group": [str(d) for d in sorted(month_txns.keys())],
                "daily_timeline": {str(k): round(v, 2) for k, v in sorted(filled.items())},
            })
    except Exception as e:
        out["stage3_error"] = str(e)
        return out

    # ── STAGE 4: final averages ───────────────────────────────────────────────
    try:
        results = []
        for (year, month), month_txns in monthly_groups.items():
            data = calculate_averages(month_txns, txns)
            data["month"] = calendar.month_name[month]
            data["year"]  = year
            results.append(data)
        out["stage4_results"] = results
    except Exception as e:
        out["stage4_error"] = str(e)

    return out


@app.post("/audit")
async def audit_statement(
    file: UploadFile = File(...),
    password: Optional[str] = Form(None),
):
    """
    Kotak descending-statement audit mode.

    Prints every stage of the pipeline in human-readable form:
      Stage A — Raw Extraction (every row with its PDF row number)
      Stage B — Date Grouping (per-date transaction list + first/last selection)
      Stage C — Daily Closing Balance Map (day → closing balance)
      Stage D — Daily Balance Fill (all days of month with carry-forward)
      Stage E — Series Selection (5-series and 10-series with source date)

    Use this to identify exactly which stage first produces a wrong balance.
    """
    contents = await file.read()

    # ── Parse ────────────────────────────────────────────────────────────────
    try:
        raw_txns, pdf_text = parse_pdf(contents, password=password or None)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    bank       = detect_bank(pdf_text)
    sort_order = detect_sort_order(raw_txns)
    txns       = normalize(raw_txns, bank=bank)

    from calculator import _fill_daily_from_txns, get_day1_balance, _get_balance_with_fallback

    out: dict = {"bank": bank, "sort_order": sort_order}

    # ── STAGE A: Raw Extraction ───────────────────────────────────────────────
    # Show every transaction in PDF row order with its global row number.
    stage_a = []
    global_row = 1
    for d, balances in raw_txns.items():
        if d == OPENING_BALANCE_KEY:
            continue
        for bal in balances:
            stage_a.append({
                "pdf_row": global_row,
                "date": str(d),
                "balance": round(bal, 2),
            })
            global_row += 1
    out["stage_A_raw_extraction"] = stage_a

    # ── STAGE B: Date Grouping ────────────────────────────────────────────────
    # After normalization, show per-date transaction list + first/last selection.
    stage_b = []
    for d in sorted(d for d in txns if d != OPENING_BALANCE_KEY):
        balances = txns[d]
        txn_list = {str(i + 1): round(b, 2) for i, b in enumerate(balances)}
        stage_b.append({
            "date": str(d),
            "transactions": txn_list,
            "selected_first": round(balances[0], 2),
            "selected_last_closing": round(balances[-1], 2),
        })
    out["stage_B_date_grouping"] = stage_b

    # ── STAGE C: Daily Closing Balance Map ───────────────────────────────────
    # Only dates that have actual transactions (no carry-forward yet).
    stage_c = {}
    for d in sorted(d for d in txns if d != OPENING_BALANCE_KEY):
        stage_c[str(d)] = round(txns[d][-1], 2)
    out["stage_C_closing_balance_per_date"] = stage_c

    # ── STAGE D: Daily Balance Fill ───────────────────────────────────────────
    # Full month fill with carry-forward + Day 1 override.
    monthly_groups = group_by_month(txns)
    stage_d_months = []
    for (year, month), month_txns in monthly_groups.items():
        filled = _fill_daily_from_txns(month_txns, year, month)
        d1 = get_day1_balance(month_txns, txns, year, month)
        if d1 is not None:
            filled[1] = d1

        _, days_in_month = calendar.monthrange(year, month)
        daily_map = {}
        for day in range(1, days_in_month + 1):
            entry: dict = {"balance": round(filled[day], 2) if day in filled else None}
            # Flag whether this day had a real transaction or is carry-forward
            real_date = __import__("datetime").date(year, month, day)
            entry["source"] = "transaction" if real_date in month_txns else "carry_forward"
            daily_map[f"{year}-{month:02d}-{day:02d}"] = entry

        stage_d_months.append({
            "month": f"{calendar.month_name[month]} {year}",
            "daily_balance_map": daily_map,
        })
    out["stage_D_daily_balance_fill"] = stage_d_months

    # ── STAGE E: Series Selection ─────────────────────────────────────────────
    # Show which balance was chosen for each series date and what source date
    # the backward fallback resolved to.
    stage_e_months = []
    for (year, month), month_txns in monthly_groups.items():
        filled = _fill_daily_from_txns(month_txns, year, month)
        d1 = get_day1_balance(month_txns, txns, year, month)
        if d1 is not None:
            filled[1] = d1

        def resolve(target_day: int) -> dict:
            for day in range(target_day, 0, -1):
                if day in filled:
                    return {
                        "date_requested": target_day,
                        "balance_used": round(filled[day], 2),
                        "source_day": day,
                        "source_date": f"{year}-{month:02d}-{day:02d}",
                        "fallback_used": day != target_day,
                    }
            return {"date_requested": target_day, "balance_used": None, "source_day": None}

        series_5  = [resolve(d) for d in [1, 5, 10, 15, 20, 25, 30]]
        series_10 = [resolve(d) for d in [1, 10, 20, 30]]

        selected_5  = [e["balance_used"] for e in series_5  if e["balance_used"] is not None]
        selected_10 = [e["balance_used"] for e in series_10 if e["balance_used"] is not None]

        stage_e_months.append({
            "month": f"{calendar.month_name[month]} {year}",
            "5_series": series_5,
            "5_series_average": round(sum(selected_5) / len(selected_5), 2) if selected_5 else None,
            "10_series": series_10,
            "10_series_average": round(sum(selected_10) / len(selected_10), 2) if selected_10 else None,
        })
    out["stage_E_series_selection"] = stage_e_months

    return out
