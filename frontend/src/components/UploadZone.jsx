import { useRef, useState } from "react";

/**
 * Drag-and-drop + click-to-browse PDF upload area.
 * Props: onFile(File), disabled
 */
export default function UploadZone({ onFile, disabled }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);

  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f?.type === "application/pdf") onFile(f);
  };

  const handleChange = (e) => {
    const f = e.target.files[0];
    if (f) onFile(f);
  };

  return (
    <div
      onClick={() => !disabled && inputRef.current.click()}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={`
        flex flex-col items-center justify-center gap-3 border-2 border-dashed rounded-2xl
        p-10 cursor-pointer transition-colors select-none
        ${dragging ? "border-blue-500 bg-blue-50" : "border-slate-300 bg-white hover:border-blue-400 hover:bg-blue-50/40"}
        ${disabled ? "opacity-50 cursor-not-allowed" : ""}
      `}
    >
      <svg className="w-12 h-12 text-blue-400" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round"
          d="M12 16v-8m0 0-3 3m3-3 3 3M4.5 19.5h15A2.25 2.25 0 0 0 21.75 17.25V9a2.25 2.25 0 0 0-2.25-2.25H15l-1.5-2.25H10.5L9 6.75H4.5A2.25 2.25 0 0 0 2.25 9v8.25A2.25 2.25 0 0 0 4.5 19.5z" />
      </svg>
      <p className="text-slate-600 font-medium">Drag &amp; drop your bank statement PDF here</p>
      <p className="text-slate-400 text-sm">or click to browse</p>
      <input ref={inputRef} type="file" accept=".pdf" className="hidden" onChange={handleChange} disabled={disabled} />
    </div>
  );
}
