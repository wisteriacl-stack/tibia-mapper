(() => {
  const byId = id => document.getElementById(id);

  function ensureAiPanel() {
    const section = byId('executionSection');
    if (!section || byId('aiAdvisorPanel')) return;

    const panel = document.createElement('article');
    panel.id = 'aiAdvisorPanel';
    panel.className = 'panel';
    panel.innerHTML = `
      <div class="panel-title-row">
        <div>
          <span class="badge">IA</span>
          <h2>Advisor</h2>
          <p class="muted small">Analiza estado Battle, Health Monitor, logs, rutina y opcionalmente contexto offline de TibiaMaps. No ejecuta input.</p>
        </div>
        <div class="action-row compact">
          <button id="analyzeAiBtn" class="primary">Analizar estado</button>
        </div>
      </div>
      <div class="grid cols-3" style="margin:10px 0">
        <label>X mapa<input id="aiMapX" type="number" value="31946"></label>
        <label>Y mapa<input id="aiMapY" type="number" value="31900"></label>
        <label>Z mapa<input id="aiMapZ" type="number" value="7" min="0" max="15"></label>
      </div>
      <label style="display:flex;flex-direction:row;align-items:center;gap:8px;width:max-content;margin-bottom:10px">
        <input id="aiUseMap" type="checkbox" checked style="width:auto">
        <span>Incluir contexto local TibiaMaps</span>
      </label>
      <p id="aiAdvisorStatus" class="status">Listo.</p>
      <div id="aiAdvisorResult" class="info-box">Todavía no hay análisis.</div>`;

    section.appendChild(panel);
    byId('analyzeAiBtn').onclick = analyzeNow;
  }

  function selectedRoutineId() {
    try {
      return selectedRoutine?.id || null;
    } catch (_) {
      return null;
    }
  }

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
  }

  function mapPayload() {
    if (!byId('aiUseMap')?.checked) return null;
    const x = Number(byId('aiMapX')?.value);
    const y = Number(byId('aiMapY')?.value);
    const z = Number(byId('aiMapZ')?.value);
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return null;
    return {x, y, z};
  }

  function mapHtml(analysis) {
    if (analysis.map_error) {
      return `<hr style="border:0;border-top:1px solid #273550;margin:10px 0"><div class="muted small">Mapa: ${esc(analysis.map_error)}</div>`;
    }
    const map = analysis.map_context;
    if (!map) return '';
    const p = map.position || {};
    const pf = map.pathfinding || {};
    const markers = (map.nearby_markers || []).slice(0, 5).map(m => {
      const label = m.description || m.icon || 'marker';
      return `${esc(label)} (${Number(m.distance_tiles || 0).toFixed(1)} tiles)`;
    }).join(' · ');
    return `<hr style="border:0;border-top:1px solid #273550;margin:10px 0">
      <div><strong>Mapa local</strong></div>
      <div class="muted small">posición ${esc(p.x)}, ${esc(p.y)}, ${esc(p.z)} · path=${esc(pf.state || '-')} · fricción=${esc(pf.friction ?? '-')}</div>
      ${markers ? `<div class="muted small">cercanos: ${markers}</div>` : '<div class="muted small">sin marcadores cercanos en el radio actual</div>'}`;
  }

  async function analyzeNow() {
    const button = byId('analyzeAiBtn');
    const status = byId('aiAdvisorStatus');
    const resultBox = byId('aiAdvisorResult');
    button.disabled = true;
    status.textContent = 'Analizando estado, logs, rutina y mapa local…';

    try {
      const payload = {routine_id: selectedRoutineId()};
      const position = mapPayload();
      if (position) payload.position = position;

      const data = await fetch('/api/ai/analyze', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      }).then(r => r.json());

      if (!data.ok) throw new Error(data.error || 'No se pudo analizar el estado.');
      const a = data.analysis || {};
      const findings = (a.findings || []).map(item => `<li>${esc(item)}</li>`).join('');
      const snapshot = a.context_snapshot || {};

      resultBox.innerHTML = `
        <div><strong>${esc(a.summary || 'Análisis completado')}</strong></div>
        <div class="muted small">provider=${esc(a.provider || '-')} · model=${esc(a.model || '-')} · status=${esc(a.status || '-')} · confianza ${(Number(a.confidence || 0) * 100).toFixed(0)}%</div>
        <ul>${findings || '<li>Sin hallazgos.</li>'}</ul>
        <div><strong>Recomendación</strong><br>${esc(a.recommendation || '-')}</div>
        ${mapHtml(a)}
        <hr style="border:0;border-top:1px solid #273550;margin:10px 0">
        <div class="muted small">HP=${esc(snapshot.hp)} · Battle=${esc(snapshot.battle_phase)} · grabación=${snapshot.recording_active ? 'activa' : 'detenida'} · rutina=${esc(snapshot.routine_id || '-')} · logs=${Number(snapshot.recent_log_count || 0)}</div>`;
      status.textContent = 'Análisis completado.';
    } catch (err) {
      status.textContent = `Error: ${err}`;
      resultBox.textContent = String(err);
    } finally {
      button.disabled = false;
    }
  }

  function waitForExecutionSection() {
    ensureAiPanel();
    if (!byId('aiAdvisorPanel')) setTimeout(waitForExecutionSection, 250);
  }

  waitForExecutionSection();
})();
