(() => {
  const byId = id => document.getElementById(id);
  let battleTimer = null;
  let battleRunning = false;
  let battleTargets = [];

  function currentSettings() { return window.settings || settings || {}; }

  function ensureExecutionSection() {
    const nav = document.querySelector('.tabs');
    const routinesSection = byId('routinesSection');
    const runPanel = byId('startRoutineBtn')?.closest('.hero-panel');
    if (!nav || !routinesSection || !runPanel || byId('executionSection')) return;

    const tab = document.createElement('button');
    tab.className = 'tab';
    tab.dataset.target = 'executionSection';
    tab.textContent = 'Ejecutar';
    nav.insertBefore(tab, nav.firstChild);

    const section = document.createElement('section');
    section.id = 'executionSection';
    section.className = 'tab-section';
    section.innerHTML = `
      <div id="executionRoutineSlot"></div>
      <article class="panel">
        <div class="panel-title-row">
          <div>
            <span class="badge">BATTLE EN VIVO</span>
            <h2>Detección Battle</h2>
            <p class="muted small">En espera se analiza Battle. Cuando hay una acción pendiente se vigila únicamente el canal Loot hasta que cambie.</p>
          </div>
          <div class="action-row compact">
            <button id="startBattleMonitorBtn" class="primary">Iniciar detección</button>
            <button id="stopBattleMonitorBtn" class="danger" disabled>Detener</button>
          </div>
        </div>
        <p id="battleMonitorStatus" class="status">Detenido.</p>
        <div class="grid cols-2">
          <div>
            <h3>Referencias detectables</h3>
            <p class="muted small">La imagen Battle identifica la referencia; Loot marca el fin de la espera.</p>
            <div id="executionBattleTargets" class="stack"></div>
          </div>
          <div>
            <h3>Estado Battle</h3>
            <div id="executionBattleLast" class="info-box">Detección detenida.</div>
          </div>
        </div>
      </article>`;

    routinesSection.parentNode.insertBefore(section, routinesSection);
    byId('executionRoutineSlot').appendChild(runPanel);
    byId('startBattleMonitorBtn').onclick = startBattleMonitor;
    byId('stopBattleMonitorBtn').onclick = stopBattleMonitor;

    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.tab-section').forEach(x => x.classList.remove('active'));
    tab.classList.add('active');
    section.classList.add('active');
  }

  async function loadData() {
    const data = await fetch('/api/battle/targets').then(r => r.json());
    battleTargets = data.ok ? (data.targets || []) : [];
    renderBattleTargets();
  }

  function renderBattleTargets() {
    const root = byId('executionBattleTargets');
    if (!root) return;
    root.innerHTML = battleTargets.length ? battleTargets.map(t => `
      <div class="library-card">
        <div class="card-main" style="align-items:flex-start">
          <input class="execution-battle-toggle" data-id="${String(t.id)}" type="checkbox" ${t.enabled ? 'checked' : ''} style="width:auto;margin-top:8px" title="Detectar">
          <div class="grow">
            <strong>${String(t.name || t.id)}</strong>
            <p>prioridad ${Number(t.priority || 100)} · ${t.enabled ? 'activa' : 'desactivada'} · Loot controla el cierre</p>
            <label style="display:flex;flex-direction:row;align-items:center;gap:8px;margin:8px 0;width:max-content">
              <input class="execution-battle-loot-toggle" data-id="${String(t.id)}" type="checkbox" ${t.loot_enabled ? 'checked' : ''} style="width:auto">
              <strong>Loot</strong>
            </label>
            <div class="action-row compact" style="align-items:flex-start">
              <div>
                <div class="muted small">Inicia detección</div>
                <img src="/api/battle/targets/${encodeURIComponent(t.id)}/image?t=${Date.now()}" style="max-width:180px;max-height:80px;border-radius:6px">
              </div>
            </div>
          </div>
        </div>
      </div>`).join('') : '<p class="muted">No hay referencias Battle cargadas.</p>';
  }

  async function updateTarget(id, payload) {
    const data = await fetch(`/api/battle/targets/${encodeURIComponent(id)}`, {
      method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)
    }).then(r=>r.json());
    if (data.ok) {
      battleTargets = data.targets || battleTargets;
      renderBattleTargets();
    }
  }

  async function setBattleDetectionEnabled(enabled) {
    const data = await fetch('/api/settings', {
      method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({battle_detection_enabled: !!enabled})
    }).then(r=>r.json());
    if (!data.ok) throw new Error(data.error || 'No se pudo actualizar el estado Battle.');
    if (typeof settings !== 'undefined' && data.settings) settings = data.settings;
    return data.settings || {};
  }

  function battleIntervalMs() {
    return Math.max(200, Number(currentSettings().battle_poll_seconds ?? 1) * 1000);
  }

  function phaseLabel(phase) {
    if (phase === 'waiting_loot_change') return 'Esperando cambio en Loot';
    if (phase === 'loot_change_detected') return 'Cambio en Loot detectado';
    return 'Listo para detectar';
  }

  function timingHtml(scan) {
    const t = scan?.timing;
    if (!t) return '';
    const mode = scan?.scan_mode || '-';
    return `<hr style="border:0;border-top:1px solid #273550;margin:10px 0">
      <div class="muted small">Rendimiento · modo <strong>${mode}</strong></div>
      <div class="muted small">total ${Number(t.total_scan_ms || 0).toFixed(0)} ms · captura ${Number(t.capture_ms || 0).toFixed(0)} ms · Battle ${Number(t.battle_match_ms || 0).toFixed(0)} ms · comparación ${Number(t.visual_compare_ms || 0).toFixed(0)} ms</div>`;
  }

  async function scanBattleOnce() {
    if (!battleRunning) return;
    const status = byId('battleMonitorStatus');
    try {
      status.textContent = 'Analizando Battle…';
      const data = await fetch('/api/battle/scan-passive', {method:'POST'}).then(r=>r.json());
      if (!data.ok) {
        status.textContent = data.error || 'Error al analizar Battle.';
        return;
      }

      const state = data.state || {};
      if (state.busy) {
        status.textContent = 'Análisis anterior todavía en curso; se omitió este ciclo.';
        return;
      }
      const scan = state.scan || {};
      if (scan.detection_enabled === false) {
        battleRunning = false;
        clearTimeout(battleTimer);
        battleTimer = null;
        byId('startBattleMonitorBtn').disabled = false;
        byId('stopBattleMonitorBtn').disabled = true;
        byId('battleMonitorStatus').textContent = 'Detenido.';
        byId('executionBattleLast').textContent = 'Detección detenida.';
        return;
      }

      const pending = state.pending_target;
      const phase = state.phase || 'idle';
      const triggerText = state.action_triggered ? '<br><strong>Nuevo target detectado.</strong>' : '';
      let releaseText = '';
      if (state.released && state.release_reason === 'loot_changed') {
        releaseText = '<br><strong>Loot cambió: Battle liberado.</strong>';
      } else if (state.released && state.timeout_forced) {
        releaseText = '<br><strong>Timeout: estado Battle liberado internamente.</strong>';
      }

      const elapsed = state.action_elapsed_seconds;
      const lootSimilarity = state.loot_similarity;

      byId('executionBattleLast').innerHTML = `
        ${pending ? `<strong>${String(pending.name || pending.target_id || 'Referencia')}</strong><br>inicio ${(Number(pending.similarity || 0) * 100).toFixed(1)}%<br>` : ''}
        estado: <strong>${phaseLabel(phase)}</strong>
        ${lootSimilarity !== null && lootSimilarity !== undefined ? `<br>similitud Loot: <strong>${(Number(lootSimilarity) * 100).toFixed(1)}%</strong>` : ''}
        ${elapsed !== null && elapsed !== undefined ? `<br>tiempo: ${Number(elapsed).toFixed(1)} s / ${Number(currentSettings().battle_action_timeout_seconds ?? 20).toFixed(0)} s` : ''}
        ${triggerText}${releaseText}
        ${timingHtml(scan)}`;

      status.textContent = `Detectando · ${phaseLabel(phase)} · último ciclo ${Number(scan?.timing?.total_scan_ms || 0).toFixed(0)} ms.`;
    } catch (err) {
      status.textContent = `Error: ${err}`;
    }
  }

  function scheduleNextBattleScan() {
    clearTimeout(battleTimer);
    if (!battleRunning) return;
    battleTimer = setTimeout(async () => {
      await scanBattleOnce();
      scheduleNextBattleScan();
    }, battleIntervalMs());
  }

  async function startBattleMonitor() {
    const startBtn = byId('startBattleMonitorBtn');
    const stopBtn = byId('stopBattleMonitorBtn');
    startBtn.disabled = true;
    byId('battleMonitorStatus').textContent = 'Iniciando detección…';
    try {
      await setBattleDetectionEnabled(true);
      battleRunning = true;
      stopBtn.disabled = false;
      await scanBattleOnce();
      scheduleNextBattleScan();
    } catch (err) {
      battleRunning = false;
      startBtn.disabled = false;
      stopBtn.disabled = true;
      byId('battleMonitorStatus').textContent = `Error: ${err}`;
    }
  }

  async function stopBattleMonitor() {
    battleRunning = false;
    clearTimeout(battleTimer);
    battleTimer = null;
    byId('startBattleMonitorBtn').disabled = false;
    byId('stopBattleMonitorBtn').disabled = true;
    byId('battleMonitorStatus').textContent = 'Deteniendo…';
    try {
      await setBattleDetectionEnabled(false);
      await fetch('/api/battle/reset', {method:'POST'});
    } catch (_) {}
    byId('battleMonitorStatus').textContent = 'Detenido.';
    byId('executionBattleLast').textContent = 'Detección detenida.';
  }

  // El polling principal sigue consultando /api/status, pero evitamos volver a
  // renderizar la rutina y descargar el mismo checkpoint PNG cada segundo.
  function optimizeRoutineRecordingPolling() {
    if (typeof updateRecordingUi !== 'function' || typeof refreshSelectedRoutine !== 'function') return;

    const originalUpdateRecordingUi = updateRecordingUi;
    let lastRecording = null;
    let lastRenderedSignature = null;

    updateRecordingUi = function(recordingState = null) {
      if (recordingState) lastRecording = recordingState;
      originalUpdateRecordingUi(recordingState);

      const stateNode = byId('recordingEditorState');
      if (stateNode && recordingState?.active) {
        const timed = recordingState.timed_active
          ? ` · Modo 2s ACTIVO · muestras ${Number(recordingState.timed_sample_count || 0)}`
          : ' · F9 inicia modo automático cada 2s';
        stateNode.textContent += timed;
      }
    };

    refreshSelectedRoutine = async function() {
      if (!selectedRoutine) return;
      const recordingState = lastRecording || {};
      const lastPos = recordingState.last_position || {};
      const lastCheckpoint = recordingState.last_checkpoint || {};
      const signature = [
        selectedRoutine.id,
        Number(lastPos.step_count || 0),
        Number(lastCheckpoint.step_number || 0),
        String(lastCheckpoint.image || ''),
      ].join('|');

      if (signature === lastRenderedSignature) return;
      const d = await fetch(`/api/routines/${selectedRoutine.id}`).then(r => r.json());
      if (d.ok) {
        lastRenderedSignature = signature;
        showRoutineEditor(d.routine);
      }
    };
  }

  function ensureTimedRecorderHint() {
    const recordingBox = document.querySelector('#editorPanel .recording-box');
    if (!recordingBox || byId('timedRecorderHint')) return;
    const hint = document.createElement('div');
    hint.id = 'timedRecorderHint';
    hint.className = 'info-box';
    hint.style.marginTop = '10px';
    hint.innerHTML = '<strong>Método 2: muestreo automático</strong><br><span class="muted small">Con la grabación activa, presiona <kbd>F9</kbd> para iniciar/detener. Guarda la posición actual del mouse cada 2 segundos como pasos X/Y normales de la misma rutina.</span>';
    recordingBox.insertAdjacentElement('afterend', hint);
  }

  document.addEventListener('change', e => {
    const toggle = e.target.closest('.execution-battle-toggle');
    if (toggle) {
      updateTarget(toggle.dataset.id, {enabled:toggle.checked});
      return;
    }
    const lootToggle = e.target.closest('.execution-battle-loot-toggle');
    if (lootToggle) updateTarget(lootToggle.dataset.id, {loot_enabled:lootToggle.checked});
  });

  ensureExecutionSection();
  optimizeRoutineRecordingPolling();
  ensureTimedRecorderHint();
  loadData();

  if (!document.querySelector('script[data-routine-actions-ui]')) {
    const script = document.createElement('script');
    script.src = '/static/routine_actions_ui.js';
    script.dataset.routineActionsUi = '1';
    document.body.appendChild(script);
  }
})();