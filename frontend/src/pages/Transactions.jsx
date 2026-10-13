import { useEffect, useMemo, useState } from 'react';
import { getTransactions } from '../api.js';
import { ErrorState, FlagBadge, Loading, StatusBadge } from '../components/common.jsx';
import { STATUS_LABELS, STATUS_ORDER, csvEscape, fmtDate, money } from '../format.js';
import { go, href, useApp, useAsync } from '../hooks.js';

const COLUMNS = [
  { key: 'transaction_id', label: 'Transaction ID' },
  { key: 'transaction_date', label: 'Date' },
  { key: 'merchant_name', label: 'Merchant' },
  { key: 'transaction_amount', label: 'Amount', num: true },
  { key: 'settlement_status', label: 'Settlement status' },
  { key: 'total_settled_amount', label: 'Settlement amount', num: true },
  { key: 'issue_flag', label: 'Issue' },
];
const FLAG_RANK = { critical: 0, warning: 1, none: 2 };

function exportCsv(rows) {
  const head = ['transaction_id', 'transaction_date', 'merchant_name', 'transaction_amount', 'currency',
    'settlement_status', 'total_settled_amount', 'issue_flag', 'issue'];
  const lines = [head.join(',')].concat(rows.map((t) =>
    [t.transaction_id, t.transaction_date, t.merchant_name, t.transaction_amount, t.currency, t.settlement_status,
      t.total_settled_amount, t.issue_flag, t.issues[0]?.title || ''].map(csvEscape).join(',')));
  const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = 'transactions.csv';
  a.click();
  URL.revokeObjectURL(url);
}

export default function Transactions({ query }) {
  const { asOf, version } = useApp();
  const { data, error, loading, reload } = useAsync(() => getTransactions(asOf), [asOf, version]);
  const [search, setSearch] = useState('');
  const [issue, setIssue] = useState(['critical', 'warning', 'none'].includes(query.issue) ? query.issue : 'all');
  const [sort, setSort] = useState({ key: 'transaction_id', dir: 'asc' });

  useEffect(() => {
    setIssue(['critical', 'warning', 'none'].includes(query.issue) ? query.issue : 'all');
  }, [query.issue]);

  const status = STATUS_ORDER.includes(query.status) ? query.status : 'ALL';
  const all = data?.transactions || [];

  const counts = useMemo(() => {
    const c = { ALL: all.length };
    all.forEach((t) => { c[t.settlement_status] = (c[t.settlement_status] || 0) + 1; });
    return c;
  }, [all]);

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered = all.filter((t) =>
      (status === 'ALL' || t.settlement_status === status) &&
      (issue === 'all' || t.issue_flag === issue) &&
      (!needle || [t.transaction_id, t.merchant_name, t.account_id, t.lifecycle_id].join(' ').toLowerCase().includes(needle)));
    const dir = sort.dir === 'asc' ? 1 : -1;
    return [...filtered].sort((a, b) => {
      let x = a[sort.key], y = b[sort.key];
      if (sort.key === 'issue_flag') { x = FLAG_RANK[x]; y = FLAG_RANK[y]; }
      if (typeof x === 'string') return x.localeCompare(y) * dir;
      return (x - y) * dir;
    });
  }, [all, status, issue, search, sort]);

  const setStatus = (s) => go('/transactions', s === 'ALL' ? undefined : { status: s });
  const toggleSort = (key) => setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' }));
  const filtersActive = status !== 'ALL' || issue !== 'all' || search;

  return (
    <>
      <div className="page-head">
        <h1>Transactions</h1>
        <p>Every transaction with its settlement status and issue flag. Select a row for the full settlement history.</p>
      </div>

      <div className="toolbar">
        <input className="search" type="search" placeholder="Search by ID, merchant or account" aria-label="Search transactions"
               value={search} onChange={(e) => setSearch(e.target.value)} />
        <select className="select" aria-label="Filter by issue" value={issue} onChange={(e) => setIssue(e.target.value)}>
          <option value="all">All issue levels</option>
          <option value="critical">Critical only</option>
          <option value="warning">Warnings only</option>
          <option value="none">No issues</option>
        </select>
        <span className="toolbar__spacer" />
        <button className="btn btn--secondary btn--small" onClick={() => exportCsv(rows)} disabled={!rows.length}>Export CSV</button>
      </div>

      <div className="pills" role="group" aria-label="Filter by settlement status">
        <button className="pill" aria-pressed={status === 'ALL'} onClick={() => setStatus('ALL')}>
          All<span className="pill__count">{counts.ALL ?? 0}</span>
        </button>
        {STATUS_ORDER.map((s) => (
          <button key={s} className="pill" aria-pressed={status === s} onClick={() => setStatus(s)}>
            {STATUS_LABELS[s]}<span className="pill__count">{counts[s] || 0}</span>
          </button>
        ))}
      </div>

      {loading && !data ? <Loading label="Loading transactions…" /> : error ? <ErrorState error={error} onRetry={reload} /> : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {COLUMNS.map((c) => (
                  <th key={c.key} className={c.num ? 'num' : ''} aria-sort={sort.key === c.key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                    <button className="sort-btn" onClick={() => toggleSort(c.key)}>
                      {c.label}{sort.key === c.key ? (sort.dir === 'asc' ? ' ↑' : ' ↓') : ''}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.transaction_id} className={`row-link is-${t.issue_flag}`} tabIndex={0}
                    onClick={() => go(`/transactions/${t.transaction_id}`)}
                    onKeyDown={(e) => e.key === 'Enter' && go(`/transactions/${t.transaction_id}`)}>
                  <td><a className="mono" href={href(`/transactions/${t.transaction_id}`)} onClick={(e) => e.stopPropagation()}>{t.transaction_id}</a></td>
                  <td>{fmtDate(t.transaction_date)}</td>
                  <td>{t.merchant_name}</td>
                  <td className="num">{money(t.transaction_amount, t.currency)}</td>
                  <td><StatusBadge status={t.settlement_status} /></td>
                  <td className="num">{t.settlement_count ? money(t.total_settled_amount, t.currency) : <span className="muted">—</span>}</td>
                  <td><FlagBadge flag={t.issue_flag} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && (
            <div className="empty">
              <h3>No transactions match</h3>
              <p>{filtersActive ? 'Try removing a filter or clearing the search.' : 'There are no transactions yet.'}</p>
              {filtersActive && (
                <button className="btn btn--secondary btn--small" onClick={() => { setSearch(''); setIssue('all'); setStatus('ALL'); }}>
                  Clear filters
                </button>
              )}
            </div>
          )}
        </div>
      )}
      {data && <p className="muted" style={{ fontSize: 13, marginTop: 12 }}>Showing {rows.length} of {all.length} transactions · issues evaluated as of {fmtDate(data.as_of)}</p>}
    </>
  );
}
