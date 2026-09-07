(() => {
  const byId = id => document.getElementById(id);
  const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

  const ACTION_LABELS = {
    left_click: 'Click izquierdo',
    move_mouse: 'Mover mouse',
    write: 'Escribir texto',
  };

  function actionDescription(action = {}) {
    const type = action.type || '';
    if (type === 'left_click' || type === 'move_mouse') {
      return `${ACTION_LABELS[type] || type} · (${Number(action.x || 0)}, ${Number(action.y || 0)})`;
    }
    if (type === 'write') {
      return `Escribir texto · “${String(action.text || '').slice(0, 60)}”`;
    }
    return 'Acción';
  }

  async function saveRoutineSteps(steps) {
    if (!selectedRoutine) return null;
    const data = await fetch(`/api/routines/${encodeURIComponent(selectedRoutine.id)}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        name: byId('editName').value || selectedRoutine.name,
        version: byId('editVersion').value || selectedRoutine.version,
        steps,
      }),
    }).then(r => r.json());

    if (!data.ok) throw new Error(data.error || 'No se pudo guardar la rutina.');
    selectedRoutine = data.routine;
    routines = data.routines || routines;
    window.routines = routines;
    return data.routine;
  }

  function installActionPanel() {
    const editor = byId('editorPanel');
    if (!editor || byId('recordingActionPanel')) return;

    const anchor = byId('recordingEditorState');
    const panel = document.createElement('div');
    panel.id = 'recordingActionPanel';
    panel.className = 'recording-box hidden';
    panel.innerHTML = `
      <div class="grow">
        <strong>Agregar paso de acción</strong>
        <p class="muted small">Disponible mientras la rutina está en modo grabación.</p>
        <div class="grid cols-2">
          <label>Acción
            <select id="routineActionType">
              <option value="move_mouse">Mover mouse</option>
              <option value="left_click">Click izquierdo</option>
              <option value="write">Escribir texto</option>
            </select>
          </label>
          <div id="routineActionFields"></div>
        </div>
        <div class="action-row compact">
          <button type="button" id="captureRoutineActionF12" class="secondary">Tomar coordenada con F12</button>
          <button type="button" id="addRoutineActionStep" class="primary">Agregar acción como paso</button>
        </div>
        <p id="routineActionStatus" class="status"></p>
      </div>`;
    anchor.insertAdjacentElement('afterend', panel);

    byId('routineActionType').onchange = renderActionFields;
    byId('captureRoutineActionF12').onclick = captureActionPosition;
    byId('addRoutineActionStep').onclick = addActionStep;
    renderActionFields();
  }

  function renderActionFields() {
    const type = byId('routineActionType')?.value || 'move_mouse';
    const root = byId('routineActionFields');
    if (!root) return;

    if (type === 'write') {
      root.innerHTML = `<label>Texto<input id="routineActionText" placeholder="Texto a registrar"></label>`;
      byId('captureRoutineActionF12').classList.add('hidden');
    } else {
      root.innerHTML = `<div class="grid cols-2"><label>X<input id="routineActionX" type="number" value="0"></label><label>Y<input id="routineActionY" type="number" value="0"></label></div>`;
      byId('captureRoutineActionF12').classList.remove('hidden');
    }
  }

  async function captureActionPosition() {
    const status = byId('routineActionStatus');
    status.textContent = 'Lleva Tibia al primer plano, posiciona el cursor y presiona F12…';
    try {
      const data = await fetch('/api/events/capture-position', {method: 'POST'}).then(r => r.json());
      if (!data.ok) throw new Error(data.error || 'No se pudo capturar la coordenada.');
      byId('routineActionX').value = data.x;
      byId('routineActionY').value = data.y;
      status.textContent = `Coordenada capturada: (${data.x}, ${data.y}).`;
    } catch (err) {
      status.textContent = `Error: ${err.message || err}`;
    }
  }

  async function addActionStep() {
    if (!selectedRoutine) return;
    if (!recordingActive || recordingRoutineId !== selectedRoutine.id) {
      byId('routineActionStatus').textContent = 'Primero inicia la grabación de esta rutina.';
      return;
    }

    const type = byId('routineActionType').value;
    let action;
    if (type === 'write') {
      const text = String(byId('routineActionText')?.value || '');
      if (!text) {
        byId('routineActionStatus').textContent = 'Ingresa el texto de la acción.';
        return;
      }
      action = {type, text};
    } else {
      action = {
        type,
        x: Number(byId('routineActionX')?.value || 0),
        y: Number(byId('routineActionY')?.value || 0),
      };
    }

    const steps = [...(selectedRoutine.steps || []), {type: 'action', action}];
    byId('routineActionStatus').textContent = 'Guardando paso de acción…';
    try {
      await saveRoutineSteps(steps);
      byId('routineActionStatus').textContent = `Acción agregada como paso ${selectedRoutine.steps.length}: ${actionDescription(action)}.`;
      window.renderSteps();
    } catch (err) {
      byId('routineActionStatus').textContent = `Error: ${err.message || err}`;
    }
  }

  const originalUpdateRecordingUi = window.updateRecordingUi;
  window.updateRecordingUi = function patchedUpdateRecordingUi(s = null) {
    originalUpdateRecordingUi?.(s);
    const panel = byId('recordingActionPanel');
    if (!panel) return;
    const activeForSelected = !!recordingActive && !!selectedRoutine && recordingRoutineId === selectedRoutine.id;
    panel.classList.toggle('hidden', !activeForSelected);
  };

  const originalRenderSteps = window.renderSteps;
  window.renderSteps = function patchedRenderSteps() {
    const steps = selectedRoutine?.steps || [];
    const root = byId('stepsList');
    if (!root) return originalRenderSteps?.();

    byId('checkpointSummary').textContent = `${steps.filter(s => s.validation_image).length}/${steps.length} con imagen · ${steps.filter(s => s.type === 'action').length} acciones`;
    byId('insertIndex').value = steps.length;

    root.innerHTML = steps.map((step, i) => {
      if (step.type === 'action') {
        return `<article class="step-card" data-index="${i}">
          <div class="step-number">${i + 1}</div>
          <div class="grow">
            <span class="badge">ACCIÓN</span>
            <h3>${esc(ACTION_LABELS[step.action?.type] || step.action?.type || 'Acción')}</h3>
            <p class="muted">${esc(actionDescription(step.action || {}))}</p>
          </div>
          <button class="danger delete-step-btn" data-index="${i}">Eliminar</button>
        </article>`;
      }

      return `<article class="step-card" data-index="${i}">
        <div class="step-number">${i + 1}</div>
        <div class="step-fields"><label>X<input class="step-x" type="number" value="${Number(step.x || 0)}"></label><label>Y<input class="step-y" type="number" value="${Number(step.y || 0)}"></label></div>
        <div class="checkpoint-box">${step.validation_image ? `<img class="checkpoint-thumb" src="/api/routines/${selectedRoutine.id}/steps/${i}/checkpoint?t=${Date.now()}">` : '<div class="checkpoint-empty">Sin imagen</div>'}<div class="checkpoint-actions"><button class="secondary capture-checkpoint-btn" data-index="${i}">Capturar en 3s</button><label class="file-button">Subir imagen<input class="checkpoint-file" data-index="${i}" type="file" accept="image/*"></label>${step.validation_image ? `<button class="secondary compare-checkpoint-btn" data-index="${i}">Comparar ahora</button>` : ''}</div><span class="small muted compare-result" id="compareResult${i}"></span></div>
        <button class="danger delete-step-btn" data-index="${i}">Eliminar</button>
      </article>`;
    }).join('') || '<div class="empty">Sin pasos.</div>';
  };

  const saveBtn = byId('saveRoutineBtn');
  if (saveBtn) {
    saveBtn.onclick = async () => {
      if (!selectedRoutine) return;
      const cards = [...byId('stepsList').querySelectorAll('.step-card')];
      const steps = cards.map((card, i) => {
        const existing = selectedRoutine.steps?.[i] || {};
        if (existing.type === 'action') return existing;
        return {
          type: 'coordinate',
          x: Number(card.querySelector('.step-x').value),
          y: Number(card.querySelector('.step-y').value),
          ...(existing.validation_image ? {validation_image: existing.validation_image} : {}),
        };
      });
      try {
        await saveRoutineSteps(steps);
        byId('editorStatus').textContent = 'Cambios guardados.';
        renderRoutines();
        window.renderSteps();
      } catch (err) {
        byId('editorStatus').textContent = `Error: ${err.message || err}`;
      }
    };
  }

  installActionPanel();
  window.renderSteps();
  window.updateRecordingUi();
})();
