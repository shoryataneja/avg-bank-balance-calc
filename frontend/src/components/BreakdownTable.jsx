import { formatINR } from "./SummaryCards";

/** Props: selected5, selected10 */
export default function BreakdownTable({ selected5, selected10 }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <Table title="5 Series" data={selected5} dates={[1, 5, 10, 15, 20, 25, 30]} />
      <Table title="10 Series" data={selected10} dates={[1, 10, 20, 30]} />
    </div>
  );
}

function Table({ title, data, dates }) {
  return (
    <div className="bg-white rounded-xl border border-slate-100 overflow-hidden">
      <div className="px-4 py-2.5 bg-slate-50 border-b border-slate-100">
        <h3 className="text-sm font-semibold text-slate-600 uppercase tracking-wide">{title}</h3>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-slate-400 border-b border-slate-100">
            <th className="px-4 py-2 font-medium">Day</th>
            <th className="px-4 py-2 font-medium text-right">Balance</th>
          </tr>
        </thead>
        <tbody>
          {dates.map((d) => (
            <tr key={d} className="border-b border-slate-50 last:border-0 hover:bg-slate-50/60 transition-colors">
              <td className="px-4 py-2 text-slate-500">{d}</td>
              <td className="px-4 py-2 text-right font-medium text-slate-800">
                {data[String(d)] != null
                  ? formatINR(data[String(d)])
                  : <span className="text-slate-300 text-xs">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
