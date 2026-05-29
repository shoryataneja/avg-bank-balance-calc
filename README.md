# Average Bank Balance Calculator

> **This project was built by Shorya Taneja during an internship at [Popular Digital AI](https://populardigital.ai).**

A full-stack web application that accepts a bank statement PDF and computes the **5 Series** and **10 Series** average bank balances using standard Indian banking rules. Supports multiple banks (Kotak, HDFC, SBI, ICICI, Axis, PNB), both ascending and descending statement formats, and password-protected PDFs.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19 + Vite + Tailwind CSS + Recharts |
| Backend | Python FastAPI + pdfplumber + reportlab |
| PDF Parsing | pdfplumber (table → regex → word-scan fallback chain) |
| PDF Export | reportlab |

---

## Project Structure

```
bank_balance_avg/
├── backend/
│   ├── main.py            # FastAPI app & all API routes
│   ├── parser.py          # PDF parsing (table + regex + word-scan fallback)
│   ├── normalizer.py      # Bank detection, sort-order detection, normalization
│   ├── calculator.py      # Daily fill, Day 1 logic, average calculation
│   ├── utils.py           # INR formatting + PDF report export
│   └── requirements.txt   # Python dependencies
├── frontend/
│   ├── public/
│   └── src/
│       ├── components/
│       │   ├── UploadZone.jsx
│       │   ├── SummaryCards.jsx
│       │   └── BreakdownTable.jsx
│       ├── pages/
│       │   └── Home.jsx
│       ├── services/
│       │   └── api.js
│       └── App.jsx
├── README.md              # This file
└── LOGIC.md               # Full technical logic documentation
```

---

## Running Locally — Step by Step

Follow these instructions exactly to run the project on any system. You need **Python 3.11+** and **Node.js 18+** installed.

### Prerequisites

Check your versions before starting:

```bash
python3 --version    # must be 3.11 or higher
node --version       # must be 18 or higher
npm --version
```

If you don't have these installed:
- Python: https://www.python.org/downloads/
- Node.js: https://nodejs.org/

---

### Step 1 — Clone the Repository

```bash
git clone https://github.com/<your-username>/bank_balance_avg.git
cd bank_balance_avg
```

---

### Step 2 — Set Up the Backend

```bash
# Navigate to the backend folder
cd backend

# Create a Python virtual environment
python3 -m venv venv

# Activate the virtual environment
# On macOS / Linux:
source venv/bin/activate

# On Windows (Command Prompt):
venv\Scripts\activate.bat

# On Windows (PowerShell):
venv\Scripts\Activate.ps1
```

Install all Python dependencies:

```bash
pip install -r requirements.txt
```

Start the backend server:

```bash
uvicorn main:app --reload --port 8000
```

You should see:

```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
```

The backend is now running at **http://localhost:8000**

> Keep this terminal open. Open a new terminal for the next step.

---

### Step 3 — Set Up the Frontend

Open a new terminal window and navigate to the frontend folder:

```bash
# From the project root
cd frontend

# Install Node dependencies
npm install

# Start the development server
npm run dev
```

You should see:

```
  VITE v8.x.x  ready in xxx ms

  ➜  Local:   http://localhost:5173/
```

The frontend is now running at **http://localhost:5173**

---

### Step 4 — Open the App

Open your browser and go to:

```
http://localhost:5173
```

Upload any supported bank statement PDF and click **Calculate Average Balance**.

---

## Both Servers Must Be Running

The app requires both servers running simultaneously:

| Service | URL |
|---|---|
| Frontend (React) | http://localhost:5173 |
| Backend (FastAPI) | http://localhost:8000 |

The frontend is pre-configured to call `http://localhost:8000` by default. No environment variables need to be set for local development.

---

## Stopping the Servers

Press `Ctrl + C` in each terminal to stop the respective server.

To deactivate the Python virtual environment:

```bash
deactivate
```

---

## API Endpoints

Once the backend is running, you can also test the API directly:

| Endpoint | Method | Description |
|---|---|---|
| `/upload` | POST | Upload a PDF, returns calculated averages |
| `/export-pdf` | POST | Send result JSON, receive downloadable PDF report |
| `/health` | GET | Health check — returns `{"status": "ok"}` |
| `/debug-pdf` | POST | Full pipeline diagnostic for debugging extraction |
| `/audit` | POST | Detailed audit trace for Kotak descending statements |

Interactive API docs (Swagger UI) are available at:

```
http://localhost:8000/docs
```

---

## Supported Banks

| Bank | Ascending | Descending |
|---|---|---|
| HDFC Bank | ✅ | ✅ |
| SBI | ✅ | — |
| ICICI Bank | ✅ | — |
| Axis Bank | ✅ | — |
| PNB | ✅ | — |
| Other / Unknown | ✅ (auto-detected) | ✅ (auto-detected) |

---

## Business Rules Summary

### Closing Balance
Multiple transactions on the same date → the **last transaction's balance** is the closing balance for that day.

### Daily Fill
Days with no transaction inherit the **previous day's closing balance** (carry-forward).

### 5 Series Average
Dates: `[1, 5, 10, 15, 20, 25, 30]` → `sum / 7`

### 10 Series Average
Dates: `[1, 10, 20, 30]` → `sum / 4`

### Date Fallback
If a required series date has no balance, walk **backward** day by day until one is found.

### Day 1 Priority Logic
1. Transactions exist on Day 1 → use last transaction of Day 1
2. No Day 1 transactions → use last transaction of previous month's last active day
3. No previous month data → use opening balance row from statement (if present)
4. Nothing else available → use first transaction of the earliest active day in the month

For the full technical documentation of all logic, see [LOGIC.md](./LOGIC.md).

---

## Supported Balance Formats

- `1,25,000.50` — Indian grouping format
- `125000.50` — Standard format
- `1,25,000.50 CR` — Credit suffix
- `1,25,000.50 DR` — Debit suffix (treated as negative)

---

## Troubleshooting

**Backend won't start — "module not found"**
Make sure you activated the virtual environment before running `uvicorn`:
```bash
source venv/bin/activate   # macOS/Linux
venv\Scripts\activate      # Windows
```

**Frontend shows "Upload failed" or network error**
Make sure the backend is running on port 8000 before using the frontend.

**"No transaction data found in the PDF"**
The PDF may be image-based (scanned). pdfplumber cannot extract text from scanned images. Only text-based PDFs are supported.

**Port already in use**
If port 8000 or 5173 is taken, use:
```bash
uvicorn main:app --reload --port 8001        # backend on different port
npm run dev -- --port 5174                   # frontend on different port
```
If you change the backend port, update `VITE_API_URL` in a `.env` file in the frontend folder:
```
VITE_API_URL=http://localhost:8001
```
# avg-bank-balance-calc
