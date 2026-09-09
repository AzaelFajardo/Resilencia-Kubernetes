// resilience.js — Resiliencia y caos: circuit breaker + inyección de fallos.

import { API } from '../api.js';
import { card, badge, toast } from '../ui.js';

export function render(view) {
  view.innerHTML = `
    <div class="grid">
      ${card('Circuit breaker (order → payment)',
        'El breaker protege a payment-service: si falla 3 veces seguidas pasa a OPEN y order-service deja de llamarlo (fallo rápido). Tras 15s entra en HALF_OPEN y deja pasar una única petición de prueba; si tiene éxito vuelve a CLOSED, si falla vuelve a OPEN.',
        '<div id="r-cb" class="muted">cargando…</div>')}
      ${card('Inyección de fallos (chaos)',
        'Cambia el comportamiento de un servicio en caliente para probar resiliencia. · FAILURE_RATE: probabilidad (0.0–1.0) de que el servicio falle en cada petición. · LATENCY_MS: retardo artificial añadido en milisegundos. · TIMEOUT_RATE: probabilidad de simular un timeout (espera 30s).',
        `
        <form id="c-form" class="row">
          <select id="c-svc">
            <option value="order">order-service</option>
            <option value="user">user-service</option>
            <option value="inventory">inventory-service</option>
            <option value="payment">payment-service</option>
            <option value="notification">notification-service</option>
          </select>
          <label>FAILURE_RATE <input id="c-fr" type="number" step="0.1" min="0" max="1" placeholder="0.0"></label>
          <label>LATENCY_MS <input id="c-lm" type="number" step="100" min="0" placeholder="0"></label>
          <label>TIMEOUT_RATE <input id="c-tr" type="number" step="0.1" min="0" max="1" placeholder="0.0"></label>
          <button class="btn">Aplicar</button>
          <button class="btn secondary" id="c-reset" type="button">Reset todo</button>
        </form>
        <div class="msg" id="c-msg"></div>
      `)}
    </div>
  `;

  const t = setInterval(refreshCB, 3000);
  refreshCB();
  const cleanup = () => clearInterval(t);

  view.querySelector('#c-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const cfg = {};
    if (view.querySelector('#c-fr').value !== '') cfg.FAILURE_RATE = parseFloat(view.querySelector('#c-fr').value);
    if (view.querySelector('#c-lm').value !== '') cfg.LATENCY_MS = parseInt(view.querySelector('#c-lm').value);
    if (view.querySelector('#c-tr').value !== '') cfg.TIMEOUT_RATE = parseFloat(view.querySelector('#c-tr').value);
    const svc = view.querySelector('#c-svc').value;
    const msg = view.querySelector('#c-msg');
    try {
      const r = await API.chaosSet(svc, cfg);
      msg.className = 'msg ok'; msg.textContent = `${svc}: ${JSON.stringify(r.config)}`;
      toast('Chaos aplicado a ' + svc, 'ok');
    } catch (err) { msg.className = 'msg err'; msg.textContent = err.message; }
  });

  view.querySelector('#c-reset').addEventListener('click', async () => {
    const msg = view.querySelector('#c-msg');
    try { await API.chaosResetAll(); msg.className = 'msg ok'; msg.textContent = 'Chaos reseteado en los 5 servicios.'; toast('Chaos reseteado', 'ok'); }
    catch (err) { msg.className = 'msg err'; msg.textContent = err.message; }
  });

  return cleanup;

  async function refreshCB() {
    try {
      const cb = await API.circuitBreaker();
      view.querySelector('#r-cb').innerHTML =
        `<div style="margin-bottom:8px">${badge(cb.state, cb.state)}</div>` +
        `<div class="muted">fallos: ${cb.failures}/${cb.failure_threshold} · umbral: ${cb.failure_threshold} · recuperación: ${cb.recovery_timeout}s</div>`;
    } catch (_) {
      view.querySelector('#r-cb').textContent = 'no disponible';
    }
  }
}
