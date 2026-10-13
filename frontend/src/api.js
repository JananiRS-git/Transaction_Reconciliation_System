// Thin wrapper around the REST API. Every call returns parsed JSON or throws an Error with a readable message.

const BASE = '/api';

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${BASE}${path}`, options);
  } catch {
    throw new Error("Can't reach the server. Make sure the backend is running (python run.py in /backend).");
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    /* non-JSON response */
  }
  if (!response.ok) {
    throw new Error(body?.error?.message || `Request failed (${response.status})`);
  }
  return body;
}

const withAsOf = (asOf, extra = '') => {
  const parts = [];
  if (asOf) parts.push(`as_of=${encodeURIComponent(asOf)}`);
  if (extra) parts.push(extra);
  return parts.length ? `?${parts.join('&')}` : '';
};

export const getSummary = (asOf) => request(`/dashboard/summary${withAsOf(asOf)}`);
export const getTransactions = (asOf) => request(`/transactions${withAsOf(asOf)}`);
export const getTransaction = (id, asOf) => request(`/transactions/${encodeURIComponent(id)}${withAsOf(asOf)}`);

export function reconcile({ file, useSample }, asOf) {
  if (file) {
    const form = new FormData();
    form.append('file', file);
    return request(`/reconcile${withAsOf(asOf)}`, { method: 'POST', body: form });
  }
  return request(`/reconcile${withAsOf(asOf, useSample ? 'use_sample=true' : '')}`, { method: 'POST' });
}

export const resetData = () => request('/reset', { method: 'POST' });
