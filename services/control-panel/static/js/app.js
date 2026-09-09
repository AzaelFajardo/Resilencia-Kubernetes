// app.js — entry point: registers tabs, starts the router and the header health strip.

import { start, register } from './router.js';
import { API } from './api.js';
import { dot } from './ui.js';
import { createTimer, refreshNow, setRefreshInterval, getIntervalSeconds } from './refresh.js';

import * as home from './tabs/home.js';
import * as orders from './tabs/orders.js';
import * as pruebas from './tabs/pruebas.js';
import * as users from './tabs/users.js';
import * as inventory from './tabs/inventory.js';
import * as payments from './tabs/payments.js';
import * as notifications from './tabs/notifications.js';
import * as resilience from './tabs/resilience.js';
import * as observability from './tabs/observability.js';
import * as kubernetes from './tabs/kubernetes.js';

register('home', home.render);
register('orders', orders.render);
register('pruebas', pruebas.render);
register('users', users.render);
register('inventory', inventory.render);
register('payments', payments.render);
register('notifications', notifications.render);
register('resilience', resilience.render);
register('observability', observability.render);
register('kubernetes', kubernetes.render);

start();
refreshHealthStrip();
const healthTimer = createTimer(refreshHealthStrip);

// ---- Global auto-refresh control (header) ----
const ri = document.getElementById('refreshInterval');
ri.value = getIntervalSeconds();
ri.addEventListener('change', () => {
  setRefreshInterval(ri.value);
  ri.value = getIntervalSeconds();
  refreshNow();
});
document.getElementById('refreshNow').addEventListener('click', refreshNow);

async function refreshHealthStrip() {
  const el = document.getElementById('healthStrip');
  if (!el) return;
  try {
    const data = await API.health();
    el.innerHTML = Object.entries(data).map(([k, v]) =>
      `<span class="chip" data-tip="${k}-service">${dot(v.up)}${k}</span>`
    ).join('');
  } catch (_) {
    el.innerHTML = '<span class="chip" data-tip="El panel no puede alcanzar los servicios">panel desconectado</span>';
  }
}
