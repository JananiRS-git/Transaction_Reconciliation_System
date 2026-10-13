import { useRef, useState } from 'react';
import { reconcile, resetData } from '../api.js';
import { fmtDate } from '../format.js';
import { href, useApp } from '../hooks.js';

const OUTCOME_LABEL = {
  matched_lifecycle: ['matched', 'Matched · lifecycle ID'],
  matched_fallback: ['matched', 'Matched · fallback'],
  unmatched: ['unmatched', 'Unmatched'],
  duplicate: ['duplicate', 'Already processed'],
  conflict: ['conflict', 'Conflict'],
  invalid: ['invalid', 'Invalid row'],
};

export default function Reconcile() {
  const { asOf, refresh } = useApp();
  const inputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [result, setResult] = useState(null);

  const pick = (f) => {
    setError('');
    setNotice('');
    if (f && !/\.csv$/i.test(f.name) && f.type !== 'text/csv') {
      setError('Please choose a .csv file.');
      return;
    }
    setFile(f || null);
  };

  const run = async (useSample) => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const data = await reconcile({ file: useSample ? null : file, useSample }, asOf);
      setResult(data);
      refresh();
      if (!useSample) setFile(null);
    } catch (e) {
      setResult(null);
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    if (!window.confirm('Reset all settlements and restore the original sample transactions?')) return;
    setBusy(true);
    setError('');
    try {
      await resetData();
      setResult(null);
      setNotice('Database reset. All transactions are back to the original sample data.');
      refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const s = result?.summary;

  return (
    <>
      <div className="page-head">
        <h1>Reconcile settlements</h1>
        <p>Upload a settlement CSV. Each row is matched to a transaction, stored, and the transaction status is updated. Uploading the same file twice is safe.</p>
      </div>

      <div className="card">
        <label
          className={`dropzone ${dragging ? 'is-over' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files?.[0]); }}
        >
          <strong>Drop a CSV file here, or click to browse</strong>
          <span>Maximum 5 MB</span>
          <input ref={inputRef} type="file" accept=".csv,text/csv" className="sr-only"
                 onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ''; }} />
        </label>

        {file && (
          <div className="file-chip">
            <span>{file.name}</span>
            <button onClick={() => setFile(null)} aria-label="Remove file">×</button>
          </div>
        )}

        <div className="actions">
          <button className="btn btn--primary" disabled={!file || busy} onClick={() => run(false)}>
            {busy ? 'Working…' : 'Reconcile this file'}
          </button>
          <button className="btn btn--secondary" disabled={busy} onClick={() => run(true)}>Use the sample report</button>
        </div>
        <p className="cols">
          Required columns: settlement_id, lifecycle_id, account_id, merchant_name, transaction_date, settlement_date,
          settlement_amount, settlement_type (DEBIT or CREDIT), currency. lifecycle_id may be empty.
        </p>

        {error && <div className="alert alert--error" role="alert">{error}</div>}
        {notice && <div className="alert alert--ok" role="status">{notice}</div>}
      </div>

      {result && (
        <section className="section card" aria-live="polite">
          <h2>Result for {result.source}</h2>
          <p className="card__sub">Issue flags below use the “viewing as of” date {fmtDate(result.as_of)}.</p>

          <div className="result-tiles">
            <div className="tile"><p className="tile__label">Rows read</p><p className="tile__value">{s.rows_total}</p></div>
            <div className="tile"><p className="tile__label">Matched</p><p className="tile__value">{s.matched}</p>
              <p className="tile__label">{s.matched_by_lifecycle_id} by ID · {s.matched_by_fallback} fallback</p></div>
            <div className={`tile ${s.unmatched ? 'tile--bad' : ''}`}><p className="tile__label">Unmatched</p><p className="tile__value">{s.unmatched}</p></div>
            <div className="tile"><p className="tile__label">Already processed</p><p className="tile__value">{s.duplicates + s.conflicts}</p></div>
            <div className={`tile ${s.invalid ? 'tile--bad' : ''}`}><p className="tile__label">Invalid</p><p className="tile__value">{s.invalid}</p></div>
            <div className="tile"><p className="tile__label">Transactions updated</p><p className="tile__value">{s.transactions_updated}</p></div>
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Line</th><th>Settlement</th><th>Outcome</th><th>Transaction</th><th>Details</th></tr>
              </thead>
              <tbody>
                {result.results.map((r) => {
                  const [tone, label] = OUTCOME_LABEL[r.outcome] || ['duplicate', r.outcome];
                  return (
                    <tr key={`${r.line}-${r.settlement_id}`}>
                      <td className="muted">{r.line}</td>
                      <td className="mono">{r.settlement_id || '—'}</td>
                      <td><span className={`badge badge--${tone}`}>{label}</span></td>
                      <td>{r.transaction_id ? <a className="mono" href={href(`/transactions/${r.transaction_id}`)}>{r.transaction_id}</a> : '—'}</td>
                      <td className="wrap" style={{ maxWidth: 420 }}>
                        {r.message}
                        {r.warnings.length > 0 && <ul className="warn-list">{r.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="actions">
            <a className="btn btn--primary" href={href('/')}>See the dashboard</a>
            <a className="btn btn--secondary" href={href('/transactions')}>View transactions</a>
          </div>
        </section>
      )}

      <section className="section card">
        <h2>Demo tools</h2>
        <p className="card__sub">Start over with the original 14 sample transactions and no settlements.</p>
        <button className="btn btn--danger btn--small" onClick={reset} disabled={busy}>Reset demo data</button>
      </section>
    </>
  );
}
