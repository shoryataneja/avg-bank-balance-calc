import { useState } from "react";
import UploadZone from "../components/UploadZone";
import SummaryCards from "../components/SummaryCards";
import BreakdownTable from "../components/BreakdownTable";
import { uploadStatement, exportPDF } from "../services/api";

export default function Home() {
  const [file, setFile] = useState(null);
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null); // { months: [...] }
  const [exporting, setExporting] = useState(false);

  const handleFile = (f) => { setFile(f); setResult(null); setError(null); };

  const handleUpload = async () => {
    if (!file) return;
    setLoading(true); setError(null); setResult(null);
    try {
      const data = await uploadStatement(file, password || null);
      setResult(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleExport = async () => {
    setExporting(true);
    try { await exportPDF(result); }
    catch (e) { setError(e.message); }
    finally { setExporting(false); }
  };

  const handleReset = () => { setFile(null); setPassword(""); setResult(null); setError(null); };

  return (
    <div className="min-h-screen bg-slate-50 py-10 px-4">
      <div className="max-w-2xl mx-auto space-y-5">

        {/* Header */}
        <div className="text-center space-y-1 pb-2">
          <h1 className="text-2xl font-bold text-slate-800 tracking-tight">Average Bank Balance Calculator</h1>
          <p className="text-slate-400 text-sm">Upload a bank statement PDF to compute average balances</p>
        </div>

        {/* Upload card */}
        <div className="bg-white rounded-2xl border border-slate-200 p-5 space-y-4">
          <UploadZone onFile={handleFile} disabled={loading} />

          {file && (
            <div className="flex items-center gap-2 text-sm text-slate-600 bg-slate-50 rounded-lg px-3 py-2">
              <svg className="w-4 h-4 text-red-400 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path d="M4 2a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.414A2 2 0 0 0 17.414 6L14 2.586A2 2 0 0 0 12.586 2H4z" />
              </svg>
              <span className="truncate font-medium flex-1">{file.name}</span>
              <button onClick={handleReset} className="text-slate-300 hover:text-red-400 transition-colors text-base leading-none">✕</button>
            </div>
          )}

          <div className="space-y-2">
            <button
              type="button"
              onClick={() => setShowPassword((p) => !p)}
              className="text-xs text-slate-400 hover:text-blue-500 transition-colors"
            >
              {showPassword ? "▲ Hide password field" : "🔒 Password-protected PDF?"}
            </button>
            {showPassword && (
              <input
                type="password"
                placeholder="Enter PDF password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200"
              />
            )}
          </div>

          <button
            onClick={handleUpload}
            disabled={!file || loading}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-slate-200 disabled:text-slate-400 disabled:cursor-not-allowed text-white font-semibold py-2.5 rounded-xl transition-colors flex items-center justify-center gap-2 text-sm"
          >
            {loading ? (
              <>
                <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
                Processing…
              </>
            ) : "Calculate Average Balance"}
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-600 rounded-xl px-4 py-3 text-sm flex gap-2 items-start">
            <span className="mt-0.5">⚠</span>
            {error}
          </div>
        )}

        {/* Results */}
        {result?.months?.length > 0 && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <p className="text-sm text-slate-500">
                {result.months.length === 1
                  ? `Results for ${result.months[0].month} ${result.months[0].year}`
                  : `Results across ${result.months.length} months`}
              </p>
              <button
                onClick={handleExport}
                disabled={exporting}
                className="text-xs bg-white border border-slate-200 hover:border-blue-300 text-slate-600 hover:text-blue-600 px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1"
              >
                {exporting ? "Exporting…" : "⬇ Export PDF"}
              </button>
            </div>

            {result.months.map((m) => (
              <MonthCard key={`${m.year}-${m.month}`} data={m} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function MonthCard({ data }) {
  return (
    <div className="bg-white rounded-2xl border border-slate-200 overflow-hidden">
      {/* Month header */}
      <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between">
        <h2 className="font-semibold text-slate-700">{data.month} {data.year}</h2>
      </div>

      <div className="p-5 space-y-4">
        <SummaryCards average5={data.average5} average10={data.average10} />
        <BreakdownTable selected5={data.selected_balances_5} selected10={data.selected_balances_10} />
      </div>
    </div>
  );
}
