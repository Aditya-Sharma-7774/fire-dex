/**
 * Small hand-drawn SVG charts.
 *
 * Deliberately not a charting library. These are simple enough that a
 * dependency would cost more than it saves, and drawing them ourselves
 * means they match the rest of the interface exactly rather than looking
 * like a widget dropped in from somewhere else.
 *
 * Every chart here handles the empty case explicitly. A chart with no data
 * must say so rather than drawing an empty box that looks like zero.
 */

interface Point {
  label: string
  value: number
}

/* ------------------------------------------------------------------ */

/**
 * Horizontal bars. Used for per-agent duration and token comparisons,
 * where the labels are words and would not fit under vertical bars.
 */
export function BarRows({
  data,
  unit = '',
  colour = '#f97316',
  formatValue,
}: {
  data: Point[]
  unit?: string
  colour?: string
  formatValue?: (value: number) => string
}) {
  if (data.length === 0) {
    return <p className="py-4 text-center text-xs text-coal-600">No data</p>
  }

  const max = Math.max(...data.map((d) => d.value), 1)

  return (
    <div className="space-y-2">
      {data.map((point) => (
        <div key={point.label} className="flex items-center gap-3">
          <span className="w-32 shrink-0 truncate text-[11px] text-coal-400" title={point.label}>
            {point.label}
          </span>
          <div className="h-5 flex-1 overflow-hidden rounded-md bg-white/[0.04]">
            <div
              className="h-full rounded-md transition-[width] duration-700 ease-out"
              style={{
                width: `${Math.max((point.value / max) * 100, 2)}%`,
                background: `linear-gradient(90deg, ${colour}55, ${colour})`,
              }}
            />
          </div>
          <span
            className="w-20 shrink-0 text-right font-mono text-[11px] text-coal-300"
            style={{ fontVariantNumeric: 'tabular-nums' }}
          >
            {formatValue ? formatValue(point.value) : point.value}
            {unit}
          </span>
        </div>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ */

/**
 * Line chart with a filled area, for a metric tracked across analyses.
 *
 * The y-axis is padded rather than starting at zero, because reviewer
 * scores cluster in a narrow band and a zero-based axis would flatten every
 * difference into a straight line.
 */
export function TrendLine({
  data,
  colour = '#f97316',
  height = 120,
  suffix = '',
}: {
  data: Point[]
  colour?: string
  height?: number
  suffix?: string
}) {
  if (data.length === 0) {
    return (
      <div
        className="grid place-items-center rounded-xl border hairline"
        style={{ height }}
      >
        <p className="text-xs text-coal-600">No analyses yet</p>
      </div>
    )
  }

  if (data.length === 1) {
    return (
      <div
        className="grid place-items-center rounded-xl border hairline"
        style={{ height }}
      >
        <div className="text-center">
          <div className="font-mono text-2xl text-coal-100">
            {data[0].value.toFixed(1)}
            {suffix}
          </div>
          <div className="mt-1 text-[10px] text-coal-600">
            one analysis — a trend needs at least two
          </div>
        </div>
      </div>
    )
  }

  const width = 100 // viewBox units; the SVG scales to its container
  const values = data.map((d) => d.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const pad = (max - min) * 0.15 || 1
  const lo = min - pad
  const hi = max + pad

  const x = (i: number) => (i / (data.length - 1)) * width
  const y = (v: number) => height - ((v - lo) / (hi - lo)) * height

  const line = data.map((d, i) => `${i === 0 ? 'M' : 'L'} ${x(i)} ${y(d.value)}`).join(' ')
  const area = `${line} L ${width} ${height} L 0 ${height} Z`

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        className="w-full"
        style={{ height }}
        role="img"
        aria-label={`Trend across ${data.length} analyses`}
      >
        <defs>
          <linearGradient id={`fill-${colour.slice(1)}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={colour} stopOpacity="0.28" />
            <stop offset="100%" stopColor={colour} stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* horizontal guides */}
        {[0.25, 0.5, 0.75].map((f) => (
          <line
            key={f}
            x1="0"
            x2={width}
            y1={height * f}
            y2={height * f}
            stroke="rgba(255,255,255,0.05)"
            strokeWidth="0.5"
            vectorEffect="non-scaling-stroke"
          />
        ))}

        <path d={area} fill={`url(#fill-${colour.slice(1)})`} />
        <path
          d={line}
          fill="none"
          stroke={colour}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />

        {data.map((d, i) => (
          <circle
            key={i}
            cx={x(i)}
            cy={y(d.value)}
            r="2.5"
            fill="#0b0b0d"
            stroke={colour}
            strokeWidth="1.5"
            vectorEffect="non-scaling-stroke"
          >
            <title>{`${d.label}: ${d.value.toFixed(1)}${suffix}`}</title>
          </circle>
        ))}
      </svg>

      <div className="mt-1 flex justify-between font-mono text-[9px] text-coal-600">
        <span>
          {lo.toFixed(0)}
          {suffix}
        </span>
        <span>
          {hi.toFixed(0)}
          {suffix}
        </span>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */

/**
 * A single proportion, drawn as an arc.
 *
 * Used for evidence coverage and confidence — one number where the
 * remainder is meaningful (the evidence that was NOT used).
 */
export function Gauge({
  value,
  max = 100,
  label,
  sublabel,
  colour = '#f97316',
  size = 96,
}: {
  value: number
  max?: number
  label: string
  sublabel?: string
  colour?: string
  size?: number
}) {
  const fraction = Math.max(0, Math.min(1, value / max))
  const radius = 34
  const circumference = 2 * Math.PI * radius

  return (
    <div className="flex flex-col items-center">
      <div className="relative" style={{ width: size, height: size }}>
        <svg viewBox="0 0 80 80" className="h-full w-full -rotate-90">
          <circle
            cx="40"
            cy="40"
            r={radius}
            fill="none"
            stroke="rgba(255,255,255,0.06)"
            strokeWidth="7"
          />
          <circle
            cx="40"
            cy="40"
            r={radius}
            fill="none"
            stroke={colour}
            strokeWidth="7"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - fraction)}
            style={{ transition: 'stroke-dashoffset 900ms cubic-bezier(0.22,1,0.36,1)' }}
          />
        </svg>
        <div className="absolute inset-0 grid place-items-center">
          <span
            className="font-mono text-lg font-semibold text-coal-100"
            style={{ fontVariantNumeric: 'tabular-nums' }}
          >
            {label}
          </span>
        </div>
      </div>
      {sublabel && (
        <span className="mt-1.5 text-center text-[10px] uppercase tracking-wide text-coal-500">
          {sublabel}
        </span>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */

/**
 * Stacked proportion bar. Used for token split and pass/fail counts.
 */
export function StackedBar({
  segments,
}: {
  segments: { label: string; value: number; colour: string }[]
}) {
  const total = segments.reduce((sum, s) => sum + s.value, 0)
  if (total === 0) {
    return <p className="py-2 text-center text-xs text-coal-600">No data</p>
  }

  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-full bg-white/[0.04]">
        {segments.map((segment) => (
          <div
            key={segment.label}
            className="transition-[width] duration-700"
            style={{
              width: `${(segment.value / total) * 100}%`,
              background: segment.colour,
            }}
            title={`${segment.label}: ${segment.value}`}
          />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {segments.map((segment) => (
          <span key={segment.label} className="flex items-center gap-1.5 text-[10px]">
            <span
              className="h-2 w-2 rounded-sm"
              style={{ background: segment.colour }}
            />
            <span className="text-coal-400">{segment.label}</span>
            <span className="font-mono text-coal-200">{segment.value.toLocaleString()}</span>
          </span>
        ))}
      </div>
    </div>
  )
}
