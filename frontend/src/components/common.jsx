import { FLAG_LABELS, STATUS_LABELS } from '../format.js';

export function StatusBadge({ status }) {
  return <span className={`badge badge--${status}`}>{STATUS_LABELS[status] || status}</span>;
}

export function FlagBadge({ flag }) {
  return <span className={`badge badge--${flag}`}>{FLAG_LABELS[flag] || flag}</span>;
}

export function Loading({ label = 'Loading…' }) {
  return (
    <div className="state" role="status">
      <div className="spinner" aria-hidden="true" />
      {label}
    </div>
  );
}

export function ErrorState({ error, onRetry }) {
  return (
    <div className="state" role="alert">
      <h3 style={{ fontFamily: 'var(--serif)', fontWeight: 400, fontSize: 26, margin: '0 0 6px', color: 'var(--ink)' }}>
        Something went wrong
      </h3>
      <p style={{ margin: '0 0 18px' }}>{error?.message || 'Unexpected error.'}</p>
      {onRetry && (
        <button className="btn btn--secondary btn--small" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function Kpi({ label, value, note, tone }) {
  return (
    <div className={`card kpi ${tone ? `kpi--${tone}` : ''}`}>
      <p className="kpi__label">{label}</p>
      <p className="kpi__value">{value}</p>
      {note && <p className="kpi__note">{note}</p>}
    </div>
  );
}
