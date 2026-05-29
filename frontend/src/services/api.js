const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

/**
 * Upload a bank statement PDF to the backend.
 * @param {File} file
 * @param {string|null} password
 * @returns {Promise<object>} parsed result
 */
export async function uploadStatement(file, password = null) {
  const form = new FormData();
  form.append("file", file);
  if (password) form.append("password", password);

  const res = await fetch(`${BASE_URL}/upload`, { method: "POST", body: form });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Upload failed");
  return data;
}

/**
 * Request a PDF export of the result from the backend.
 * @param {object} result
 */
export async function exportPDF(result) {
  const res = await fetch(`${BASE_URL}/export-pdf`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(result),  // result is the full {months:[...]} payload
  });
  if (!res.ok) throw new Error("PDF export failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "bank_balance_report.pdf";
  a.click();
  URL.revokeObjectURL(url);
}
