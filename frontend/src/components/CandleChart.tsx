import { useEffect, useRef } from 'react'
import {
  CandlestickSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import type { BarOut, TradeOut } from '../api/types'

interface Props {
  bars: BarOut[]
  trades: TradeOut[]
  height?: number
}

function toTime(ts: string): UTCTimestamp {
  return Math.floor(Date.parse(ts) / 1000) as UTCTimestamp
}

/** Greatest bar time <= t (markers must sit on an existing candle), or null. */
function snapToBar(t: UTCTimestamp, barTimes: number[]): UTCTimestamp | null {
  let lo = 0
  let hi = barTimes.length - 1
  let best = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (barTimes[mid] <= t) {
      best = barTimes[mid]
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  return best < 0 ? null : (best as UTCTimestamp)
}

const GREEN = '#16a34a'
const RED = '#dc2626'
const BLUE = '#2563eb'

export function CandleChart({ bars, trades, height = 320 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const priceLinesRef = useRef<IPriceLine[]>([])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const chart = createChart(el, {
      autoSize: true,
      timeScale: { timeVisible: true, secondsVisible: false },
    })
    const series = chart.addSeries(CandlestickSeries, {
      upColor: GREEN,
      downColor: RED,
      borderVisible: false,
      wickUpColor: GREEN,
      wickDownColor: RED,
    })
    chartRef.current = chart
    seriesRef.current = series
    markersRef.current = createSeriesMarkers(series, [])
    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
      markersRef.current = null
      priceLinesRef.current = []
    }
  }, [])

  useEffect(() => {
    seriesRef.current?.setData(
      bars.map((b) => ({
        time: toTime(b.ts_utc),
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      })),
    )
  }, [bars])

  useEffect(() => {
    const series = seriesRef.current
    if (!series) return
    const barTimes = bars.map((b) => toTime(b.ts_utc) as number)

    const markers: SeriesMarker<Time>[] = []
    for (const t of trades) {
      if (t.opened_at_utc && (t.status === 'OPEN' || t.status === 'CLOSED')) {
        const time = snapToBar(toTime(t.opened_at_utc), barTimes)
        if (time != null) {
          markers.push({
            time,
            position: t.direction === 'BUY' ? 'belowBar' : 'aboveBar',
            shape: t.direction === 'BUY' ? 'arrowUp' : 'arrowDown',
            color: t.direction === 'BUY' ? GREEN : RED,
            text: `#${t.id} ${t.direction}`,
          })
        }
      }
      if (t.closed_at_utc && t.status === 'CLOSED') {
        const time = snapToBar(toTime(t.closed_at_utc), barTimes)
        if (time != null) {
          const win = t.result === 'WIN'
          markers.push({
            time,
            position: 'aboveBar',
            shape: win ? 'circle' : 'square',
            color: win ? GREEN : t.result === 'BREAKEVEN' ? '#a16207' : RED,
            text: `#${t.id} ${t.result ?? ''}`,
          })
        }
      }
    }
    markers.sort((a, b) => (a.time as number) - (b.time as number))
    markersRef.current?.setMarkers(markers)

    // SL/TP/entry lines of the currently pending/open trade
    for (const line of priceLinesRef.current) series.removePriceLine(line)
    priceLinesRef.current = []
    const open = trades.find((t) => t.status === 'OPEN' || t.status === 'PENDING')
    if (open) {
      const lines: { price: number | null; color: string; title: string }[] = [
        { price: open.entry_price, color: BLUE, title: 'Entry' },
        { price: open.sl_price, color: RED, title: 'SL' },
        { price: open.tp1_price, color: GREEN, title: 'TP1' },
        { price: open.tp2_price, color: GREEN, title: 'TP2' },
      ]
      for (const l of lines) {
        if (l.price != null) {
          priceLinesRef.current.push(
            series.createPriceLine({
              price: l.price,
              color: l.color,
              title: l.title,
              lineWidth: 1,
              lineStyle: LineStyle.Dashed,
            }),
          )
        }
      }
    }
  }, [trades, bars])

  return <div ref={containerRef} style={{ width: '100%', height }} />
}
