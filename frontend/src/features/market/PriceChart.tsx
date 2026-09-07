import { useEffect, useRef, useState } from 'react'
import {
  ColorType,
  CrosshairMode,
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type LineData,
  type Time,
} from 'lightweight-charts'

import { api, ApiError, type CandleSeriesResponse } from '../../services/api'

/**
 * Candlestick chart with the indicator overlays.
 *
 * Every line drawn here comes from our own tested indicator engine — the
 * same numbers the Technical Analysis agent reasons about. Chart and
 * analysis cannot disagree, because they read the identical series.
 *
 * lightweight-charts is used rather than a general charting library
 * because candlesticks with volume and overlays are exactly what it does,
 * and it is a fraction of the size of the alternatives.
 */

const INTERVALS = ['15m', '1h', '4h', '1d'] as const
type Interval = (typeof INTERVALS)[number]

interface Overlays {
  sma20: boolean
  sma50: boolean
  bollinger: boolean
}

export function PriceChart({ symbol }: { symbol: string }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

  const [interval, setInterval] = useState<Interval>('1h')
  const [overlays, setOverlays] = useState<Overlays>({
    sma20: true,
    sma50: false,
    bollinger: false,
  })
  const [data, setData] = useState<CandleSeriesResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // ---- fetch ------------------------------------------------------
  useEffect(() => {
    let cancelled = false
    setLoading(true)

    api
      .candles(symbol, interval)
      .then((series) => {
        if (cancelled) return
        setData(series)
        setError(null)
      })
      .catch((err) => {
        if (cancelled) return
        setData(null)
        setError(
          err instanceof ApiError ? err.message : `No candle data available for ${symbol}`,
        )
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [symbol, interval])

  // ---- draw -------------------------------------------------------
  useEffect(() => {
    const container = containerRef.current
    if (!container || !data) return

    const chart = createChart(container, {
      width: container.clientWidth,
      height: 340,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#7b7b86',
        fontFamily: 'Inter, system-ui, sans-serif',
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.04)' },
        horzLines: { color: 'rgba(255,255,255,0.04)' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.07)' },
      timeScale: { borderColor: 'rgba(255,255,255,0.07)', timeVisible: true },
    })
    chartRef.current = chart

    // Candle times arrive as ISO strings; lightweight-charts wants epoch
    // seconds. Values must also be strictly ascending or it throws.
    const toTime = (iso: string): Time => (Date.parse(iso) / 1000) as Time

    const candles: CandlestickData[] = data.times.map((t, i) => ({
      time: toTime(t),
      open: data.open[i],
      high: data.high[i],
      low: data.low[i],
      close: data.close[i],
    }))

    const candleSeries = chart.addCandlestickSeries({
      upColor: '#34d399',
      downColor: '#f87171',
      borderUpColor: '#34d399',
      borderDownColor: '#f87171',
      wickUpColor: '#34d399',
      wickDownColor: '#f87171',
    })
    candleSeries.setData(candles)

    // Volume on its own scale, squeezed into the bottom fifth so it reads
    // as context rather than competing with price.
    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })
    volumeSeries.setData(
      data.times.map((t, i): HistogramData => ({
        time: toTime(t),
        value: data.volume[i],
        color: data.close[i] >= data.open[i] ? 'rgba(52,211,153,0.3)' : 'rgba(248,113,113,0.3)',
      })),
    )

    // Indicator overlays. Nulls are dropped rather than plotted as zero —
    // an indicator has no value until its warm-up period has passed, and
    // drawing zero there would invent a reading.
    const line = (values: (number | null)[], colour: string, width: 1 | 2, title: string) => {
      const points: LineData[] = []
      values.forEach((v, i) => {
        if (v !== null) points.push({ time: toTime(data.times[i]), value: v })
      })
      if (points.length === 0) return
      const series = chart.addLineSeries({
        color: colour,
        lineWidth: width,
        priceLineVisible: false,
        lastValueVisible: false,
        title,
      })
      series.setData(points)
    }

    if (overlays.sma20) line(data.sma_20, '#f97316', 2, 'SMA 20')
    if (overlays.sma50) line(data.sma_50, '#60a5fa', 2, 'SMA 50')
    if (overlays.bollinger) {
      line(data.bollinger_upper, 'rgba(167,139,250,0.55)', 1, 'BB upper')
      line(data.bollinger_lower, 'rgba(167,139,250,0.55)', 1, 'BB lower')
    }

    chart.timeScale().fitContent()

    // Follow container width so the chart reflows with the layout.
    const observer = new ResizeObserver(([entry]) => {
      chart.applyOptions({ width: entry.contentRect.width })
    })
    observer.observe(container)

    return () => {
      observer.disconnect()
      chart.remove()
      chartRef.current = null
    }
  }, [data, overlays])

  const toggle = (key: keyof Overlays) =>
    setOverlays((previous) => ({ ...previous, [key]: !previous[key] }))

  return (
    <section className="mt-14">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-coal-300">
          {symbol} price
        </h2>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex gap-1">
            {INTERVALS.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setInterval(option)}
                className={`rounded-lg px-2.5 py-1 text-[11px] font-medium transition-colors ${
                  interval === option
                    ? 'bg-fire-500/15 text-fire-300'
                    : 'text-coal-500 hover:bg-white/[0.04] hover:text-coal-300'
                }`}
              >
                {option}
              </button>
            ))}
          </div>

          <div className="flex gap-1 border-l hairline pl-3">
            <OverlayToggle
              label="SMA 20"
              colour="#f97316"
              on={overlays.sma20}
              onClick={() => toggle('sma20')}
            />
            <OverlayToggle
              label="SMA 50"
              colour="#60a5fa"
              on={overlays.sma50}
              onClick={() => toggle('sma50')}
            />
            <OverlayToggle
              label="Bollinger"
              colour="#a78bfa"
              on={overlays.bollinger}
              onClick={() => toggle('bollinger')}
            />
          </div>
        </div>
      </div>

      <div className="glass overflow-hidden p-4">
        {loading && !data && <div className="h-[340px] animate-shimmer rounded-xl" />}

        {error && !loading && (
          <div className="grid h-[340px] place-items-center text-center">
            <div>
              <p className="text-sm text-coal-400">{error}</p>
              <p className="mt-1 text-[11px] text-coal-600">
                Stablecoins and some assets have no trading pair we can chart.
              </p>
            </div>
          </div>
        )}

        <div ref={containerRef} className={loading || error ? 'hidden' : ''} />

        {data && !error && (
          <p className="mt-3 border-t hairline pt-3 text-[10px] leading-relaxed text-coal-600">
            {data.close.length} candles from Binance. Every overlay is computed by our own
            tested indicator engine — the same values the Technical Analysis agent reads, so
            the chart and the analysis cannot disagree.
          </p>
        )}
      </div>
    </section>
  )
}

function OverlayToggle({
  label,
  colour,
  on,
  onClick,
}: {
  label: string
  colour: string
  on: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      className={`flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] transition-colors ${
        on ? 'text-coal-200' : 'text-coal-600 hover:text-coal-400'
      }`}
    >
      <span
        className="h-0.5 w-3 rounded-full transition-opacity"
        style={{ background: colour, opacity: on ? 1 : 0.3 }}
      />
      {label}
    </button>
  )
}
