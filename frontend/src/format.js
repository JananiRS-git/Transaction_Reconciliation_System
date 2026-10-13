// Display helpers and shared labels/colours.

export const DEMO_DATE = '2025-08-15'; // the sample data is from August 2025

export const STATUS_LABELS = {
  PENDING: 'Pending',
  PARTIAL: 'Partial',
  FULLY_SETTLED: 'Fully settled',
  OVER_SETTLED: 'Over settled',
  REFUNDED: 'Refunded',
  NOT_APPLICABLE: 'Not applicable',
};

export const STATUS_ORDER = ['PENDING', 'PARTIAL', 'FULLY_SETTLED', 'OVER_SETTLED', 'REFUNDED', 'NOT_APPLICABLE'];

export const STATUS_COLORS = {
  PENDING: '#8a96b4',
  PARTIAL: '#e5a50a',
  FULLY_SETTLED: '#1dbf8a',
  OVER_SETTLED: '#e5483d',
  REFUNDED: '#4d74e6',
  NOT_APPLICABLE: '#c3c8d2',
};

export const FLAG_LABELS = { critical: 'Critical', warning: 'Warning', none: 'No issues' };

export function money(value, currency = 'USD') {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  try {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(value);
  } catch {
    return `${Number(value).toFixed(2)} ${currency}`;
  }
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// "2025-08-14" -> "14 Aug 2025" (no Date object, so no timezone surprises)
export function fmtDate(iso) {
  if (!iso) return '—';
  const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number);
  if (!y || !m || !d) return String(iso);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

export function fmtDateTime(value) {
  if (!value) return '—';
  return `${fmtDate(value)} ${String(value).slice(11, 16)}`.trim();
}

export function percent(x) {
  if (x === null || x === undefined) return '—';
  return `${Math.round(x * 1000) / 10}%`;
}

export function todayIso() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function csvEscape(value) {
  const s = value === null || value === undefined ? '' : String(value);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
