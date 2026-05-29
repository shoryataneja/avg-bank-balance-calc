/** Format number as Indian Rupee string */
export function formatINR(amount) {
  if (amount == null) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(amount);
}

/** Props: average5, average10 */
export default function SummaryCards({ average5, average10 }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <Card label="5 Series Average" value={average5} gradient="from-blue-600 to-blue-500" />
      <Card label="10 Series Average" value={average10} gradient="from-violet-600 to-violet-500" />
    </div>
  );
}

function Card({ label, value, gradient }) {
  return (
    <div className={`rounded-xl bg-gradient-to-br ${gradient} text-white px-5 py-4 shadow-sm`}>
      <p className="text-xs font-medium opacity-75 uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold mt-1">{formatINR(value)}</p>
    </div>
  );
}
