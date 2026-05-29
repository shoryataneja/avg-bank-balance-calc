# Average Bank Balance Calculator

A full-stack web application to upload a bank statement PDF and compute average bank balances using standard banking rules.

## Tech Stack
- **Frontend**: React + Vite + Tailwind CSS + Recharts
- **Backend**: Python FastAPI + pdfplumber + pandas + reportlab

---

## Project Structure

```
bank_balance_avg/
├── backend/
│   ├── main.py          # FastAPI app & routes
│   ├── parser.py        # PDF parsing (table + regex fallback)
│   ├── calculator.py    # Daily fill + average calculation
│   ├── utils.py         # INR formatting + PDF export
│   └── requirements.txt
└── frontend/
    └── src/
        ├── components/
        │   ├── UploadZone.jsx
        │   ├── SummaryCards.jsx
        │   ├── BreakdownTable.jsx
        │   ├── TransactionTable.jsx
        │   └── BalanceChart.jsx
        ├── pages/
        │   └── Home.jsx
        ├── services/
        │   └── api.js
        └── App.jsx
```

---

## Setup & Run

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Backend runs at: http://localhost:8000

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at: http://localhost:5173

---

## API Reference

### POST /upload

Upload a bank statement PDF.

**Request** (multipart/form-data):
| Field    | Type   | Required | Description              |
|----------|--------|----------|--------------------------|
| file     | File   | Yes      | Bank statement PDF       |
| password | string | No       | Password for locked PDFs |

**Response**:
```json
{
  "average7": 15220.50,
  "average4": 14110.00,
  "selected_balances_7": {
    "1": 12000.00,
    "5": 15000.00,
    "10": 18000.00,
    "15": 14000.00,
    "20": 16000.00,
    "25": 13500.00,
    "30": 17500.00
  },
  "selected_balances_4": {
    "1": 12000.00,
    "10": 18000.00,
    "20": 16000.00,
    "30": 17500.00
  },
  "daily_balances": { "1": 12000.00, "2": 12000.00, "...": "..." },
  "transactions": [
    { "date": "2024-04-01", "balance": 12000.00 }
  ],
  "month": "April",
  "year": 2024
}
```

### POST /export-pdf

Send the result JSON back to receive a downloadable PDF report.

### GET /health

Returns `{"status": "ok"}`.

---

## Business Rules

### Closing Balance
Multiple transactions on the same date → **last transaction's balance** is the closing balance.

### Daily Fill
Days with no transaction inherit the **previous day's closing balance**.

### Average-7
Dates: `[1, 5, 10, 15, 20, 25, 30]`  
Formula: `sum / 7`

### Average-4
Dates: `[1, 10, 20, 30]`  
Formula: `sum / 4`

### Date Fallback
If a required date has no balance, walk backward until one is found.

---

## Supported Balance Formats
- `1,25,000.50` (Indian)
- `125000.50` (standard)
- `1,25,000.50 CR` / `1,25,000.50 DR`

## Edge Cases Handled
- February (28/29 days)
- Missing 30th/31st
- Password-protected PDFs
- Empty / invalid PDFs
- Table extraction with regex fallback
# average_bank_balance_calculator
