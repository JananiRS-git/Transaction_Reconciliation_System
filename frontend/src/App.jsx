import { useCallback, useMemo, useState } from 'react';
import { AppContext, href, useHashRoute } from './hooks.js';
import { DEMO_DATE, todayIso } from './format.js';
import Dashboard from './pages/Dashboard.jsx';
import Transactions from './pages/Transactions.jsx';
import TransactionDetail from './pages/TransactionDetail.jsx';
import Reconcile from './pages/Reconcile.jsx';

const STORAGE_KEY = 'recon.asOf';

function loadAsOf() {
  try {
    return window.localStorage.getItem(STORAGE_KEY) || DEMO_DATE;
  } catch {
    return DEMO_DATE;
  }
}

const NAV = [
  { path: '/', label: 'Dashboard' },
  { path: '/transactions', label: 'Transactions' },
  { path: '/reconcile', label: 'Reconcile' },
];

function isActive(navPath, current) {
  if (navPath === '/') return current === '/';
  return current === navPath || current.startsWith(`${navPath}/`);
}

export default function App() {
  const route = useHashRoute();
  const [asOf, setAsOfState] = useState(loadAsOf);
  const [version, setVersion] = useState(0);

  const setAsOf = useCallback((value) => {
    setAsOfState(value);
    try {
      window.localStorage.setItem(STORAGE_KEY, value);
    } catch {
      /* storage unavailable - ignore */
    }
  }, []);
  const refresh = useCallback(() => setVersion((v) => v + 1), []);
  const ctx = useMemo(() => ({ asOf, setAsOf, version, refresh }), [asOf, setAsOf, version, refresh]);

  let page;
  const detail = route.path.match(/^\/transactions\/([^/]+)$/);
  if (route.path === '/') page = <Dashboard />;
  else if (route.path === '/transactions') page = <Transactions query={route.query} />;
  else if (detail) page = <TransactionDetail id={decodeURIComponent(detail[1])} />;
  else if (route.path === '/reconcile') page = <Reconcile />;
  else
    page = (
      <div className="state">
        <h3 style={{ fontFamily: 'var(--serif)', fontWeight: 400, fontSize: 28, margin: '0 0 6px', color: 'var(--ink)' }}>Page not found</h3>
        <a href={href('/')}>Back to the dashboard</a>
      </div>
    );

  return (
    <AppContext.Provider value={ctx}>
      <header className="nav">
        <div className="nav__inner">
          <a className="brand" href={href('/')}>Reconcile</a>
          <nav className="nav__links" aria-label="Main">
            {NAV.map((n) => (
              <a key={n.path} className="nav__link" href={href(n.path)} aria-current={isActive(n.path, route.path) ? 'page' : undefined}>
                {n.label}
              </a>
            ))}
          </nav>
          <div className="asof">
            <label htmlFor="asof" className="asof__label">Viewing as of</label>
            <input id="asof" type="date" value={asOf} onChange={(e) => e.target.value && setAsOf(e.target.value)} />
            {asOf !== todayIso() && (
              <button className="asof__reset" onClick={() => setAsOf(todayIso())} title="Use today's date">Today</button>
            )}
            {asOf !== DEMO_DATE && (
              <button className="asof__reset" onClick={() => setAsOf(DEMO_DATE)} title="The sample data is from August 2025">Demo date</button>
            )}
          </div>
        </div>
      </header>
      <main className="page">{page}</main>
    </AppContext.Provider>
  );
}
