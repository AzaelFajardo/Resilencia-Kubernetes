// observability.js — Observabilidad: latencia, recursos, alertas y Grafana.

import { API } from '../api.js';
import { card, table, esc, fmt, badge } from '../ui.js';

export function render(view) {
  view.innerHTML = `
    <div class="grid">
      ${card('Latencia por servicio (p50 / p95 / p99)',
        'Percentiles de la duración de cada petición por servicio, calculados sobre el histograma de Prometheus. p50 = mediana (la mitad tarda menos). p95 = el 95% tarda menos que esto. p99 = el 99% tarda menos (cola larga). A mayor diferencia entre p50 y p99, más variable es la latencia.',
        table(['Servicio', 'p50 (s)', 'p95 (s)', 'p99 (s)'], [])
          .replace('<tbody></tbody>', '<tbody id="o-lat"></tbody>'))}
      ${card('Recursos por servicio (CPU / RAM / Disco)',
        'CPU en núcleos (rate de process_cpu_seconds_total), RAM residente en MiB (process_resident_memory_bytes) y escritura de disco acumulada en MiB (leída del socket de Docker, sin contador Prometheus).',
        table(['Servicio', 'CPU (cores)', 'RAM (MiB)', 'Disco (MiB)'], [])
          .replace('<tbody></tbody>', '<tbody id="o-res"></tbody>'))}
      ${card('Alertas (reglas de Prometheus)',
        'Reglas de alerta cargadas en Prometheus con su estado: inactive (ok), pending (condición cumplida, esperando umbral), firing (activa).',
        '<div id="o-alerts" class="muted">cargando…</div>')}
    </div>
    ${card('Grafana — Resilencia Overview',
      'Dashboard de Grafana con 12 paneles de los 4 sectores de la propuesta: desempeño, resiliencia, recursos y observabilidad. Embebido en modo kiosk.',
      '<iframe class="grafana" id="o-graf" src="about:blank" loading="lazy"></iframe>',
      { full: true })}
  `;

  const t = setInterval(refresh, 5000);
  refresh();
  initGrafana();

  const cleanup = () => clearInterval(t);
  return cleanup;

  async function refresh() {
    try {
      const d = await API.latency();
      view.querySelector('#o-lat').innerHTML = Object.entries(d).map(([k, v]) =>
        `<tr><td>${esc(k)}-service</td><td>${fmt(v.p50, 3)}</td><td>${fmt(v.p95, 3)}</td><td>${fmt(v.p99, 3)}</td></tr>`
      ).join('') || `<tr><td colspan="4" class="muted">sin datos de latencia</td></tr>`;
    } catch (_) {}

    try {
      const [res, disk] = await Promise.all([API.resources(), API.disk().catch(() => ({}))]);
      view.querySelector('#o-res').innerHTML = Object.entries(res).map(([inst, v]) => {
        const svc = inst.split('-')[0];
        return `<tr><td>${esc(inst)}</td><td>${fmt(v.cpu_cores, 3)}</td><td>${fmt(v.mem_mib, 1)}</td><td>${disk[svc] ?? '—'}</td></tr>`;
      }).join('') || `<tr><td colspan="4" class="muted">sin datos (Prometheus vacío)</td></tr>`;
    } catch (_) {}

    try {
      const a = await API.alerts();
      const rules = a.groups || [];
      view.querySelector('#o-alerts').innerHTML = rules.length
        ? rules.map((r) => {
            const color = r.state === 'firing' ? 'var(--red)' : r.state === 'pending' ? 'var(--yellow)' : 'var(--muted)';
            const ann = r.annotations || {};
            const desc = ann.summary || ann.description || '';
            return `<div class="row" style="justify-content:flex-start;gap:10px"><span class="dot" style="background:${color}"></span><b>${esc(r.name)}</b> ${badge(r.state, r.state === 'firing' ? 'bad' : r.state === 'pending' ? 'warn' : 'ok')}<span class="muted">${esc(desc)}</span></div>`;
          }).join('')
        : '<span class="muted">sin reglas de alerta cargadas</span>';
    } catch (_) { view.querySelector('#o-alerts').textContent = 'no disponible'; }
  }

  async function initGrafana() {
    try {
      const cfg = await API.config();
      view.querySelector('#o-graf').src = cfg.grafana_url + '/d/resilencia-overview/resilencia-overview?orgId=1&kiosk&refresh=10s&theme=dark';
    } catch (_) {}
  }
}
