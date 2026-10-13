import { getSummary, getTransactions } from '../api.js';
import { DailyBars, HBars, ProgressBar, StatusDonut } from '../components/charts.jsx';
import { ErrorState, FlagBadge, Kpi, Loading } from '../components/common.jsx';
import { fmtDate, fmtDateTime, money, percent } from '../format.js';
import { go, href, useApp, useAsync } from '../hooks.js';

export default function Dashboard() {
  const { asOf, version } = useApp();
  const summary = useAsync(() => getSummary(asOf), [asOf, version]);
  const txns = useAsync(() => getTransactions(asOf), [asOf, version]);

  const hero = (
    <section className="hero">
      <h1 className="hero__title">
        Match every settlement. <br />
        Catch every <span className="accent">discrepancy.</span>
      </h1>
      <p className="hero__text">
        Upload a settlement report, match it to your transactions, and see at a glance what is pending, partial, over-settled or missing.
      </p>
      <div className="hero__actions">
        <a className="btn btn--primary" href={href('/reconcile')}>Run reconciliation →</a>
        <a className="btn btn--secondary" href={href('/transactions')}>View transactions</a>
      </div>
    </section>
  );

  if (summary.loading && !summary.data) return <>{hero}<Loading label="Loading summary…" /></>;
  if (summary.error) return <>{hero}<ErrorState error={summary.error} onRetry={summary.reload} /></>;

  const s = summary.data;
  const cur = s.amounts.currency;
  const attention = (txns.data?.transactions || [])
    .filter((t) => t.issue_flag !== 'none')
    .sort((a, b) => (a.issue_flag === b.issue_flag ? 0 : a.issue_flag === 'critical' ? -1 : 1));

  return (
    <>
      {hero}

      {!s.last_run && (
        <div className="banner">
          <p><strong>No settlement report has been reconciled yet.</strong> Run the sample report to see matching and issue detection in action.</p>
          <a className="btn btn--primary btn--small" href={href('/reconcile')}>Go to Reconcile</a>
        </div>
      )}

      <section aria-label="Reconciliation summary" className="grid grid--kpi">
        <Kpi label="Transactions processed" value={s.totals.transactions} note={`${s.totals.completed_transactions} completed`} />
        <Kpi label="Settlements processed" value={s.totals.settlements_processed}
             note={`${s.totals.settlements_matched} matched · ${s.totals.settlements_unmatched} unmatched`} />
        <Kpi tone="critical" label="Critical issues" value={s.issues.critical} note="Needs action" />
        <Kpi tone="warning" label="Warnings" value={s.issues.warning} note="Worth a look" />
        <Kpi label="Outstanding amount" value={money(s.amounts.outstanding_amount, cur)} note="Pending + partial, not yet settled" />
        <Kpi label="Over-settled amount" value={money(s.amounts.over_settled_amount, cur)} note="Settled above the transaction amount" />
      </section>

      <section className="section grid grid--2">
        <div className="card">
          <h2>Settlement status</h2>
          <p className="card__sub">Select a status to see its transactions.</p>
          <StatusDonut counts={s.status_breakdown} onSelect={(st) => go('/transactions', { status: st })} />
        </div>

        <div className="card">
          <h2>Performance</h2>
          <p className="card__sub">Based on completed transactions.</p>
          <div className="perf">
            <div>
              <span className="muted">Average days to settle</span>
              <p className="perf__value">{s.performance.avg_days_to_settle ?? '—'}</p>
            </div>
            <div>
              <span className="muted">Settlement rate</span>
              <p className="perf__value">{percent(s.performance.settlement_rate)}</p>
            </div>
          </div>
          <ProgressBar value={s.performance.settlement_rate} />
          <p className="card__sub" style={{ marginTop: 8 }}>
            {s.performance.settled_transactions} of {s.totals.completed_transactions} completed transactions have a settlement.
          </p>
          <div style={{ marginTop: 22 }}>
            <HBars items={[
              { label: 'Critical', value: s.issues.critical, color: 'var(--critical)' },
              { label: 'Warning', value: s.issues.warning, color: '#e5a50a' },
              { label: 'No issues', value: s.issues.none, color: '#1dbf8a' },
            ]} />
          </div>
        </div>
      </section>

      <section className="section grid grid--2">
        <div className="card">
          <h2>Needs attention</h2>
          <p className="card__sub">As of {fmtDate(s.as_of)}. Critical issues first.</p>
          {txns.loading && !txns.data ? <Loading /> : attention.length === 0 ? (
            <p className="muted">Nothing needs attention right now.</p>
          ) : (
            <ul className="attention">
              {attention.slice(0, 6).map((t) => (
                <li key={t.transaction_id}>
                  <a href={href(`/transactions/${t.transaction_id}`)}>
                    <span className={`dot dot--${t.issue_flag}`} aria-hidden="true" />
                    <span>
                      <span className="attention__title">{t.merchant_name} <span className="muted mono">{t.transaction_id}</span></span>
                      <br />
                      <span className="attention__sub">{t.issues[0]?.title}</span>
                    </span>
                    <FlagBadge flag={t.issue_flag} />
                  </a>
                </li>
              ))}
            </ul>
          )}
          {attention.length > 6 && (
            <p style={{ margin: '14px 0 0' }}>
              <a href={href('/transactions', { issue: 'critical' })}>See all {attention.length} flagged transactions</a>
            </p>
          )}
        </div>

        <div className="card">
          <h2>Settlement activity</h2>
          <p className="card__sub">Money moved by settlement date.</p>
          {s.daily_settlements.length ? <DailyBars data={s.daily_settlements} currency={cur} /> : (
            <p className="muted">No settlements yet.</p>
          )}
          <div className="grid grid--2" style={{ marginTop: 18, gap: 12 }}>
            <div>
              <span className="muted">Total transaction amount</span>
              <p style={{ margin: 0, fontWeight: 600 }}>{money(s.amounts.total_transaction_amount, cur)}</p>
            </div>
            <div>
              <span className="muted">Net settled (all)</span>
              <p style={{ margin: 0, fontWeight: 600 }}>{money(s.amounts.total_net_settled, cur)}</p>
            </div>
          </div>
        </div>
      </section>

      {s.unmatched_settlements.length > 0 && (
        <section className="section">
          <div className="card">
            <h2>Unmatched settlements</h2>
            <p className="card__sub">These rows could not be tied to exactly one transaction, so they are not counted against any transaction.</p>
            <div className="table-wrap" style={{ border: 0 }}>
              <table>
                <thead>
                  <tr><th>Settlement</th><th>Merchant</th><th>Account</th><th>Date</th><th className="num">Amount</th><th>Why</th></tr>
                </thead>
                <tbody>
                  {s.unmatched_settlements.map((u) => (
                    <tr key={u.settlement_id}>
                      <td className="mono">{u.settlement_id}</td>
                      <td>{u.merchant_name || '—'}</td>
                      <td className="mono">{u.account_id || '—'}</td>
                      <td>{fmtDate(u.settlement_date)}</td>
                      <td className="num">{u.settlement_type === 'CREDIT' ? '−' : ''}{money(u.settlement_amount, u.currency)}</td>
                      <td className="wrap" style={{ maxWidth: 340 }}>{u.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      )}

      {s.last_run && (
        <p className="muted" style={{ marginTop: 20, fontSize: 13 }}>
          Last reconciliation: {fmtDateTime(s.last_run.run_at)} UTC · {s.last_run.source_name} · {s.last_run.rows_total} rows
        </p>
      )}
    </>
  );
}
