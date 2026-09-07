(() => {
  const byId = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

  let battleTargets = [];
  let battleTimer = null;
  let battleScanning = false;

  // Presencia genérica: se usa solo para lectura/estado visual.
  // No modifica matches/pending_target ni dispara acciones automáticas.
  const GENERIC_PRESENCE_THRESHOLD = 0.72;

  function addBattleTab() {
    const tabs = document.querySelector('.tabs');
    const settingsTab = tabs?.querySelector('[data-target="settingsSection"]');
    if (!tabs || byId('battleSection')) return;

    const tab = document.createElement('button');
    tab.className = 'tab';
    tab.dataset.target = 'battleSection';
    tab.textContent = 'Battle';
    tabs.insertBefore(tab, settingsTab || null);

    const section = document.createElement('section');
    section.id = 'battleSection';
    section.className = 'tab-section';
    section.innerHTML = `
      <article class="panel">
        <div class="panel-title-row">
          <div>
            <span class="badge">BATTLE</span>
            <h2>Referencias detectables</h2>
            <p class="muted">Las referencias sirven para identificar objetivos concretos. La presencia genérica se informa aunque no alcance el match exacto.</p>
          </div>
          <a class="button-link secondary" href="/battle">Administrar referencias</a>
        </div>
        <div id="battleReferenceList" class="card-grid single"></div>
        <p id="battleReferenceStatus" class="status"></p>
      </article>

      <article class="panel">
        <div class="panel-title-row">
          <div>
            <span class="badge">MONITOR</span>
            <h2>Detección Battle</h2>
            <p class="muted">Analiza periódicamente la Región Battle usando el intervalo configurado.</p>
          </div>
          <div class="action-row compact">
            <button id="startBattleMonitorBtn" class="primary">Iniciar detección</button>
            <button id="stopBattleMonitorBtn" class="danger" disabled>Detener</button>
          </div>
        </div>
        <div class="info-box">
          <strong id="battleMonitorState">Detenido</strong>
          <p id="battleMonitorInfo" class="muted small">Sin análisis todavía.</p>
          <p id="battlePresenceInfo" class="small" style="margin-top:8px">Presencia Battle: sin datos.</p>
        </div>
        <div class="table-wrap" style="margin-top:14px">
          <table>
            <thead><tr><th>Estado</th><th>Referencia</th><th>Prioridad</th><th>Similitud</th><th>Centro Región Battle</th></tr></thead>
            <tbody id="battleMonitorBody"><tr><td colspan="5" class="muted">Sin detecciones.</td></tr></tbody>
          </table>
        </div>
        <p class="muted small">La presencia genérica solo informa si Battle parece ocupado; no genera input automático de mouse o teclado.</p>
      </article>`;

    const settingsSection = byId('settingsSection');
    settingsSection?.parentNode?.insertBefore(section, settingsSection);

    byId('startBattleMonitorBtn').onclick = startBattleMonitor;
    byId('stopBattleMonitorBtn').onclick = stopBattleMonitor;
  }

  function regionCenter() {
    const region = settings?.battle_event_region || {};
    const x = Number(region.x || 0);
    const y = Number(region.y || 0);
    const width = Math.max(1, Number(region.width || 1));
    const height = Math.max(1, Number(region.height || 1));
    return {
      x: Math.round(x + width / 2),
      y: Math.round(y + height / 2),
    };
  }

  function renderReferences() {
    const container = byId('battleReferenceList');
    if (!container) return;
    container.innerHTML = battleTargets.map(target => `
      <label class="library-card" style="cursor:pointer">
        <div class="card-main">
          <input class="battle-target-toggle" type="checkbox" data-id="${esc(target.id)}" ${target.enabled !== false ? 'checked' : ''} style="width:auto">
          <img class="checkpoint-thumb" src="/api/battle/targets/${encodeURIComponent(target.id)}/image?t=${Date.now()}" alt="${esc(target.name)}">
          <div>
            <h3>${esc(target.name)}</h3>
            <p>prioridad ${Number(target.priority || 100)}${target.image_width && target.image_height ? ` · ${target.image_width}×${target.image_height}` : ''}</p>
          </div>
        </div>
        <span class="badge subtle">${target.enabled !== false ? 'ACTIVA' : 'DESACTIVADA'}</span>
      </label>`).join('') || '<p class="empty">No hay referencias Battle cargadas.</p>';

    container.querySelectorAll('.battle-target-toggle').forEach(input => {
      input.onchange = async () => {
        input.disabled = true;
        const response = await fetch(`/api/battle/targets/${encodeURIComponent(input.dataset.id)}`, {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({enabled: input.checked}),
        }).then(r => r.json()).catch(err => ({ok:false,error:String(err)}));
        input.disabled = false;
        if (!response.ok) {
          input.checked = !input.checked;
          byId('battleReferenceStatus').textContent = response.error || 'No se pudo actualizar la referencia.';
          return;
        }
        battleTargets = response.targets || battleTargets;
        byId('battleReferenceStatus').textContent = input.checked ? 'Referencia activada.' : 'Referencia desactivada.';
        renderReferences();
      };
    });
  }

  async function refreshBattleData() {
    const data = await fetch('/api/status').then(r => r.json());
    battleTargets = data.battle_targets || [];
    if (data.settings) settings = data.settings;
    renderReferences();
  }

  function genericPresence(state) {
    const debug = Array.isArray(state?.scan?.match_debug) ? state.scan.match_debug : [];
    const scores = debug
      .map(item => Number(item?.best_similarity))
      .filter(Number.isFinite);
    const bestScore = scores.length ? Math.max(...scores) : null;
    const hasTarget = bestScore !== null && bestScore >= GENERIC_PRESENCE_THRESHOLD;
    return {hasTarget, bestScore};
  }

  function renderScan(state) {
    const pending = state?.pending_target;
    const center = regionCenter();
    const rows = [];
    if (pending) rows.push({...pending, stateLabel: 'detectada'});
    for (const queued of (state?.queue || [])) rows.push({...queued, stateLabel: 'en cola'});

    byId('battleMonitorBody').innerHTML = rows.map(item => `
      <tr>
        <td>${esc(item.stateLabel)}</td>
        <td>${esc(item.name)}</td>
        <td>${Number(item.priority || 100)}</td>
        <td>${((Number(item.similarity || 0)) * 100).toFixed(1)}%</td>
        <td>${center.x}, ${center.y}</td>
      </tr>`).join('') || '<tr><td colspan="5" class="muted">Sin detecciones exactas.</td></tr>';

    const presence = genericPresence(state);
    const presenceEl = byId('battlePresenceInfo');
    if (presenceEl) {
      if (presence.bestScore === null) {
        presenceEl.textContent = 'Presencia Battle: sin referencias activas para estimar actividad.';
      } else if (presence.hasTarget) {
        presenceEl.textContent = `Presencia Battle: OCUPADO · score visual ${(presence.bestScore * 100).toFixed(1)}%`;
      } else {
        presenceEl.textContent = `Presencia Battle: VACÍO · score visual ${(presence.bestScore * 100).toFixed(1)}%`;
      }
    }

    if (pending) {
      byId('battleMonitorInfo').textContent = `Detectada ${pending.name}. Centro configurado de Región Battle: (${center.x}, ${center.y}).`;
    } else if (presence.hasTarget) {
      byId('battleMonitorInfo').textContent = 'Hay una fila/actividad visible en Battle, aunque no coincida con una referencia exacta.';
    } else {
      byId('battleMonitorInfo').textContent = 'Battle sin presencia visual suficiente.';
    }
  }

  async function scanBattleOnce() {
    if (!battleScanning) return;
    byId('battleMonitorState').textContent = 'Analizando…';
    const data = await fetch('/api/battle/scan-passive', {method:'POST'})
      .then(r => r.json())
      .catch(err => ({ok:false,error:String(err)}));

    if (!battleScanning) return;
    if (!data.ok) {
      byId('battleMonitorState').textContent = 'Error';
      byId('battleMonitorInfo').textContent = data.error || 'No se pudo analizar Battle.';
      scheduleNextScan();
      return;
    }

    byId('battleMonitorState').textContent = 'Activo';
    renderScan(data.state || {});
    scheduleNextScan();
  }

  function scheduleNextScan() {
    if (!battleScanning) return;
    clearTimeout(battleTimer);
    const seconds = Math.max(0.5, Number(settings?.battle_poll_seconds || 1));
    battleTimer = setTimeout(scanBattleOnce, seconds * 1000);
  }

  async function startBattleMonitor() {
    if (battleScanning) return;
    await refreshBattleData();
    battleScanning = true;
    byId('startBattleMonitorBtn').disabled = true;
    byId('stopBattleMonitorBtn').disabled = false;
    byId('battleMonitorState').textContent = 'Activo';
    const seconds = Math.max(0.5, Number(settings?.battle_poll_seconds || 1));
    byId('battleMonitorInfo').textContent = `Analizando cada ${seconds.toFixed(1)} s.`;
    scanBattleOnce();
  }

  function stopBattleMonitor() {
    battleScanning = false;
    clearTimeout(battleTimer);
    battleTimer = null;
    byId('startBattleMonitorBtn').disabled = false;
    byId('stopBattleMonitorBtn').disabled = true;
    byId('battleMonitorState').textContent = 'Detenido';
    byId('battleMonitorInfo').textContent = 'Monitor Battle detenido.';
    if (byId('battlePresenceInfo')) byId('battlePresenceInfo').textContent = 'Presencia Battle: sin datos.';
  }

  addBattleTab();
  refreshBattleData().catch(() => {});
})();