import { useState, useEffect, useCallback } from 'react'
import {
  ResponsiveContainer,
  LineChart, Line,
  BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ReferenceLine,
} from 'recharts'
import { api } from './api'
import './index.css'

// ─────────────────────────────────────────────────────────────────
// Formatting helpers
// ─────────────────────────────────────────────────────────────────

function fmtMW(val, dp = 0) {
  if (val == null) return '—'
  return `${Number(val).toLocaleString('en-GB', { minimumFractionDigits: dp, maximumFractionDigits: dp })}`
}

function fmtPct(val) {
  if (val == null) return '—'
  return `${val.toFixed(1)}%`
}

function fmtTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })
}

function fmtDatetime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('en-GB', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
    timeZone: 'UTC', hour12: false,
  }) + ' UTC'
}

function errorClass(e) {
  if (e == null) return ''
  if (e > 50) return 'error-positive'
  if (e < -50) return 'error-negative'
  return 'error-zero'
}

/** Presentation-only: bucket hourly errors for simple “too high / too low / close” counts */
function bucketErrors(intervals, closeMw = 50) {
  let tooHigh = 0
  let tooLow = 0
  let close = 0
  for (const r of intervals || []) {
    const e = r.error_mw
    if (e == null) continue
    if (e > closeMw) tooHigh++
    else if (e < -closeMw) tooLow++
    else close++
  }
  return { tooHigh, tooLow, close, total: tooHigh + tooLow + close }
}

/** Plain-language quality label from MAPE (display only) */
function guessQuality(mape) {
  if (mape == null) return { emoji: '❓', label: 'Still loading', tone: 'muted' }
  if (mape < 12) return { emoji: '🌟', label: 'Excellent guesses', tone: 'great' }
  if (mape < 22) return { emoji: '🙂', label: 'Pretty good guesses', tone: 'good' }
  if (mape < 35) return { emoji: '😐', label: 'Okay guesses', tone: 'ok' }
  return { emoji: '😕', label: 'Guesses were often far off', tone: 'poor' }
}

function biasStory(biasMw) {
  if (biasMw == null) return 'We are still calculating the pattern.'
  if (biasMw > 50) return 'Usually we guessed MORE wind than really blew.'
  if (biasMw < -50) return 'Usually we guessed LESS wind than really blew.'
  return 'We did not mostly guess too high or too low — pretty balanced.'
}

function exportCSV(matched, filename = 'windsight_forecast_accuracy.csv') {
  if (!matched?.length) return
  const headers = ['delivery_time', 'forecast_mw', 'actual_mw', 'error_mw', 'publish_time', 'lead_time_h', 'cutoff']
  const rows = matched.map(r => headers.map(h => r[h] ?? '').join(','))
  const blob = new Blob([headers.join(',') + '\n' + rows.join('\n')], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}

// ─────────────────────────────────────────────────────────────────
// Custom chart tooltip
// ─────────────────────────────────────────────────────────────────

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="custom-tooltip">
      <div className="tooltip-title">{label} UTC</div>
      {payload.map((p, i) => (
        <div className="tooltip-row" key={i}>
          <span className="tooltip-label">
            <span className="tooltip-dot" style={{ background: p.color }} />
            {p.name}
          </span>
          <span className="tooltip-value">{fmtMW(p.value)} MW</span>
        </div>
      ))}
      {payload[0]?.payload?.error_mw != null && (
        <div className="tooltip-row" style={{ borderTop: '1px solid rgba(255,255,255,0.07)', marginTop: 6, paddingTop: 6 }}>
          <span className="tooltip-label">Error</span>
          <span className={`tooltip-value ${errorClass(payload[0].payload.error_mw)}`}>
            {payload[0].payload.error_mw > 0 ? '+' : ''}{fmtMW(payload[0].payload.error_mw)} MW
          </span>
        </div>
      )}
      {payload[0]?.payload?.publish_time && (
        <div className="tooltip-row">
          <span className="tooltip-label">Published</span>
          <span className="tooltip-value" style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>
            {fmtDatetime(payload[0].payload.publish_time)}
          </span>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────
// Header
// ─────────────────────────────────────────────────────────────────

function Header({ apiStatus, viewMode, onViewModeChange }) {
  return (
    <header className="site-header">
      <div className="header-brand">
        <div className="brand-icon">💨</div>
        <div className="brand-text">
          <h1>WindSight UK</h1>
          <p>{viewMode === 'simple' ? 'Did our wind guess match reality?' : 'National Wind Generation Forecast Accuracy'}</p>
        </div>
      </div>
      <div className="header-meta">
        <div className="view-toggle" role="tablist" aria-label="Dashboard view">
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === 'simple'}
            className={`view-toggle-btn ${viewMode === 'simple' ? 'active' : ''}`}
            onClick={() => onViewModeChange('simple')}
          >
            Simple story
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={viewMode === 'expert'}
            className={`view-toggle-btn ${viewMode === 'expert' ? 'active' : ''}`}
            onClick={() => onViewModeChange('expert')}
          >
            Expert charts
          </button>
        </div>
        <span className="period-badge">January 2026</span>
        <div className="status-indicator">
          <span className={`status-dot ${apiStatus}`} />
          {apiStatus === 'healthy' ? 'API Online' : apiStatus === 'loading' ? 'Connecting…' : 'API Error'}
        </div>
      </div>
    </header>
  )
}

// ─────────────────────────────────────────────────────────────────
// KPI Cards
// ─────────────────────────────────────────────────────────────────

function KpiCard({ label, value, unit, sub, accent }) {
  return (
    <div className="kpi-card" style={{ '--kpi-accent': accent }}>
      <div className="kpi-label">{label}</div>
      {value == null
        ? <div className="kpi-null">—</div>
        : <div className="kpi-value">{value}<span className="kpi-unit">{unit}</span></div>
      }
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────
// Forecast vs Actual chart
// ─────────────────────────────────────────────────────────────────

function ForecastActualChart({ intervals, loading, simple = false }) {
  const data = intervals.map(r => ({
    time: fmtTime(r.delivery_time),
    forecast_mw: r.forecast_mw,
    actual_mw: r.actual_mw,
    error_mw: r.error_mw,
    publish_time: r.publish_time,
  }))

  return (
    <div className="chart-wrap">
      {loading ? (
        <div className="state-box">
          <div className="loading-spinner" />
        </div>
      ) : !data.length ? (
        <div className="state-box">
          <div className="state-box-icon">📭</div>
          <div className="state-box-title">No matched intervals</div>
          <div className="state-box-msg">No data returned for this date. Check that the date is within January 2026 and both APIs returned data.</div>
        </div>
      ) : (
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
            <XAxis dataKey="time" tick={{ fill: 'var(--chart-tick)', fontSize: 11 }} tickLine={false} axisLine={false} />
            <YAxis
              tick={{ fill: 'var(--chart-tick)', fontSize: 11 }} tickLine={false} axisLine={false}
              tickFormatter={v => `${(v / 1000).toFixed(0)}k`}
              width={40}
            />
            <Tooltip content={<ChartTooltip />} />
            <Legend
              wrapperStyle={{ fontSize: '0.75rem', paddingTop: '8px' }}
              formatter={(v) => <span style={{ color: 'var(--text-secondary)' }}>{v}</span>}
            />
            <Line
              type="monotone" dataKey="forecast_mw" name={simple ? 'Our guess' : 'Forecast'}
              stroke="var(--chart-forecast)" strokeWidth={2.5} dot={false} activeDot={{ r: 4, stroke: 'var(--chart-forecast)', fill: '#0c0e16' }}
            />
            <Line
              type="monotone" dataKey="actual_mw" name={simple ? 'What really happened' : 'Actual'}
              stroke="var(--chart-actual)" strokeWidth={2.5} dot={false} activeDot={{ r: 4, stroke: 'var(--chart-actual)', fill: '#0c0e16' }}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────
// Error Over Time chart
// ─────────────────────────────────────────────────────────────────

function ErrorChart({ intervals }) {
  const data = intervals.map(r => ({
    time: fmtTime(r.delivery_time),
    error_mw: r.error_mw,
  }))

  return (
    <div className="chart-wrap-sm">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 8 }} barSize={4}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
          <XAxis dataKey="time" tick={{ fill: 'var(--chart-tick)', fontSize: 10 }} tickLine={false} axisLine={false} />
          <YAxis tick={{ fill: 'var(--chart-tick)', fontSize: 10 }} tickLine={false} axisLine={false} width={40} />
          <Tooltip formatter={(v) => [`${v > 0 ? '+' : ''}${fmtMW(v)} MW`, 'Error']} labelFormatter={l => `${l} UTC`} contentStyle={{ background: 'var(--surface-2)', border: '1px solid var(--border-default)', borderRadius: '8px', fontSize: '0.75rem' }} />
          <ReferenceLine y={0} stroke="var(--chart-refline)" />
          <Bar dataKey="error_mw" name="Error (MW)"
            fill="var(--chart-error)"
            // Color each bar by sign
            label={false}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────
// Lead-time section
// ─────────────────────────────────────────────────────────────────

function LeadTimeSection({ bands, loading, error }) {
  if (loading) return <div className="state-box"><div className="loading-spinner" /></div>
  if (error) return <div className="state-box"><div className="state-box-title">Could not load lead-time analysis</div><div className="state-box-msg">{error}</div></div>
  if (!bands?.length) return <div className="state-box"><div className="state-box-msg">No lead-time data available.</div></div>

  return (
    <div className="lead-time-grid">
      {bands.map(b => (
        <div className="lt-card" key={b.band}>
          <div className="lt-band-name">{b.band}</div>
          <div className="lt-count">{b.count} matched intervals</div>
          <div className="lt-metric-row">
            <span className="lt-metric-label">MAE</span>
            <span className="lt-metric-value">{b.mae_mw != null ? `${fmtMW(b.mae_mw)} MW` : '—'}</span>
          </div>
          <div className="lt-metric-row">
            <span className="lt-metric-label">RMSE</span>
            <span className="lt-metric-value">{b.rmse_mw != null ? `${fmtMW(b.rmse_mw)} MW` : '—'}</span>
          </div>
          <div className="lt-metric-row">
            <span className="lt-metric-label">Bias</span>
            <span className="lt-metric-value" style={{ color: b.bias_mw > 0 ? 'var(--red-400)' : b.bias_mw < 0 ? 'var(--green-400)' : 'var(--text-primary)' }}>
              {b.bias_mw != null ? `${b.bias_mw > 0 ? '+' : ''}${fmtMW(b.bias_mw)} MW` : '—'}
            </span>
          </div>
          <div className="lt-metric-row">
            <span className="lt-metric-label">MAPE</span>
            <span className="lt-metric-value">{b.mape_pct != null ? fmtPct(b.mape_pct) : '—'}</span>
          </div>
        </div>
      ))}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────
// Data table
// ─────────────────────────────────────────────────────────────────

function IntervalTable({ intervals, loading }) {
  const PAGE = 48
  const [page, setPage] = useState(0)

  if (loading) return <div className="state-box"><div className="loading-spinner" /></div>
  if (!intervals?.length) return <div className="state-box"><div className="state-box-msg">No intervals to display.</div></div>

  const totalPages = Math.ceil(intervals.length / PAGE)
  const slice = intervals.slice(page * PAGE, (page + 1) * PAGE)

  return (
    <>
      <div className="export-row">
        <button className="btn btn-ghost" onClick={() => exportCSV(intervals)}>⬇ Export CSV</button>
      </div>
      <div className="data-table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Delivery (UTC)</th>
              <th>Forecast (MW)</th>
              <th>Actual (MW)</th>
              <th>Error (MW)</th>
              <th>Lead Time (h)</th>
              <th>Published (UTC)</th>
              <th>Cutoff (UTC)</th>
            </tr>
          </thead>
          <tbody>
            {slice.map((r, i) => (
              <tr key={i}>
                <td>{fmtDatetime(r.delivery_time)}</td>
                <td>{fmtMW(r.forecast_mw)}</td>
                <td>{fmtMW(r.actual_mw)}</td>
                <td className={errorClass(r.error_mw)}>{r.error_mw > 0 ? '+' : ''}{fmtMW(r.error_mw)}</td>
                <td>{r.lead_time_h?.toFixed(1)}h</td>
                <td>{fmtDatetime(r.publish_time)}</td>
                <td>{fmtDatetime(r.cutoff)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="toolbar table-pagination">
          <button className="btn btn-ghost" onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}>← Prev</button>
          <span className="section-note">Page {page + 1} of {totalPages}</span>
          <button className="btn btn-ghost" onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page === totalPages - 1}>Next →</button>
        </div>
      )}
    </>
  )
}

// ─────────────────────────────────────────────────────────────────
// Simple story view (plain language — same data, no API changes)
// ─────────────────────────────────────────────────────────────────

function SimpleMeter({ label, value, max, hint, color }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div className="simple-meter">
      <div className="simple-meter-top">
        <span className="simple-meter-label">{label}</span>
        <span className="simple-meter-value">{value}</span>
      </div>
      <div className="simple-meter-track">
        <div className="simple-meter-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      {hint && <div className="simple-meter-hint">{hint}</div>}
    </div>
  )
}

function SimpleMonthStory({ summaryLoading, summaryError, m, coverage }) {
  if (summaryLoading) {
    return (
      <div className="story-hero state-box">
        <div className="loading-spinner" />
        <p className="story-lead" style={{ marginTop: 16 }}>Loading January’s wind guesses…</p>
      </div>
    )
  }
  if (summaryError) {
    return (
      <div className="story-hero story-hero--warn">
        <div className="story-hero-icon">⚠️</div>
        <h2 className="story-title">Could not load the story</h2>
        <p className="story-lead">{summaryError}</p>
      </div>
    )
  }

  const quality = guessQuality(m?.mape_pct)
  const matched = coverage?.matched_count ?? 0
  const expected = coverage?.expected_hours ?? 744

  return (
    <div className="story-hero">
      <div className="story-hero-icon" aria-hidden>{quality.emoji}</div>
      <h2 className="story-title">How good were the wind guesses in January?</h2>
      <p className="story-lead">
        Imagine someone tries to guess how much electricity UK wind will make each hour.
        We compare that <strong>guess</strong> to <strong>what really happened</strong>.
      </p>
      <div className="story-verdict">
        <span className={`story-badge story-badge--${quality.tone}`}>{quality.label}</span>
        {m?.mae_mw != null && (
          <span className="story-stat">
            Typical miss: about <strong>{fmtMW(m.mae_mw)} MW</strong> per hour
          </span>
        )}
      </div>
      <SimpleMeter
        label="Hours we could check (guess + reality both known)"
        value={matched}
        max={expected}
        hint={`${fmtPct(coverage?.coverage_pct)} of the month · ${expected - matched} hours missing data`}
        color="var(--accent-mint)"
      />
      <p className="story-footnote">{biasStory(m?.bias_mw)}</p>
    </div>
  )
}

function SimpleDayScoreboard({ intervals, dayMetrics, selectedDate, loading }) {
  if (loading) return <div className="state-box"><div className="loading-spinner" /></div>
  const { tooHigh, tooLow, close, total } = bucketErrors(intervals)
  const quality = guessQuality(dayMetrics?.mape_pct)

  return (
    <div className="scoreboard">
      <h3 className="scoreboard-title">This day in three buckets</h3>
      <p className="scoreboard-lead">
        For <strong>{selectedDate}</strong>, each hour is counted once. “Close” means the guess was within about 50 MW of reality.
      </p>
      <div className="scoreboard-grid">
        <div className="score-card score-card--high">
          <div className="score-card-emoji" aria-hidden>⬆️</div>
          <div className="score-card-num">{tooHigh}</div>
          <div className="score-card-label">Guessed too much wind</div>
        </div>
        <div className="score-card score-card--close">
          <div className="score-card-emoji" aria-hidden>✅</div>
          <div className="score-card-num">{close}</div>
          <div className="score-card-label">Pretty close</div>
        </div>
        <div className="score-card score-card--low">
          <div className="score-card-emoji" aria-hidden>⬇️</div>
          <div className="score-card-num">{tooLow}</div>
          <div className="score-card-label">Guessed too little wind</div>
        </div>
      </div>
      {total > 0 && (
        <p className="scoreboard-summary">
          Out of <strong>{total}</strong> hours checked: {quality.emoji} {quality.label}.
          {dayMetrics?.mae_mw != null && <> Average miss this day: <strong>{fmtMW(dayMetrics.mae_mw)} MW</strong>.</>}
        </p>
      )}
    </div>
  )
}

function SimpleLeadTimeStory({ bands, loading, error }) {
  if (loading) return <div className="state-box"><div className="loading-spinner" /></div>
  if (error) return <div className="state-box"><div className="state-box-msg">{error}</div></div>
  if (!bands?.length) return <div className="state-box"><div className="state-box-msg">No data yet.</div></div>

  return (
    <div className="simple-lt-list">
      {bands.map(b => (
        <div className="simple-lt-row" key={b.band}>
          <div>
            <div className="simple-lt-when">{b.band}</div>
            <div className="simple-lt-plain">How early the guess was made · {b.count} hours</div>
          </div>
          <div className="simple-lt-miss">
            Typical miss: <strong>{b.mae_mw != null ? `${fmtMW(b.mae_mw)} MW` : '—'}</strong>
          </div>
        </div>
      ))}
    </div>
  )
}

function SimpleDashboard({
  summaryLoading, summaryError, m, coverage,
  selectedDate, setSelectedDate, fetchDay, dayLoading, dayError,
  intervals, dayData, ltData, ltLoading, ltError,
}) {
  const [showNumbers, setShowNumbers] = useState(false)

  return (
    <>
      <SimpleMonthStory
        summaryLoading={summaryLoading}
        summaryError={summaryError}
        m={m}
        coverage={coverage}
      />

      <div className="story-callout">
        <span className="story-callout-icon" aria-hidden>📅</span>
        <div>
          <strong>Rule we use:</strong> only guesses sent before <strong>11:00 UTC the day before</strong> count
          (like deciding tomorrow’s plan before lunch today).
        </div>
      </div>

      <section className="dashboard-section">
        <div className="section-header">
          <span className="section-title">Pick one day to explore</span>
        </div>
        <div className="filter-bar toolbar">
          <span className="toolbar-label">Day</span>
          <input
            id="delivery-date-input"
            type="date"
            className="date-input"
            min="2026-01-01"
            max="2026-01-31"
            value={selectedDate}
            onChange={e => setSelectedDate(e.target.value)}
          />
          <button className="btn btn-ghost" onClick={() => fetchDay(selectedDate)} disabled={dayLoading}>
            {dayLoading ? <><div className="loading-spinner" style={{ width: 12, height: 12 }} /> Loading</> : '↻ Refresh'}
          </button>
        </div>
        {dayError && <div className="warning-banner">⚠ {dayError}</div>}

        <div className="panel">
          <div className="panel-head">
            <div className="panel-title"><span className="panel-title-icon">🎨</span> Guess vs reality — {selectedDate}</div>
            <div className="panel-subtitle">
              Purple line = our guess. Teal line = what wind really produced. When lines hug each other, the guess was good.
            </div>
          </div>
          <div className="panel-body">
            <div className="chart-legend" aria-hidden>
              <div className="chart-legend-item">
                <span className="chart-legend-swatch forecast" />
                Our guess
              </div>
              <div className="chart-legend-item">
                <span className="chart-legend-swatch actual" />
                What really happened
              </div>
            </div>
            <ForecastActualChart intervals={intervals} loading={dayLoading} simple />
          </div>
        </div>

        <div className="panel">
          <div className="panel-body">
            <SimpleDayScoreboard
              intervals={intervals}
              dayMetrics={dayData?.metrics}
              selectedDate={selectedDate}
              loading={dayLoading}
            />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <div className="panel-title"><span className="panel-title-icon">⏰</span> Does it matter how early we guessed?</div>
            <div className="panel-subtitle">Earlier guesses are harder. Smaller “typical miss” means better accuracy for that group.</div>
          </div>
          <div className="panel-body">
            <SimpleLeadTimeStory bands={ltData?.lead_time_bands} loading={ltLoading} error={ltError} />
          </div>
        </div>

        <div className="simple-expand">
          <button
            type="button"
            className="btn btn-ghost simple-expand-btn"
            onClick={() => setShowNumbers(v => !v)}
            aria-expanded={showNumbers}
          >
            {showNumbers ? 'Hide the big number table ▲' : 'Show all hourly numbers (detailed table) ▼'}
          </button>
          {showNumbers && (
            <div className="panel" style={{ marginTop: 14 }}>
              <div className="panel-body">
                <IntervalTable intervals={intervals} loading={dayLoading} />
              </div>
            </div>
          )}
        </div>

        <p className="simple-tip">
          Want MAE, RMSE, bias, and raw error bars? Switch to <strong>Expert charts</strong> at the top.
        </p>
      </section>
    </>
  )
}

// ─────────────────────────────────────────────────────────────────
// Main App
// ─────────────────────────────────────────────────────────────────

export default function App() {
  const [viewMode, setViewMode] = useState('simple')
  const [apiStatus, setApiStatus] = useState('loading')

  // Summary (whole month)
  const [summary, setSummary] = useState(null)
  const [summaryLoading, setSummaryLoading] = useState(true)
  const [summaryError, setSummaryError] = useState(null)

  // Day detail
  const [selectedDate, setSelectedDate] = useState('2026-01-15')
  const [dayData, setDayData] = useState(null)
  const [dayLoading, setDayLoading] = useState(false)
  const [dayError, setDayError] = useState(null)

  // Lead-time
  const [ltData, setLtData] = useState(null)
  const [ltLoading, setLtLoading] = useState(true)
  const [ltError, setLtError] = useState(null)

  // ── health check ──────────────────────────────────────────────
  useEffect(() => {
    api.health()
      .then(() => setApiStatus('healthy'))
      .catch(() => setApiStatus('error'))
  }, [])

  // ── monthly summary ───────────────────────────────────────────
  useEffect(() => {
    setSummaryLoading(true)
    setSummaryError(null)
    api.forecastSummary('2026-01-01', '2026-01-31')
      .then(d => { setSummary(d); setSummaryLoading(false) })
      .catch(e => { setSummaryError(e.message); setSummaryLoading(false) })
  }, [])

  // ── lead-time breakdown ─────────────────────────────────────
  useEffect(() => {
    setLtLoading(true)
    api.leadTimes('2026-01-01', '2026-01-31')
      .then(d => { setLtData(d); setLtLoading(false) })
      .catch(e => { setLtError(e.message); setLtLoading(false) })
  }, [])

  // ── day detail ───────────────────────────────────────────────
  const fetchDay = useCallback((date) => {
    setDayLoading(true)
    setDayError(null)
    api.forecastDay(date)
      .then(d => { setDayData(d); setDayLoading(false) })
      .catch(e => { setDayError(e.message); setDayLoading(false) })
  }, [])

  useEffect(() => { fetchDay(selectedDate) }, [selectedDate, fetchDay])

  const m = summary?.summary_metrics
  const coverage = summary?.coverage
  const intervals = dayData?.intervals || []

  return (
    <div className={`dashboard-layout ${viewMode === 'simple' ? 'mode-simple' : 'mode-expert'}`}>
      <Header apiStatus={apiStatus} viewMode={viewMode} onViewModeChange={setViewMode} />

      <main className="dashboard-main">

        {viewMode === 'simple' ? (
          <SimpleDashboard
            summaryLoading={summaryLoading}
            summaryError={summaryError}
            m={m}
            coverage={coverage}
            selectedDate={selectedDate}
            setSelectedDate={setSelectedDate}
            fetchDay={fetchDay}
            dayLoading={dayLoading}
            dayError={dayError}
            intervals={intervals}
            dayData={dayData}
            ltData={ltData}
            ltLoading={ltLoading}
            ltError={ltError}
          />
        ) : (
        <>

        {/* ── Cutoff info ── */}
        <div className="cutoff-info">
          <div className="cutoff-info-icon" aria-hidden>🎯</div>
          <div>
            <div className="cutoff-info-title">Day-ahead decision cutoff</div>
            <strong>11:00 UTC</strong> on the calendar day before each delivery date
            (an assignment modeling assumption to validate with the buyer).
            Only forecasts published at or before this cutoff are used in accuracy calculations.
          </div>
        </div>

        {/* ── KPI Cards ── */}
        <section className="dashboard-section">
        <div className="section-header">
          <span className="section-title">January 2026 summary</span>
          {coverage ? (
            <div className="coverage-pills">
              <span className="coverage-pill"><strong>{coverage.matched_count}</strong> / {coverage.expected_hours} matched</span>
              <span className="coverage-pill"><strong>{fmtPct(coverage.coverage_pct)}</strong> coverage</span>
              <span className="coverage-pill">{coverage.missing_actual_count} missing actual</span>
              <span className="coverage-pill">{coverage.missing_forecast_count} missing forecast</span>
            </div>
          ) : (
            <span className="section-note">Loading coverage…</span>
          )}
        </div>
        <div className="kpi-grid">
          {summaryLoading ? (
            <div className="state-box" style={{ gridColumn: '1/-1' }}>
              <div className="loading-spinner" />
              <div style={{ marginTop: 12, color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                Fetching January 2026 data from Elexon BMRS…<br />
                <span style={{ fontSize: '0.72rem' }}>(First load may take 20–60 s while the cache is built)</span>
              </div>
            </div>
          ) : summaryError ? (
            <div className="state-box" style={{ gridColumn: '1/-1' }}>
              <div className="state-box-icon">⚠️</div>
              <div className="state-box-title">Could not load summary</div>
              <div className="state-box-msg">{summaryError}<br /><br />
                Make sure the backend is running: <code>uvicorn main:app --reload --port 8000</code>
              </div>
            </div>
          ) : (
            <>
              <KpiCard label="MAE" value={fmtMW(m?.mae_mw)} unit="MW" sub="Mean absolute error" accent="var(--accent-cyan)" />
              <KpiCard label="RMSE" value={fmtMW(m?.rmse_mw)} unit="MW" sub="Root mean square error" accent="var(--accent-violet)" />
              <KpiCard
                label="Bias"
                value={m?.bias_mw != null ? (m.bias_mw > 0 ? '+' : '') + fmtMW(m.bias_mw) : null}
                unit="MW"
                sub={m?.bias_mw > 0 ? 'Systematic overforecast' : m?.bias_mw < 0 ? 'Systematic underforecast' : ''}
                accent={m?.bias_mw > 0 ? 'var(--red-400)' : m?.bias_mw < 0 ? 'var(--green-400)' : 'var(--text-muted)'}
              />
              <KpiCard label="MAPE" value={m?.mape_pct != null ? m.mape_pct.toFixed(1) : null} unit="%" sub={`n=${m?.n_mape ?? 0} (zero actuals excluded)`} accent="var(--accent-gold)" />
              <KpiCard label="Coverage" value={coverage?.coverage_pct != null ? coverage.coverage_pct.toFixed(1) : null} unit="%" sub={`${coverage?.matched_count ?? 0} of ${coverage?.expected_hours ?? 744} expected hours matched`} accent="var(--accent-mint)" />
            </>
          )}
        </div>
        </section>

        {/* ── Filters ── */}
        <section className="dashboard-section">
        <div className="section-header">
          <span className="section-title">Daily forecast accuracy</span>
          <span className="section-note">Pick a delivery day in January 2026 to inspect hourly forecast vs actual.</span>
        </div>
        <div className="filter-bar toolbar">
          <span className="toolbar-label">Delivery date</span>
          <input
            id="delivery-date-input"
            type="date"
            className="date-input"
            min="2026-01-01"
            max="2026-01-31"
            value={selectedDate}
            onChange={e => setSelectedDate(e.target.value)}
          />
          <button id="refresh-btn" className="btn btn-ghost" onClick={() => fetchDay(selectedDate)} disabled={dayLoading}>
            {dayLoading ? <><div className="loading-spinner" style={{ width: 12, height: 12 }} /> Loading</> : '↻ Refresh'}
          </button>
        </div>

        {dayError && (
          <div className="warning-banner">⚠ {dayError}</div>
        )}

        {/* ── Forecast vs Actual chart ── */}
        <div className="panel">
          <div className="panel-head">
            <div className="panel-title"><span className="panel-title-icon">📈</span> Forecast vs actual — {selectedDate}</div>
            <div className="panel-subtitle">
              Day-ahead forecast compared to actual wind generation (MW), hourly resolution.
              Forecast = latest publication at or before 11:00 UTC the previous day.
            </div>
          </div>
          <div className="panel-body">
            <div className="chart-legend" aria-hidden>
              <div className="chart-legend-item">
                <span className="chart-legend-swatch forecast" />
                Forecast (MW)
              </div>
              <div className="chart-legend-item">
                <span className="chart-legend-swatch actual" />
                Actual wind (MW)
              </div>
              <span className="chart-legend-hint">Hover chart for values · Times in UTC</span>
            </div>
            <ForecastActualChart intervals={intervals} loading={dayLoading} />
          </div>
        </div>

        {/* ── Error chart + Lead-time side by side ── */}
        <div className="two-col">
          <div className="panel">
            <div className="panel-head">
              <div className="panel-title"><span className="panel-title-icon">📉</span> Forecast error — {selectedDate}</div>
              <div className="panel-subtitle">Error = forecast − actual (MW). Positive bars = overforecast; below zero = underforecast.</div>
            </div>
            <div className="panel-body">
              {dayLoading ? <div className="state-box"><div className="loading-spinner" /></div>
                : <>
                  <div className="error-sign-legend" aria-hidden>
                    <span><span className="dot-up" /> Overforecast (error &gt; 0)</span>
                    <span className="error-negative">Underforecast (error &lt; 0)</span>
                  </div>
                  <ErrorChart intervals={intervals} />
                </>
              }
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <div className="panel-title"><span className="panel-title-icon">⏱</span> Day metrics</div>
              <div className="panel-subtitle">Aggregated accuracy for {selectedDate}.</div>
            </div>
            <div className="panel-body">
              {dayLoading ? <div className="state-box"><div className="loading-spinner" /></div>
                : dayData?.metrics ? (
                  <div className="lead-time-grid" style={{ gridTemplateColumns: '1fr' }}>
                    <div className="lt-card">
                      <div className="lt-band-name">Daily summary</div>
                      <div className="lt-count">{dayData.count} hourly intervals · {selectedDate}</div>
                      <div className="lt-metric-row"><span className="lt-metric-label">MAE</span><span className="lt-metric-value">{fmtMW(dayData.metrics.mae_mw)} MW</span></div>
                      <div className="lt-metric-row"><span className="lt-metric-label">RMSE</span><span className="lt-metric-value">{fmtMW(dayData.metrics.rmse_mw)} MW</span></div>
                      <div className="lt-metric-row">
                        <span className="lt-metric-label">Bias</span>
                        <span className="lt-metric-value" style={{ color: dayData.metrics.bias_mw > 0 ? 'var(--red-400)' : 'var(--green-400)' }}>
                          {dayData.metrics.bias_mw > 0 ? '+' : ''}{fmtMW(dayData.metrics.bias_mw)} MW
                        </span>
                      </div>
                      <div className="lt-metric-row"><span className="lt-metric-label">MAPE</span><span className="lt-metric-value">{fmtPct(dayData.metrics.mape_pct)}</span></div>
                    </div>
                  </div>
                ) : <div className="state-box"><div className="state-box-msg">No metrics for selected date.</div></div>
              }
            </div>
          </div>
        </div>

        {/* ── Lead-time analysis ── */}
        <div className="panel">
          <div className="panel-head">
            <div className="panel-title"><span className="panel-title-icon">🎯</span> Lead-time accuracy — January 2026</div>
            <div className="panel-subtitle">
              Metrics grouped by how far ahead the forecast was published.
              ~24h band = published ≥20 h before delivery (typical day-ahead);
              10–20h = shorter lead still before cutoff. Under 10h cannot qualify with the 11:00 UTC cutoff rule.
            </div>
          </div>
          <div className="panel-body">
            <LeadTimeSection bands={ltData?.lead_time_bands} loading={ltLoading} error={ltError} />
          </div>
        </div>
        </section>

        {/* ── Data table ── */}
        <section className="dashboard-section">
        <div className="panel">
          <div className="panel-head">
            <div className="panel-title"><span className="panel-title-icon">📋</span> Interval detail — {selectedDate}</div>
            <div className="panel-subtitle">
              Matched delivery hours only. {dayData?.coverage ? `${dayData.coverage.missing_actual_count} missing actual and ${dayData.coverage.missing_forecast_count} missing forecast out of ${dayData.coverage.expected_hours} expected hours.` : 'Missing intervals are excluded from the metrics.'}
            </div>
          </div>
          <div className="panel-body">
            <IntervalTable intervals={intervals} loading={dayLoading} />
          </div>
        </div>
        </section>

        </>
        )}

      </main>
    </div>
  )
}
