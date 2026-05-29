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
    Diagnostic endpoint — returns raw pdfplumber extraction data.
    Use this to understand why a PDF is returning 422.
    """
    contents = await file.read()
    open_kwargs = {"password": password} if password else {}
    result = {"pages": []}

    try:
        with pdfplumber.open(io.BytesIO(contents), **open_kwargs) as pdf:
            result["total_pages"] = len(pdf.pages)
            for i, page in enumerate(pdf.pages[:3], start=1):  # first 3 pages only
                page_info: dict = {"page": i, "tables": [], "text_sample": ""}

                # Raw text sample
                text = page.extract_text() or ""
                page_info["text_sample"] = text[:500]

                # Table extraction
                tables = page.extract_tables() or []
                page_info["table_count"] = len(tables)
                for j, table in enumerate(tables[:2]):  # first 2 tables per page
                    if not table:
                        continue
                    tbl_info = {
                        "table_index": j,
                        "row_count": len(table),
                        "first_3_rows": table[:3],
                        "detected_cols": None,
                    }
                    # Find header row
                    header_row_idx = 0
                    for ri, row in enumerate(table):
                        if row and any("balance" in (c or "").lower() for c in row):
                            header_row_idx = ri
                            break
                    header = table[header_row_idx]
                    cols = detect_columns([c or "" for c in header])
                    if cols["date"] is None or cols["balance"] is None:
                        cols = _infer_columns_from_data(table)
                    tbl_info["header_row"] = header
                    tbl_info["detected_cols"] = cols
                    page_info["tables"].append(tbl_info)

                result["pages"].append(page_info)
    except Exception as e:
        result["error"] = str(e)

    return result
