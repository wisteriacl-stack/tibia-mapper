(() => {
  const state = {
    target: null,
    image: null,
    naturalWidth: 0,
    naturalHeight: 0,
    startX: 0,
    startY: 0,
    current: null,
    dragging: false,
  };

  const byId = id => document.getElementById(id);

  function ensureModal() {
    if (byId('regionSelectorModal')) return;

    const modal = document.createElement('div');
    modal.id = 'regionSelectorModal';
    modal.className = 'region-selector-modal hidden';
    modal.innerHTML = `
      <div class="region-selector-dialog">
        <div class="region-selector-head">
          <div>
            <span class="badge">SELECCIÓN VISUAL</span>
            <h2 id="regionSelectorTitle">Seleccionar región</h2>
            <p class="muted small">Arrastra sobre la imagen para marcar el recuadro exacto.</p>
          </div>
          <button type="button" id="regionSelectorClose" class="secondary">Cerrar</button>
        </div>
        <div class="region-selector-stage" id="regionSelectorStage">
          <img id="regionSelectorImage" alt="Captura completa">
          <div id="regionSelectorBox" class="region-selector-box hidden"></div>
        </div>
        <div class="region-selector-footer">
          <div>
            <strong id="regionSelectorCoords">Sin selección</strong>
            <div class="muted small" id="regionSelectorImageInfo"></div>
          </div>
          <div class="action-row compact">
            <button type="button" id="regionSelectorClear" class="secondary">Limpiar</button>
            <button type="button" id="regionSelectorUse" class="primary" disabled>Usar este recuadro</button>
          </div>
        </div>
      </div>`;
    document.body.appendChild(modal);

    byId('regionSelectorClose').onclick = close;
    byId('regionSelectorClear').onclick = clearSelection;
    byId('regionSelectorUse').onclick = applySelection;
    modal.addEventListener('click', e => { if (e.target === modal) close(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && !modal.classList.contains('hidden')) close(); });

    const stage = byId('regionSelectorStage');
    stage.addEventListener('mousedown', startDrag);
    stage.addEventListener('mousemove', moveDrag);
    window.addEventListener('mouseup', endDrag);
  }

  function open(target, file) {
    if (!file) return;
    ensureModal();
    state.target = target;
    const reader = new FileReader();
    reader.onload = () => {
      const img = byId('regionSelectorImage');
      img.onload = () => {
        state.naturalWidth = img.naturalWidth;
        state.naturalHeight = img.naturalHeight;
        byId('regionSelectorImageInfo').textContent = `${img.naturalWidth} × ${img.naturalHeight}px`;
        byId('regionSelectorTitle').textContent = target === 'battle' ? 'Seleccionar región Battle' : 'Seleccionar región del mapa';
        clearSelection();
        byId('regionSelectorModal').classList.remove('hidden');
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  }

  function close() {
    const modal = byId('regionSelectorModal');
    if (modal) modal.classList.add('hidden');
    state.dragging = false;
  }

  function clearSelection() {
    state.current = null;
    const box = byId('regionSelectorBox');
    if (box) box.classList.add('hidden');
    const coords = byId('regionSelectorCoords');
    if (coords) coords.textContent = 'Sin selección';
    const use = byId('regionSelectorUse');
    if (use) use.disabled = true;
  }

  function imageMetrics() {
    const img = byId('regionSelectorImage');
    const rect = img.getBoundingClientRect();
    return {
      rect,
      scaleX: state.naturalWidth / rect.width,
      scaleY: state.naturalHeight / rect.height,
    };
  }

  function pointFromEvent(e) {
    const { rect } = imageMetrics();
    return {
      x: Math.max(0, Math.min(rect.width, e.clientX - rect.left)),
      y: Math.max(0, Math.min(rect.height, e.clientY - rect.top)),
    };
  }

  function startDrag(e) {
    if (e.button !== 0 || e.target.id !== 'regionSelectorImage' && e.target.id !== 'regionSelectorBox') return;
    e.preventDefault();
    const p = pointFromEvent(e);
    state.startX = p.x;
    state.startY = p.y;
    state.dragging = true;
    state.current = { x: p.x, y: p.y, width: 0, height: 0 };
    renderBox();
  }

  function moveDrag(e) {
    if (!state.dragging) return;
    const p = pointFromEvent(e);
    const x = Math.min(state.startX, p.x);
    const y = Math.min(state.startY, p.y);
    const width = Math.abs(p.x - state.startX);
    const height = Math.abs(p.y - state.startY);
    state.current = { x, y, width, height };
    renderBox();
  }

  function endDrag() {
    if (!state.dragging) return;
    state.dragging = false;
    if (!state.current || state.current.width < 2 || state.current.height < 2) {
      clearSelection();
      return;
    }
    renderBox();
  }

  function renderBox() {
    const current = state.current;
    if (!current) return;
    const img = byId('regionSelectorImage');
    const stage = byId('regionSelectorStage');
    const box = byId('regionSelectorBox');
    const imgRect = img.getBoundingClientRect();
    const stageRect = stage.getBoundingClientRect();
    box.style.left = `${imgRect.left - stageRect.left + current.x}px`;
    box.style.top = `${imgRect.top - stageRect.top + current.y}px`;
    box.style.width = `${current.width}px`;
    box.style.height = `${current.height}px`;
    box.classList.remove('hidden');

    const { scaleX, scaleY } = imageMetrics();
    const region = {
      x: Math.round(current.x * scaleX),
      y: Math.round(current.y * scaleY),
      width: Math.max(1, Math.round(current.width * scaleX)),
      height: Math.max(1, Math.round(current.height * scaleY)),
    };
    byId('regionSelectorCoords').textContent = `X ${region.x} · Y ${region.y} · ${region.width} × ${region.height}`;
    byId('regionSelectorUse').disabled = false;
  }

  function applySelection() {
    if (!state.current) return;
    const { scaleX, scaleY } = imageMetrics();
    const region = {
      x: Math.round(state.current.x * scaleX),
      y: Math.round(state.current.y * scaleY),
      width: Math.max(1, Math.round(state.current.width * scaleX)),
      height: Math.max(1, Math.round(state.current.height * scaleY)),
    };

    const prefix = state.target === 'battle' ? 'settingsBattle' : 'settingsMap';
    byId(`${prefix}X`).value = region.x;
    byId(`${prefix}Y`).value = region.y;
    byId(`${prefix}Width`).value = region.width;
    byId(`${prefix}Height`).value = region.height;

    const status = byId('settingsStatus');
    if (status) status.textContent = `${state.target === 'battle' ? 'Región Battle' : 'Región mapa'} seleccionada: x=${region.x}, y=${region.y}, ${region.width}×${region.height}. Pulsa Guardar configuración.`;
    close();
  }

  window.RegionSelector = { open };
})();
