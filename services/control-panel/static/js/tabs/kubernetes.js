// kubernetes.js — Kubernetes: pods, HPA, namespace, borrar pod y autoescalado en vivo.

import { API } from '../api.js';
import { card, table, esc, dot, toast } from '../ui.js';
import { mountRefreshControl } from '../interval.js';

// handful of colors for the replica-history chart lines
const CHART_COLORS = ['#4f8ef7', '#f7a84f', '#57c26b', '#d55e6d', '#9b6bf7', '#41c4c4'];

export function render(view) {
  view.innerHTML = `
    <div class="stack">
      <div class="row" style="align-items:center;gap:12px">
        <label class="muted" style="white-space:nowrap">namespace</label>
        <select id="k-ns" style="max-width:220px">
          <option value="default">default</option>
        </select>
        <button class="btn sm secondary" id="k-delete-pod" title="Borra un pod seleccionado para probar liveness/self-healing">🗑 borrar pod</button>
        <span class="muted" id="k-ns-hint"></span>
      </div>
      <div class="grid">
        ${card('Pods',
        'Pods del namespace seleccionado. Borra un pod (botón 🗑) para probar que el Deployment lo recrea al instante (liveness/self-healing).',
        table(['Pod', 'Fase', 'Ready', 'Restarts', 'Borrar?'], [])
          .replace('<tbody></tbody>', '<tbody id="k-pods"></tbody>'))}
        ${card('Horizontal Pod Autoscalers',
        'HPAs del cluster. Réplicas actuales (min–max) y uso de CPU actual frente al objetivo (70%). Envíale una ráfaga de órdenes y observa cómo el HPA escala 1 → n réplicas; al bajar la carga, vuelve a 1.',
        table(['HPA', 'Target', 'Réplicas', 'CPU actual/objetivo'], [])
          .replace('<tbody></tbody>', '<tbody id="k-hpa"></tbody>'))}
      </div>
      ${card('Autoescalado en vivo (réplicas por deployment)',
        'Serie temporal de réplicas samples por cada GET /api/kubernetes. Lanza una ráfaga con "Inyectar carga" (satura CPU de order/payment) y observa cómo el HPA escala 1 → n réplicas; al parar, vuelven a bajar.',
        `<div class="row" style="align-items:center;gap:10px;margin-bottom:10px">
          <button class="btn sm secondary" id="k-burst">⚡ Inyectar carga (HPA)</button>
          <button class="btn sm secondary" id="k-burst-stop">■ Detener carga</button>
          <span class="muted" id="k-burst-status"></span>
        </div>
        <div class="chart-wrap" style="height:220px" id="k-chart"><div class="empty">esperando muestras…</div></div>
        <div class="row" style="margin-top:8px">
          <button class="btn sm secondary" id="k-chart-range-1h" data-min="1">1h</button>
          <button class="btn sm secondary" id="k-chart-range-4h" data-min="4">4h</button>
          <button class="btn sm secondary" id="k-chart-range-1d" data-min="24">24h</button>
        </div>`, { full: true })}
    </div>
  `;

  const $ = (id) => view.querySelector('#' + id);
  let ns = 'default';
  let rangeMinutes = 1;
  let historyCache = {};      // deployment -> {start, series[]} (series grows in place)

  const refreshCleanup = mountRefreshControl(view, { onRefresh: refresh, initial: 10 });
  refresh();

  // ---- namespace loader ----
  API.kubernetesNamespaces().then((names) => {
    const sel = $('k-ns');
    sel.replaceChildren(...names.map((n) => {
      const o = document.createElement('option');
      o.value = n; o.textContent = n; return o;
    }));
    sel.value = ns;
  }).catch(() => {});
  $('k-ns').addEventListener('change', () => { ns = $('k-ns').value; refresh(); });

  // ---- delete pod (by selected row + confirm) ----
  view.addEventListener('click', async (e) => {
    const btn = e.target.closest('.k-del');
    if (!btn) return;
    const podName = btn.dataset.pod;
    const confirmed = await import('../ui.js').then(({ confirmDialog }) => confirmDialog(
      `¿Borrar el pod "${podName}"?\nEl Deployment lo recreará automáticamente (prueba de liveness/self-healing).`
    ));
    if (!confirmed) return;
    try {
      await API.kubernetesDeletePod(podName, ns);
      toast(`Pod ${podName} borrado — el cluster lo está recreando`, 'ok');
      refresh();
    } catch (err) {
      toast('Error borrando pod: ' + err.message, 'err');
    }
  });

  $('k-chart-range-1h').addEventListener('click', () => setRange(1));
  $('k-chart-range-4h').addEventListener('click', () => setRange(4));
  $('k-chart-range-1d').addEventListener('click', () => setRange(24));

  // ---- Inyectar / detener carga para probar autoescalado (HPA 1→n) ----
  $('k-burst').addEventListener('click', async () => {
    const btn = $('k-burst');
    btn.disabled = true;
    try {
      const st = await API.simulateStart({ rate: 40, clients: 10 });
      $('k-burst-status').textContent = 'ráfaga activa: ' + (st && st.sent !== undefined ? `sent=${st.sent}` : 'enviando…');
      toast('Carga inyectada — observa el autoescalado en el gráfico', 'ok');
    } catch (e) {
      $('k-burst-status').textContent = 'error: ' + e.message;
    } finally {
      btn.disabled = false;
    }
  });
  $('k-burst-stop').addEventListener('click', async () => {
    try {
      const st = await API.simulateStop();
      $('k-burst-status').textContent = 'carga detenida' + (st && st.sent !== undefined ? ` (sent=${st.sent})` : '');
      toast('Simulación de carga detenida', 'ok');
    } catch (e) {
      $('k-burst-status').textContent = 'error: ' + e.message;
    }
  });

  function setRange(min) {
    rangeMinutes = min;
    [...view.querySelectorAll('[id^="k-chart-range-"]')].forEach((b) =>
      b.classList.toggle('active', +b.dataset.min === min));
    drawChart();
  }

  const cleanup = () => refreshCleanup();
  return cleanup;

  async function refresh() {
    const hint = $('k-ns-hint');
    try {
      const data = await API.kubernetes(ns);
      hint.className = 'muted'; hint.textContent = '';
      $('k-pods').innerHTML = data.pods.map((p) =>
        `<tr>
          <td>${esc(p.name)}</td>
          <td>${esc(p.phase)}</td>
          <td>${dot(p.ready)}${p.ready}</td>
          <td>${p.restarts}</td>
          <td>${p.app || p.name.startsWith('data-seeder') ? '<button class="btn sm danger k-del" data-pod="' + esc(p.name) + '">🗑</button>' : '—'}</td>
        </tr>`
      ).join('') || `<tr><td colspan="5" class="muted">sin pods en «${esc(ns)}»</td></tr>`;
      $('k-hpa').innerHTML = data.hpas.map((h) =>
        `<tr><td>${esc(h.name)}</td><td>${esc(h.target ?? '—')}</td><td>${h.currentReplicas ?? '—'}/${h.minReplicas ?? '?'}-${h.maxReplicas ?? '?'}</td><td>${h.currentCPU ?? '—'}% / ${h.targetCPU ?? '—'}%</td></tr>`
      ).join('') || `<tr><td colspan="4" class="muted">sin HPAs en «${esc(ns)}»</td></tr>`;

      // fetch history for deployments that have replicas, keep in-place accumulation
      for (const dep of data.deployments) {
        if (dep.replicas > 0 || dep.hpa) {
          const entry = historyCache[dep.name] ?? { start: Date.now(), series: [] };
          entry.start = entry.start || Date.now();
          entry.series.push({ t: Date.now(), replicas: dep.replicas, ready: dep.readyReplicas });
          if (entry.series.length > 1200) entry.series.shift();
          historyCache[dep.name] = entry;
        }
      }
      drawChart();
    } catch (e) {
      hint.className = 'msg err';
      hint.textContent = 'Kubernetes no disponible: ' + e.message +
        ' — es opcional: configura K8S_API_SERVER y monta los certificados en k8s/certs/ (ver .env.example).';
    }
  }

  function visible(names) {
    return names.filter((n) => historyCache[n]).sort((a, b) => {
      const ta = historyCache[a].start, tb = historyCache[b].start;
      return ta - tb;
    });
  }

  function drawChart() {
    const wrap = $('k-chart');
    const deps = visible(Object.keys(historyCache));
    if (!deps.length) { wrap.innerHTML = '<div class="empty">esperando muestras…</div>'; return; }
    const now = Date.now();
    const from = now - rangeMinutes * 60 * 1000;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', '100%');
    svg.setAttribute('height', '220');
    svg.style.height = '220px';

    const W = 1000, H = 200, pad = { l: 30, r: 10, t: 8, b: 20 };
    const cw = W - pad.l - pad.r, ch = H - pad.t - pad.b;

    // y-domain: max replicas across visible windows (min 4 for readability)
    let maxR = 4;
    for (const d of deps) {
      for (const s of historyCache[d].series) if (s.t >= from) maxR = Math.max(maxR, s.replicas + 1);
    }
    maxR = Math.min(maxR, Math.max(4, Math.ceil(maxR)));

    const xOf = (t) => pad.l + cw * (1 - (now - t) / (rangeMinutes * 60 * 1000));
    const yOf = (r) => pad.t + ch * (1 - r / maxR);

    // grid lines
    const grid = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    for (let r = 0; r <= maxR; r++) {
      const y = yOf(r);
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('x1', pad.l); line.setAttribute('x2', W - pad.r);
      line.setAttribute('y1', y); line.setAttribute('y2', y);
      line.setAttribute('stroke', r === 0 ? '#444' : '#2a2a2a'); line.setAttribute('stroke-width', '1');
      grid.appendChild(line);
      const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      t.setAttribute('x', pad.l - 6); t.setAttribute('y', y + 4);
      t.setAttribute('text-anchor', 'end'); t.setAttribute('fill', '#888'); t.setAttribute('font-size', '11');
      t.textContent = r;
      grid.appendChild(t);
    }
    svg.appendChild(grid);

    deps.forEach((d, i) => {
      const color = CHART_COLORS[i % CHART_COLORS.length];
      const pts = historyCache[d].series.filter((s) => s.t >= from);
      if (pts.length < 2) return;
      // line
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', pts.map((s, j) =>
        `${j === 0 ? 'M' : 'L'}${xOf(s.t).toFixed(1)},${yOf(s.replicas).toFixed(1)}`).join(' '));
      path.setAttribute('fill', 'none'); path.setAttribute('stroke', color);
      path.setAttribute('stroke-width', '2'); path.setAttribute('stroke-linejoin', 'round');
      path.setAttribute('stroke-linecap', 'round');
      svg.appendChild(path);
      // legend
      const legend = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      legend.setAttribute('x', pad.l + cw - 120 + (i * Math.min(130, cw / deps.length)));
      legend.setAttribute('y', H - 4); legend.setAttribute('fill', color); legend.setAttribute('font-size', '12');
      legend.textContent = d;
      svg.appendChild(legend);
    });

    wrap.innerHTML = '';
    wrap.appendChild(svg);
  }
}