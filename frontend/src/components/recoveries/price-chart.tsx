import { formatDate, type SkuHistory } from "@/lib/recoveries";

const PERIOD = {
  before: "#8a8680",
  during: "#c4a000",
  after: "#1f8a4c",
};

export function PriceChart({ sku }: { sku: SkuHistory }) {
  if (sku.points.length === 0) return null;
  const values = [...sku.points.map((point) => point.unit_price), sku.expected_price];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const yMin = min - span * 0.18;
  const yMax = max + span * 0.22;
  const width = 500;
  const height = 156;
  const left = 46;
  const right = 18;
  const top = 28;
  const bottom = 24;
  const innerW = width - left - right;
  const innerH = height - top - bottom;
  const yOf = (value: number) => top + (1 - (value - yMin) / (yMax - yMin)) * innerH;
  const xOf = (index: number) =>
    left + (sku.points.length <= 1 ? innerW / 2 : (index / (sku.points.length - 1)) * innerW);
  const path = sku.points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${xOf(index).toFixed(1)} ${yOf(point.unit_price).toFixed(1)}`)
    .join(" ");
  const expectedY = yOf(sku.expected_price);
  const ticks = [min, max];

  return (
    <figure className="rounded-md border border-[#eeeae4] bg-white p-3">
      <figcaption className="mb-1 flex items-baseline justify-between gap-3">
        <span className="text-[13px] font-medium text-[#1c1c1c]">{sku.sku}</span>
        <span className="truncate text-[12px] text-[#8a8680]">{sku.description}</span>
      </figcaption>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[120px] w-full" role="img" aria-label={`${sku.sku} price history`}>
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={left} x2={width - right} y1={yOf(tick)} y2={yOf(tick)} stroke="#f1efe9" />
            <text x={left - 6} y={yOf(tick) + 3} textAnchor="end" className="fill-[#8a8680]" fontSize="10">
              ${Math.round(tick)}
            </text>
          </g>
        ))}
        <line
          x1={left}
          x2={width - right}
          y1={expectedY}
          y2={expectedY}
          stroke="#8a8680"
          strokeDasharray="4 4"
        />
        <path d={path} fill="none" stroke="#1c1c1c" strokeWidth="1.6" />
        {sku.points.map((point, index) => (
          <circle key={`${point.invoice_number}-${index}`} cx={xOf(index)} cy={yOf(point.unit_price)} r="3.5" fill={PERIOD[point.period]} />
        ))}
        <text x={xOf(0)} y={height - 6} fontSize="10" className="fill-[#8a8680]">
          {formatDate(sku.points[0]?.date)}
        </text>
        <text x={xOf(sku.points.length - 1)} y={height - 6} textAnchor="end" fontSize="10" className="fill-[#8a8680]">
          {formatDate(sku.points[sku.points.length - 1]?.date)}
        </text>
      </svg>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-[#6f6c66]">
        <Legend color={PERIOD.before} label="Before" />
        <Legend color={PERIOD.during} label="During" />
        <Legend color={PERIOD.after} label="After" />
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block w-4 border-t border-dashed border-[#8a8680]" />
          After the control group
        </span>
      </div>
    </figure>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="size-2 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}
