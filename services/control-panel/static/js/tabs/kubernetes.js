// kubernetes.js — Kubernetes: pods y HPA (solo lectura, opt-in).

import { API } from '../api.js';
import { card, table, esc, dot } from '../ui.js';
import { createTimer } from '../refresh.js';

export function render(view) {
  view.innerHTML = `
    <div class="grid">
      ${card('Pods',
        'Pods del namespace default del cluster. Fase = Running/Pending/etc. Ready = si el contenedor pasó su readiness probe. Restarts = veces que se reinició el contenedor.',
        table(['Pod', 'Fase', 'Ready', 'Restarts'], [])
          .replace('<tbody></tbody>', '<tbody id="k-pods"></tbody>'))}
      ${card('Horizontal Pod Autoscalers',
        'HPAs del cluster. Réplicas actuales (min–max) y uso de CPU actual frente al objetivo. El HPA añade réplicas cuando el uso supera el objetivo (70%).',
        table(['HPA', 'Réplicas', 'CPU actual/objetivo'], [])
          .replace('<tbody></tbody>', '<tbody id="k-hpa"></tbody>'))}
    </div>
    <div class="row">
      <button class="btn secondary" id="k-refresh">Actualizar</button>
      <span class="msg" id="k-status" style="flex:1"></span>
    </div>
  `;

  const $ = (id) => view.querySelector('#' + id);
  const t = createTimer(refresh);
  refresh();
  $('k-refresh').addEventListener('click', refresh);

  const cleanup = () => t();
  return cleanup;

  async function refresh() {
    const status = $('k-status');
    try {
      const data = await API.kubernetes();
      status.className = 'msg'; status.textContent = '';
      $('k-pods').innerHTML = data.pods.map((p) =>
        `<tr><td>${esc(p.name)}</td><td>${esc(p.phase)}</td><td>${dot(p.ready)}${p.ready}</td><td>${p.restarts}</td></tr>`
      ).join('') || `<tr><td colspan="4" class="muted">sin pods</td></tr>`;
      $('k-hpa').innerHTML = data.hpas.map((h) =>
        `<tr><td>${esc(h.name)}</td><td>${h.currentReplicas ?? '—'}/${h.minReplicas ?? '?'}-${h.maxReplicas ?? '?'}</td><td>${h.currentCPU ?? '—'}% / ${h.targetCPU ?? '—'}%</td></tr>`
      ).join('') || `<tr><td colspan="3" class="muted">sin HPAs</td></tr>`;
    } catch (e) {
      status.className = 'msg err';
      status.textContent = 'Kubernetes no disponible: ' + e.message +
        ' — es opcional: configura K8S_API_SERVER y monta los certificados en k8s/certs/ (ver .env.example).';
    }
  }
}
