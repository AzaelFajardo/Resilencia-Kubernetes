// observability.js — Observabilidad: latencia, throughput, recursos, alertas,
// objetivos de Prometheus y Grafana embebido. El refresco es controlable por
// pestaña; el disco (lento, socket Docker) se actualiza aparte.

import { API } from '../api.js';
import { card, table, esc, fmt, badge, dot } from '../ui.js';
import { mountRefreshControl } from '../interval.js';

export function render(view) {
  view.innerHTML = `
    <div class="grid">
      ${card('Latencia por servicio (p50 / p95 / p99)',
        'Percentiles de la duración de cada petición por servicio, sobre el histograma de Prometheus. p50 = mediana (la mitad tarda menos). p95 = el 95% tarda menos que esto. p99 = el 99% tarda menos (cola larga). Cuanto mayor sea la diferencia p50→p99, más variable es la latencia.',
        table(['Servicio', 'p50 (s)', 'p95 (s)', 'p99 (s)'], [])
          .replace('<tbody></tbody>', '<tbody id="o-lat"></tbody>'))}
      ${card('Throughput y errores por servicio',
        'Peticiones por segundo (req/s) de cada servicio y su tasa de error (5xx). Tasa de error = errores/s ÷ req/s. Recuerda: order/payment/notification devuelven HTTP 200 incluso en fallos de negocio, así que solo los 5xx (errores de transporte) cuentan aquí.',
        table(['Servicio', 'req/s', 'errores/s', 'tasa error (%)'], [])
          .replace('<tbody></tbody>', '<tbody id="o-tp"></tbody>'))}
      ${card('Recursos por servicio (CPU / RAM / Disco)',
        'CPU en núcleos (rate de process_cpu_seconds_total), RAM residente en MiB (process_resident_memory_bytes) y escritura de disco acumulada en MiB (leída del socket de Docker, sin contador Prometheus). El disco se actualiza aparte (~30 s) por ser una lectura lenta.',
        table(['Servicio', 'CPU (cores)', 'RAM (MiB)', 'Disco (MiB)'], [])
          .replace('<tbody></tbody>', '<tbody id="o-res"></tbody>'))}
      ${card('Objetivos de Prometheus (scrape)',
        'Los 6 objetivos que Prometheus está raspando (5 microservicios + otel-collector) y su salud. Si un servicio está caído, su objetivo pasa a "down".',
        table(['Job', 'Instancia', 'Salud'], [])
          .replace('<tbody></tbody>', '<tbody id="o-targets"></tbody>'))}
      ${card('Alertas (reglas de Prometheus)',
        'Reglas de alerta cargadas en Prometheus con su estado: inactive (ok), pending (condición cumplida, esperando umbral), firing (activa).',
        '<div id="o-alerts" class="muted">cargando…</div>')}
    </div>
    ${card('Grafana — Resilencia Overview',
      'Dashboard de Grafana con 12 paneles de los 4 sectores de la propuesta: desempeño, resiliencia, recursos y observabilidad. Embebido en modo kiosk.',
      '<iframe class="grafana" id="o-graf" src="about:blank" loading="lazy"></iframe>',
      { full: true })}
  `;

  const $ = (id) => view.querySelector('#' + id);

  let diskCache = {};

  const refreshCleanup = mountRefreshControl(view, { onRefresh: refresh, initial: 5 });
  refresh();
  refreshDisk();
  const diskTimer = setInterval(refreshDisk, 30000);
  initGrafana();

  const cleanup = () => { refreshCleanup(); clearInterval(diskTimer); };
  return cleanup;

  async function refresh() {
    try {
      const d = await API.latency();
      $('o-lat').innerHTML = Object.entries(d).map(([k, v]) =>
        `<tr><td>${esc(k)}-service</td><td>${fmt(v.p50, 3)}</td><td>${fmt(v.p95, 3)}</td><td>${fmt(v.p99, 3)}</td></tr>`
      ).join('') || `<tr><td colspan="4" class="muted">sin datos de latencia</td></tr>`;
    } catch (_) {}

    try {
      const d = await API.throughput();
      $('o-tp').innerHTML = Object.entries(d).map(([k, v]) =>
        `<tr><td>${esc(k)}-service</td><td>${fmt(v.rps, 2)}</td><td>${fmt(v.errors, 2)}</td><td>${v.error_rate != null ? esc(v.error_rate) : '—'}</td></tr>`
      ).join('') || `<tr><td colspan="4" class="muted">sin tráfico reciente</td></tr>`;
    } catch (_) {}

    try {
      const res = await API.resources();
      $('o-res').innerHTML = Object.entries(res).map(([inst, v]) => {
        const svc = inst.split('-')[0];
        return `<tr><td>${esc(inst)}</td><td>${fmt(v.cpu_cores, 3)}</td><td>${fmt(v.mem_mib, 1)}</td><td class="o-disk" data-svc="${esc(svc)}">${diskCache[svc] ?? '—'}</td></tr>`;
      }).join('') || `<tr><td colspan="4" class="muted">sin datos (Prometheus vacío)</td></tr>`;
    } catch (_) {}

    try {
      const d = await API.targets();
      const list = d.targets || [];
      $('o-targets').innerHTML = list.map((tg) =>
        `<tr><td>${esc(tg.job)}</td><td>${esc(tg.instance)}</td><td>${dot(tg.health === 'up')}${esc(tg.health)}</td></tr>`
      ).join('') || `<tr><td colspan="3" class="muted">sin objetivos</td></tr>`;
    } catch (_) { $('o-targets').innerHTML = `<tr><td colspan="3" class="muted">no disponible</td></tr>`; }

    try {
      const a = await API.alerts();
      const rules = a.groups || [];
      $('o-alerts').innerHTML = rules.length
        ? rules.map((r) => {
            const color = r.state === 'firing' ? 'var(--red)' : r.state === 'pending' ? 'var(--yellow)' : 'var(--muted)';
            const ann = r.annotations || {};
            const desc = ann.summary || ann.description || '';
            return `<div class="row" style="justify-content:flex-start;gap:10px"><span class="dot" style="background:${color}"></span><b>${esc(r.name)}</b> ${badge(r.state, r.state === 'firing' ? 'bad' : r.state === 'pending' ? 'warn' : 'ok')}<span class="muted">${esc(desc)}</span></div>`;
          }).join('')
        : '<span class="muted">sin reglas de alerta cargadas</span>';
    } catch (_) { $('o-alerts').textContent = 'no disponible'; }
  }

  async function refreshDisk() {
    try {
      diskCache = await API.disk();
    } catch (_) {
      diskCache = {};
    }
    view.querySelectorAll('.o-disk').forEach((td) => {
      td.textContent = diskCache[td.dataset.svc] ?? '—';
    });
  }

  async function initGrafana() {
    try {
      const cfg = await API.config();
      $('o-graf').src = cfg.grafana_url + '/d/resilencia-overview/resilencia-overview?orgId=1&kiosk&refresh=10s&theme=dark';
    } catch (_) {}
  }
}
