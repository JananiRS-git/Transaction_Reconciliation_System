import { getTransaction } from '../api.js';
import { ErrorState, FlagBadge, Loading, StatusBadge } from '../components/common.jsx';
import { fmtDate, fmtDateTime, money } from '../format.js';
import { href, useApp, useAsync } from '../hooks.js';

function Timeline({ events, amount, currency }) {
  return (
    <ol className="timeline">
      {events.map((e, i) => {
        const isMoney = e.kind === 'debit' || e.kind === 'credit';
        const ratio = amount > 0 ? Math.max(0, Math.min(1, e.running_net / amount)) : 0;
        return (
          <li key={`${e.date}-${i}`} className={`tl tl--${e.kind} ${e.overdue ? 'is-overdue' : ''}`}>
            <span className="tl__dot" aria-hidden="true" />
            <div className="tl__head">
              <span>
                <span className="tl__label">{e.label}</span>
                <br />
                <span className="tl__date">{fmtDate(e.date)}{e.kind === 'deadline' && (e.overdue ? ' · overdue' : ' · upcoming')}</span>
              </span>
              {e.kind !== 'deadline' && (
                <span className="tl__amount">
                  {e.kind === 'credit' ? '−' : e.kind === 'debit' ? '+' : ''}{money(e.amount, currency)}
                </span>
              )}
            </div>
            {isMoney && (
              <>
                <div className={`tl__bar ${e.running_net > amount ? 'is-over' : ''}`} aria-hidden="true"><span style={{ width: `${ratio * 100}%` }} /></div>
                <div className="tl__net">Net settled so far: {money(e.running_net, currency)} of {money(amount, currency)}</div>
              </>
            )}
          </li>
        );
      })}
    </ol>
  );
}

export default function TransactionDetail({ id }) {
  const { asOf, version } = useApp();
  const { data: t, error, loading, reload } = useAsync(() => getTransaction(id, asOf), [id, asOf, version]);

  const back = <a className="crumb" href={href('/transactions')}>← All transactions</a>;
  if (loading && !t) return <div className="page-head">{back}<Loading /></div>;
  if (error) return <div className="page-head">{back}<ErrorState error={error} onRetry={error.message.includes('not found') ? undefined : reload} /></div>;

  const cur = t.currency;
  const owing = t.over_settled_amount > 0
    ? { label: 'Over-settled by', value: money(t.over_settled_amount, cur), bad: true }
    : { label: 'Still outstanding', value: money(t.outstanding_amount, cur), bad: t.outstanding_amount > 0 && t.issue_flag === 'critical' };

  return (
    <>
      <div className="page-head">
        {back}
        <h1>{t.merchant_name}</h1>
        <p style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="mono">{t.transaction_id}</span>
          <StatusBadge status={t.settlement_status} />
          <FlagBadge flag={t.issue_flag} />
        </p>
      </div>

      <div className="detail-grid">
        <div className="card">
          <h2>Transaction information</h2>
          <p className="card__sub">As recorded when the transaction completed.</p>
          <dl className="facts">
            <div><dt>Transaction ID</dt><dd className="mono">{t.transaction_id}</dd></div>
            <div><dt>Lifecycle ID</dt><dd className="mono">{t.lifecycle_id || '—'}</dd></div>
            <div><dt>Account</dt><dd className="mono">{t.account_id}</dd></div>
            <div><dt>Merchant</dt><dd>{t.merchant_name}</dd></div>
            <div><dt>Transaction date</dt><dd>{fmtDate(t.transaction_date)}</dd></div>
            <div><dt>Amount</dt><dd>{money(t.transaction_amount, cur)}</dd></div>
            <div><dt>Transaction status</dt><dd>{t.status}</dd></div>
            <div><dt>Last settlement</dt><dd>{fmtDate(t.last_settlement_date)}</dd></div>
          </dl>
        </div>

        <div className="card">
          <h2>Settlement totals</h2>
          <p className="card__sub">Net = debits − credits, across {t.settlement_count} settlement{t.settlement_count === 1 ? '' : 's'}.</p>
          <div className="tiles">
            <div className="tile"><p className="tile__label">Debits</p><p className="tile__value">{money(t.total_debits, cur)}</p></div>
            <div className="tile"><p className="tile__label">Credits (refunds)</p><p className="tile__value">{money(t.total_credits, cur)}</p></div>
            <div className="tile"><p className="tile__label">Net settled</p><p className="tile__value">{money(t.total_settled_amount, cur)}</p></div>
            <div className={`tile ${owing.bad ? 'tile--bad' : ''}`}><p className="tile__label">{owing.label}</p><p className="tile__value">{owing.value}</p></div>
          </div>
        </div>
      </div>

      <section className="section card">
        <h2>Issues and recommendations</h2>
        <p className="card__sub">Evaluated as of {fmtDate(asOf)}.</p>
        {t.issues.length === 0 ? (
          <div className="all-clear">
            <strong>No issues.</strong>
            <span>
              {t.settlement_status === 'PENDING' && 'Waiting for settlement, still inside the 7-day window.'}
              {t.settlement_status === 'NOT_APPLICABLE' && 'This transaction did not complete, so no settlement is expected.'}
              {t.settlement_status === 'REFUNDED' && 'The full amount was collected and part of it was refunded on purpose.'}
              {t.settlement_status === 'FULLY_SETTLED' && 'The settled amount matches the transaction amount.'}
            </span>
          </div>
        ) : t.issues.map((issue) => (
          <div key={issue.code} className={`issue issue--${issue.severity}`}>
            <h3>{issue.title} <FlagBadge flag={issue.severity} /></h3>
            <p>{issue.detail}</p>
            <span className="issue__rec"><strong>Recommended: </strong>{issue.recommendation}</span>
          </div>
        ))}
      </section>

      <div className="section detail-grid" style={{ gridTemplateColumns: '1.1fr 0.9fr' }}>
        <div className="card">
          <h2>Settlement history</h2>
          <p className="card__sub">Every settlement matched to this transaction.</p>
          {t.settlements.length === 0 ? (
            <p className="muted">No settlements received yet.</p>
          ) : (
            <div className="table-wrap" style={{ border: 0 }}>
              <table style={{ minWidth: 520 }}>
                <thead>
                  <tr><th>Settlement</th><th>Date</th><th>Type</th><th className="num">Amount</th><th>Processed</th></tr>
                </thead>
                <tbody>
                  {t.settlements.map((s) => (
                    <tr key={s.settlement_id}>
                      <td className="mono">{s.settlement_id}</td>
                      <td>{fmtDate(s.settlement_date)}</td>
                      <td>{s.settlement_type === 'DEBIT' ? 'Debit' : 'Credit'}</td>
                      <td className="num">{s.settlement_type === 'CREDIT' ? '−' : ''}{money(s.settlement_amount, s.currency)}</td>
                      <td className="muted">{fmtDateTime(s.processed_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card">
          <h2>Settlement timeline</h2>
          <p className="card__sub">How the net settled amount built up over time.</p>
          <Timeline events={t.timeline} amount={t.transaction_amount} currency={cur} />
        </div>
      </div>
    </>
  );
}
