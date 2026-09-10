// api.js — thin fetch wrapper + typed endpoint helpers for the control-panel API.

const JSON_HEADERS = { 'Content-Type': 'application/json' };

async function api(path, opts = {}) {
  // Every request gets a hard timeout so a hung fetch (e.g. a slow Prometheus
  // query or a stopped container that stalls) can never hold the UI forever.
  // Long-running endpoints override this with their own `timeout` option.
  const timeout = opts.timeout ?? 20000;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const r = await fetch(path, { ...opts, signal: controller.signal });
    let body = null;
    try { body = await r.json(); } catch (_) { body = {}; }
    if (!r.ok) throw new Error((body && body.detail) || `${r.status} ${r.statusText}`);
    return body;
  } finally {
    clearTimeout(timer);
  }
}

function post(path, data, timeout) {
  const opts = { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(data ?? {}) };
  if (timeout) opts.timeout = timeout;
  return api(path, opts);
}

function patch(path, data) {
  return api(path, { method: 'PATCH', headers: JSON_HEADERS, body: JSON.stringify(data ?? {}) });
}

function del(path) {
  return api(path, { method: 'DELETE' });
}

export const API = {
  health: () => api('/api/health'),
  counts: () => api('/api/counts'),
  resources: () => api('/api/resources'),
  disk: () => api('/api/disk', { timeout: 45000 }),
  latency: () => api('/api/latency'),
  throughput: () => api('/api/throughput'),
  targets: () => api('/api/targets'),
  alerts: () => api('/api/alerts'),
  circuitBreaker: () => api('/api/circuit-breaker'),
  config: () => api('/api/config'),
  kubernetes: () => api('/api/kubernetes'),

  chaosSet: (service, cfg) => post('/api/chaos', { service, ...cfg }),
  getChaos: (service) => api(`/api/chaos/${service}`),
  serviceAction: (service, action) => post(`/api/services/${service}/${action}`),
  chaosSetAll: async (cfg) => {
    const svcs = ['order', 'user', 'inventory', 'payment', 'notification'];
    const out = [];
    for (const s of svcs) {
      try { out.push({ service: s, ...(await post('/api/chaos', { service: s, ...cfg })) }); }
      catch (e) { out.push({ service: s, error: e.message }); }
    }
    return out;
  },
  chaosResetAll: async () => {
    const svcs = ['order', 'user', 'inventory', 'payment', 'notification'];
    const out = [];
    for (const s of svcs) {
      try { out.push(await post('/api/chaos', { service: s, FAILURE_RATE: 0.0, LATENCY_MS: 0, TIMEOUT_RATE: 0.0 })); }
      catch (e) { out.push({ error: e.message }); }
    }
    return out;
  },

  placeOrder: (user_id, product_id, quantity) => post('/api/orders', { user_id, product_id, quantity }),
  userOrders: (id, limit = 20) => api(`/api/users/${id}/orders?limit=${limit}`),
  generate: (what) => post(`/api/generate/${what}`),
  recent: (entity, limit = 10) => api(`/api/recent/${entity}?limit=${limit}`),

  listEntities: (entity, offset = 0, limit = 20, search = '') => {
    const qs = `offset=${offset}&limit=${limit}${search ? '&search=' + encodeURIComponent(search) : ''}`;
    return api(`/api/entities/${entity}?${qs}`);
  },
  createEntity: (entity, body) => post(`/api/entities/${entity}`, body),
  updateEntity: (entity, id, body) => patch(`/api/entities/${entity}/${id}`, body),
  deleteEntity: (entity, id) => del(`/api/entities/${entity}/${id}`),
  clearEntity: (entity) => del(`/api/entities/${entity}`),

  faker: (what, count = 100) => post(`/api/faker/${what}?count=${count}`, null, 180000),
  generateOrders: (cfg) => post('/api/orders/generate', cfg, 600000),
  simulateStatus: () => api('/api/orders/simulate/status'),
  simulateStart: (cfg) => post('/api/orders/simulate/start', cfg),
  simulateStop: () => post('/api/orders/simulate/stop'),
  getRetries: () => api('/api/resilience/retries'),
  setRetries: (cfg) => post('/api/resilience/retries', cfg),
  getMode: () => api('/api/resilience/mode'),
  setMode: (mode) => post('/api/resilience/mode', { mode }),
  getRuntimeMode: () => api('/api/runtime-mode'),
  setRuntimeMode: (mode) => post('/api/runtime-mode', { mode }),
};

export { api, post, patch, del };
