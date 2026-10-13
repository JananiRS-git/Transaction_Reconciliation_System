import { STATUS_COLORS, STATUS_LABELS, STATUS_ORDER, money } from '../format.js';

/** Donut chart of settlement statuses. Clicking a legend row filters the transaction list. */
export function StatusDonut({ counts, onSelect }) {
  const entries = STATUS_ORDER.map((s) => ({ key: s, value: counts[s] || 0 })).filter((e) => e.value > 0);
  const total = entries.reduce((sum, e) => sum + e.value, 0);
  const R = 62;
  const C = 2 * Math.PI * R;
  let offset = 0;

  return (
    <div className="donut">
      <svg width="170" height="170" viewBox="0 0 170 170" role="img" aria-label={`${total} transactions by settlement status`}>
        <g transform="rotate(-90 85 85)">
          <circle cx="85" cy="85" r={R} fill="none" stroke="#eef2f8" strokeWidth="22" />
          {entries.map((e) => {
            const len = (e.value / total) * C;
            const circle = (
              <circle
                key={e.key} cx="85" cy="85" r={R} fill="none" stroke={STATUS_COLORS[e.key]} strokeWidth="22"
                strokeDasharray={`${Math.max(len - 2, 0)} ${C - Math.max(len - 2, 0)}`} strokeDashoffset={-offset}
              />
            );
            offset += len;
            return circle;
          })}
        </g>
        <text x="85" y="84" textAnchor="middle" fontSize="34" fontFamily="var(--serif)" fill="var(--ink)">{total}</text>
        <text x="85" y="104" textAnchor="middle" fontSize="12" fill="var(--ink-3)">transactions</text>
      </svg>
      <ul className="legend">
        {STATUS_ORDER.map((s) => (
          <li key={s}>
            <button onClick={() => onSelect?.(s)} title={`Show ${STATUS_LABELS[s]} transactions`}>
              <span className="legend__dot" style={{ background: STATUS_COLORS[s] }} />
              {STATUS_LABELS[s]}
              <span className="legend__count">{counts[s] || 0}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Simple horizontal bars: items = [{label, value, color, display}] */
export function HBars({ items }) {
  const max = Math.max(...items.map((i) => i.value), 1);
  return (
    <div className="hbars">
      {items.map((i) => (
        <div key={i.label}>
          <div className="hbar__top">
            <span>{i.label}</span>
            <strong>{i.display ?? i.value}</strong>
          </div>
          <div className="hbar__track" role="presentation">
            <div className="hbar__fill" style={{ width: `${(i.value / max) * 100}%`, background: i.color }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ProgressBar({ value }) {
  const pct = Math.max(0, Math.min(1, value || 0)) * 100;
  return (
    <div className="progress" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
      <div className="progress__fill" style={{ width: `${pct}%` }} />
    </div>
  );
}

const shortDate = (iso) => {
  const [, m, d] = iso.split('-');
  return `${Number(d)}/${Number(m)}`;
};

/** Grouped vertical bars of debits vs credits per settlement date. */
export function DailyBars({ data, currency }) {
  if (!data.length) return null;
  const W = 520, H = 190, padL = 46, padB = 28, padT = 10;
  const max = Math.max(...data.flatMap((d) => [d.debits, d.credits]), 1);
  const slot = (W - padL) / data.length;
  const barW = Math.min(34, slot / 3);
  const y = (v) => padT + (H - padT - padB) * (1 - v / max);
  const ticks = [0, max / 2, max];

  return (
    <div>
      <div className="chart-legend">
        <span><i className="legend__dot" style={{ background: '#1dbf8a' }} /> Debits</span>
        <span><i className="legend__dot" style={{ background: '#4d74e6' }} /> Credits</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Settlement debits and credits by date">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W} y1={y(t)} y2={y(t)} stroke="#e8edf5" />
            <text x={padL - 8} y={y(t) + 4} textAnchor="end" fontSize="11" fill="var(--ink-3)">
              {t >= 1000 ? `${Math.round(t / 100) / 10}k` : Math.round(t)}
            </text>
          </g>
        ))}
        {data.map((d, i) => {
          const cx = padL + slot * i + slot / 2;
          return (
            <g key={d.date}>
              <rect x={cx - barW - 2} y={y(d.debits)} width={barW} height={Math.max(H - padB - y(d.debits), 0)} rx="4" fill="#1dbf8a">
                <title>{`${d.date} debits ${money(d.debits, currency)}`}</title>
              </rect>
              <rect x={cx + 2} y={y(d.credits)} width={barW} height={Math.max(H - padB - y(d.credits), 0)} rx="4" fill="#4d74e6">
                <title>{`${d.date} credits ${money(d.credits, currency)}`}</title>
              </rect>
              <text x={cx} y={H - 8} textAnchor="middle" fontSize="11" fill="var(--ink-3)">{shortDate(d.date)}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
