(() => {
  const byId = id => document.getElementById(id);
  const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

  const ACTION_LABELS = {
    left_click: 'Click izquierdo',
    move_mouse: 'Mover mouse',
    write: 'Escribir texto',
  };

  let createActions = [];
  let editActions = [];
  let battleReferences = [];
  let imagePickerCallback = null;
  let imagePickerMode = 'point';
  let imagePickerImage = null;
  let imagePickerStart = null;
  let imagePickerSelection = null;

  function currentEvents() { return window.events || events || []; }
  function currentRoutines() { return window.routines || routines || []; }

  async function loadBattleReferences() {
    try {
      const data = await fetch('/api/battle/targets').then(r => r.json());
      battleReferences = data.ok ? (data.targets || []) : [];
    } catch (_) {
      battleReferences = [];
    }
  }

  function triggerMarkup(prefix, trigger = {}) {
    const type = trigger.type === 'battle_reference' ? 'battle_reference' : 'detect_text';
    const region = trigger.region || {};
    const referenceOptions = battleReferences.map(t => `<option value="${esc(t.id)}" ${String(t.id) === String(trigger.reference_id || '') ? 'selected' : ''}>${esc(t.name || t.id)}</option>`).join('');
    return `
      <div class="grid cols-2">
        <label>Gatillo<select id="${prefix}TriggerType">
          <option value="detect_text" ${type === 'detect_text' ? 'selected' : ''}>Detectar texto en pantalla</option>
          <option value="battle_reference" ${type === 'battle_reference' ? 'selected' : ''}>Referencia Battle</option>
        </select></label>
        <label id="${prefix}BattleRefLabel" class="${type === 'battle_reference' ? '' : 'hidden'}">Referencia Battle
          <select id="${prefix}BattleReference"><option value="">Seleccionar…</option>${referenceOptions}</select>
        </label>
      </div>
      <div id="${prefix}DetectTextFields" class="${type === 'detect_text' ? '' : 'hidden'}">
        <label>Texto a detectar<input id="${prefix}DetectText" value="${esc(trigger.text || '')}"></label>
        <div class="grid cols-4">
          <label>X<input id="${prefix}TriggerX" type="number" value="${Number(region.x ?? 0)}"></label>
          <label>Y<input id="${prefix}TriggerY" type="number" value="${Number(region.y ?? 0)}"></label>
          <label>Ancho<input id="${prefix}TriggerWidth" type="number" min="1" value="${Number(region.width ?? 1)}"></label>
          <label>Alto<input id="${prefix}TriggerHeight" type="number" min="1" value="${Number(region.height ?? 1)}"></label>
        </div>
        <div class="action-row compact">
          <button type="button" class="secondary pick-trigger-image" data-prefix="${prefix}">Seleccionar región en imagen</button>
          <button type="button" class="secondary capture-trigger-f12" data-prefix="${prefix}">Capturar región con F12 ×4</button>
        </div>
        <p id="${prefix}TriggerStatus" class="muted small"></p>
      </div>`;
  }

  function renderActions(containerId, mode) {
    const actions = mode === 'create' ? createActions : editActions;
    const root = byId(containerId);
    if (!root) return;
    root.innerHTML = actions.map((a, i) => {
      const type = a.type || 'move_mouse';
      let fields = '';
      if (type === 'left_click' || type === 'move_mouse') {
        fields = `<div class="grid cols-2">
          <label>X<input class="action-x" type="number" value="${Number(a.x ?? 0)}"></label>
          <label>Y<input class="action-y" type="number" value="${Number(a.y ?? 0)}"></label>
        </div>
        <div class="action-row compact">
          <button type="button" class="secondary pick-action-image" data-mode="${mode}" data-index="${i}">Seleccionar coordenada en imagen</button>
          <button type="button" class="secondary capture-action-f12" data-mode="${mode}" data-index="${i}">Esperar F12</button>
        </div>`;
      } else if (type === 'write') {
        fields = `<label>Texto<textarea class="action-text" rows="2">${esc(a.text || '')}</textarea></label>`;
      }
      return `<div class="panel" data-action-index="${i}" style="padding:12px">
        <div class="panel-title-row">
          <label class="grow">Acción<select class="action-type" data-mode="${mode}" data-index="${i}">
            <option value="left_click" ${type === 'left_click' ? 'selected' : ''}>Click izquierdo</option>
            <option value="move_mouse" ${type === 'move_mouse' ? 'selected' : ''}>Mover mouse</option>
            <option value="write" ${type === 'write' ? 'selected' : ''}>Escribir texto</option>
          </select></label>
          <button type="button" class="danger remove-action" data-mode="${mode}" data-index="${i}">Quitar</button>
        </div>
        ${fields}
        <p class="action-capture-status muted small"></p>
      </div>`;
    }).join('') + `<button type="button" class="secondary add-action" data-mode="${mode}">+ Agregar acción</button>`;
  }

  function readActions(containerId, mode) {
    const root = byId(containerId);
    const result = [];
    root.querySelectorAll('[data-action-index]').forEach(row => {
      const type = row.querySelector('.action-type').value;
      if (type === 'left_click' || type === 'move_mouse') {
        result.push({type, x:Number(row.querySelector('.action-x').value), y:Number(row.querySelector('.action-y').value)});
      } else {
        result.push({type, text:row.querySelector('.action-text').value});
      }
    });
    if (mode === 'create') createActions = result; else editActions = result;
    return result;
  }

  function readTrigger(prefix) {
    const type = byId(`${prefix}TriggerType`).value;
    if (type === 'battle_reference') {
      return {type, reference_id: byId(`${prefix}BattleReference`).value};
    }
    return {
      type: 'detect_text',
      text: byId(`${prefix}DetectText`).value.trim(),
      region: {
        x:Number(byId(`${prefix}TriggerX`).value), y:Number(byId(`${prefix}TriggerY`).value),
        width:Number(byId(`${prefix}TriggerWidth`).value), height:Number(byId(`${prefix}TriggerHeight`).value),
      },
    };
  }

  function bindTriggerToggle(prefix) {
    byId(`${prefix}TriggerType`).onchange = () => {
      const battle = byId(`${prefix}TriggerType`).value === 'battle_reference';
      byId(`${prefix}BattleRefLabel`).classList.toggle('hidden', !battle);
      byId(`${prefix}DetectTextFields`).classList.toggle('hidden', battle);
    };
  }

  function describeEvent(e) {
    const trigger = e.trigger || {};
    const triggerText = trigger.type === 'battle_reference'
      ? `Battle: ${trigger.reference_id || 'sin referencia'}`
      : `Texto “${String(trigger.text || '').slice(0, 35)}” · ${trigger.region?.width || 1}×${trigger.region?.height || 1}`;
    const actions = (e.actions || []).map(a => ACTION_LABELS[a.type] || a.type).join(' → ') || 'sin acciones';
    return `${triggerText} · acciones: ${actions}`;
  }

  window.renderEvents = function renderEventsNew() {
    const root = byId('eventCards');
    if (!root) return;
    const list = currentEvents();
    root.innerHTML = list.map(e => `<article class="library-card">
      <div class="card-main"><div class="card-icon event">E</div><div><h3>${esc(e.name)}</h3><p>${esc(describeEvent(e))}</p></div></div>
      <button class="secondary edit-event-btn" data-id="${esc(e.id)}">Editar</button>
    </article>`).join('') || '<p class="empty">Sin eventos configurados.</p>';
  };

  function installCreateForm() {
    const form = byId('eventForm');
    if (!form) return;
    form.innerHTML = `
      <label>Nombre<input id="eventName" required></label>
      <div class="region-tools"><div><strong>Gatillo</strong><p class="muted small">Un evento nace cuando el análisis de una zona de pantalla o una referencia Battle coincide.</p></div></div>
      <div id="createTrigger"></div>
      <div class="region-tools"><div><strong>Acciones</strong><p class="muted small">Define qué acciones forman el evento. Puedes repetir tipos y mantener el orden.</p></div></div>
      <div id="createActions"></div>
      <button type="submit">Crear evento</button>`;
    byId('createTrigger').innerHTML = triggerMarkup('event', {type:'detect_text', region:{x:0,y:0,width:1,height:1}});
    createActions = [];
    renderActions('createActions', 'create');
    bindTriggerToggle('event');

    form.onsubmit = async ev => {
      ev.preventDefault();
      const payload = {
        name: byId('eventName').value.trim(),
        trigger: readTrigger('event'),
        actions: readActions('createActions', 'create'),
      };
      const data = await fetch('/api/events', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)}).then(r=>r.json());
      byId('eventStatus').textContent = data.ok ? 'Evento creado.' : data.error;
      if (data.ok) {
        events = data.events || [];
        window.events = events;
        window.renderEvents();
        form.reset();
        installCreateForm();
      }
    };
  }

  window.showEventEditor = function showEventEditorNew(e) {
    const panel = byId('eventEditorPanel');
    panel.innerHTML = `
      <div class="panel-title-row"><h2>Editar evento</h2><button id="closeEventEditorBtn" class="secondary">Cerrar</button></div>
      <input id="editEventId" type="hidden" value="${esc(e.id)}">
      <label>Nombre<input id="editEventName" value="${esc(e.name || '')}"></label>
      <div id="editTrigger"></div>
      <div class="region-tools"><div><strong>Acciones</strong></div></div>
      <div id="editActions"></div>
      <div class="action-row"><button id="saveEventBtn">Guardar</button><button id="deleteEventBtn" class="danger">Eliminar</button></div>
      <p id="eventEditorStatus" class="status"></p>`;
    byId('editTrigger').innerHTML = triggerMarkup('editEvent', e.trigger || {});
    editActions = [...(e.actions || [])];
    renderActions('editActions', 'edit');
    bindTriggerToggle('editEvent');
    panel.classList.remove('hidden');
    byId('closeEventEditorBtn').onclick = () => panel.classList.add('hidden');
    byId('saveEventBtn').onclick = async () => {
      const id = byId('editEventId').value;
      const payload = {name:byId('editEventName').value.trim(), trigger:readTrigger('editEvent'), actions:readActions('editActions','edit')};
      const data = await fetch(`/api/events/${encodeURIComponent(id)}`, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)}).then(r=>r.json());
      byId('eventEditorStatus').textContent = data.ok ? 'Evento guardado.' : data.error;
      if (data.ok) { events = data.events || []; window.events = events; window.renderEvents(); }
    };
    byId('deleteEventBtn').onclick = async () => {
      const id = byId('editEventId').value;
      const data = await fetch(`/api/events/${encodeURIComponent(id)}`, {method:'DELETE'}).then(r=>r.json());
      if (data.ok) { events = data.events || []; window.events = events; window.renderEvents(); panel.classList.add('hidden'); }
    };
  };

  function ensureImagePicker() {
    if (byId('eventImagePickerModal')) return;
    document.body.insertAdjacentHTML('beforeend', `
      <input id="eventImagePickerInput" type="file" accept="image/*" class="hidden">
      <div id="eventImagePickerModal" class="region-modal hidden" role="dialog" aria-modal="true">
        <div class="region-modal-card">
          <div class="panel-title-row"><div><span class="badge">COORDENADAS</span><h2>Seleccionar en imagen</h2><p id="eventImagePickerHelp" class="muted small"></p></div><button id="closeEventImagePicker" class="secondary">Cerrar</button></div>
          <div class="region-canvas-wrap"><canvas id="eventImagePickerCanvas"></canvas></div>
          <div class="region-selection-footer"><span id="eventImagePickerResult" class="muted">Sin selección</span><button id="applyEventImagePicker" class="primary" disabled>Usar selección</button></div>
        </div>
      </div>`);
    const input = byId('eventImagePickerInput');
    const canvas = byId('eventImagePickerCanvas');
    const ctx = canvas.getContext('2d');
    input.onchange = e => {
      const file = e.target.files?.[0]; if (!file) return;
      const reader = new FileReader();
      reader.onload = () => { const img = new Image(); img.onload = () => { imagePickerImage=img; canvas.width=img.naturalWidth; canvas.height=img.naturalHeight; imagePickerSelection=null; ctx.drawImage(img,0,0); byId('eventImagePickerModal').classList.remove('hidden'); byId('eventImagePickerHelp').textContent=imagePickerMode==='point'?'Haz clic sobre la coordenada.':'Arrastra para marcar la región.'; }; img.src=reader.result; };
      reader.readAsDataURL(file);
    };
    const point = ev => { const r=canvas.getBoundingClientRect(); return {x:Math.round((ev.clientX-r.left)*canvas.width/r.width), y:Math.round((ev.clientY-r.top)*canvas.height/r.height)}; };
    const redraw = () => { if(!imagePickerImage)return;ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(imagePickerImage,0,0);if(!imagePickerSelection)return;ctx.save();ctx.strokeStyle='#38bdf8';ctx.lineWidth=Math.max(2,canvas.width/900);if(imagePickerMode==='point'){ctx.beginPath();ctx.arc(imagePickerSelection.x,imagePickerSelection.y,8,0,Math.PI*2);ctx.stroke();}else{ctx.strokeRect(imagePickerSelection.x,imagePickerSelection.y,imagePickerSelection.width,imagePickerSelection.height);}ctx.restore(); };
    canvas.onpointerdown = ev => { const p=point(ev); if(imagePickerMode==='point'){imagePickerSelection=p;byId('eventImagePickerResult').textContent=`x=${p.x}, y=${p.y}`;byId('applyEventImagePicker').disabled=false;redraw();return;} imagePickerStart=p; };
    canvas.onpointerup = ev => { if(imagePickerMode!=='region'||!imagePickerStart)return;const p=point(ev);imagePickerSelection={x:Math.min(p.x,imagePickerStart.x),y:Math.min(p.y,imagePickerStart.y),width:Math.max(1,Math.abs(p.x-imagePickerStart.x)),height:Math.max(1,Math.abs(p.y-imagePickerStart.y))};imagePickerStart=null;byId('eventImagePickerResult').textContent=`x=${imagePickerSelection.x}, y=${imagePickerSelection.y}, ${imagePickerSelection.width}×${imagePickerSelection.height}`;byId('applyEventImagePicker').disabled=false;redraw(); };
    byId('applyEventImagePicker').onclick = () => { if(imagePickerCallback&&imagePickerSelection)imagePickerCallback(imagePickerSelection);byId('eventImagePickerModal').classList.add('hidden'); };
    byId('closeEventImagePicker').onclick = () => byId('eventImagePickerModal').classList.add('hidden');
  }

  function openImagePicker(mode, callback) {
    ensureImagePicker(); imagePickerMode=mode; imagePickerCallback=callback; imagePickerSelection=null; byId('eventImagePickerInput').value=''; byId('eventImagePickerInput').click();
  }

  async function capturePointWithF12(row) {
    const status=row.querySelector('.action-capture-status'); status.textContent='Posiciona el mouse y presiona F12…';
    const data=await fetch('/api/events/capture-point',{method:'POST'}).then(r=>r.json());
    if(!data.ok){status.textContent=data.error;return;} row.querySelector('.action-x').value=data.point.x;row.querySelector('.action-y').value=data.point.y;status.textContent=`Capturado (${data.point.x}, ${data.point.y}).`;
  }

  document.addEventListener('click', async e => {
    const add=e.target.closest('.add-action');
    if(add){const arr=add.dataset.mode==='create'?createActions:editActions;arr.push({type:'move_mouse',x:0,y:0});renderActions(add.dataset.mode==='create'?'createActions':'editActions',add.dataset.mode);return;}
    const remove=e.target.closest('.remove-action');
    if(remove){const arr=remove.dataset.mode==='create'?createActions:editActions;arr.splice(Number(remove.dataset.index),1);renderActions(remove.dataset.mode==='create'?'createActions':'editActions',remove.dataset.mode);return;}
    const pickAction=e.target.closest('.pick-action-image');
    if(pickAction){const row=pickAction.closest('[data-action-index]');openImagePicker('point',p=>{row.querySelector('.action-x').value=p.x;row.querySelector('.action-y').value=p.y;});return;}
    const f12Action=e.target.closest('.capture-action-f12');
    if(f12Action){capturePointWithF12(f12Action.closest('[data-action-index]'));return;}
    const pickTrigger=e.target.closest('.pick-trigger-image');
    if(pickTrigger){const p=pickTrigger.dataset.prefix;openImagePicker('region',r=>{byId(`${p}TriggerX`).value=r.x;byId(`${p}TriggerY`).value=r.y;byId(`${p}TriggerWidth`).value=r.width;byId(`${p}TriggerHeight`).value=r.height;});return;}
    const f12Trigger=e.target.closest('.capture-trigger-f12');
    if(f12Trigger){const p=f12Trigger.dataset.prefix;const status=byId(`${p}TriggerStatus`);status.textContent='Presiona F12 4 veces: X, Y, borde derecho (ancho), borde inferior (alto)…';const data=await fetch('/api/events/capture-region',{method:'POST'}).then(r=>r.json());if(!data.ok){status.textContent=data.error;return;}const r=data.region;byId(`${p}TriggerX`).value=r.x;byId(`${p}TriggerY`).value=r.y;byId(`${p}TriggerWidth`).value=r.width;byId(`${p}TriggerHeight`).value=r.height;status.textContent=`Región capturada: x=${r.x}, y=${r.y}, ${r.width}×${r.height}.`;return;}
  });

  document.addEventListener('change', e => {
    const type=e.target.closest('.action-type'); if(!type)return;
    const arr=type.dataset.mode==='create'?createActions:editActions;const i=Number(type.dataset.index);const old=arr[i]||{};arr[i]=type.value==='write'?{type:'write',text:old.text||''}:{type:type.value,x:Number(old.x||0),y:Number(old.y||0)};renderActions(type.dataset.mode==='create'?'createActions':'editActions',type.dataset.mode);
  });

  let executionRoutine = null;
  function findRoutineByName(name){const target=String(name||'').trim().toLowerCase();return currentRoutines().find(r=>String(r.name||'').trim().toLowerCase()===target)||null;}
  function ensureRoutineEventPanel(){
    if(byId('routineEventConfigPanel'))return;const runPanel=byId('startRoutineBtn')?.closest('.hero-panel');if(!runPanel)return;const panel=document.createElement('div');panel.id='routineEventConfigPanel';panel.className='info-box hidden';panel.innerHTML=`<div class="panel-title-row"><div><strong>Eventos de esta rutina</strong><p class="muted small">La selección se guarda en la rutina.</p></div><button id="toggleDetectedBtn" class="secondary">Detected: OFF</button></div><div id="routineEventList" class="stack"></div><div class="action-row compact"><button id="runRoutineConfirmedBtn" class="primary">Comenzar rutina</button><button id="cancelRoutineEventConfigBtn" class="secondary">Cancelar</button></div><p id="routineEventConfigStatus" class="status"></p>`;runPanel.appendChild(panel);
    byId('toggleDetectedBtn').onclick=async()=>{if(!executionRoutine)return;const cfg=executionRoutine.event_config||{detected_enabled:false,enabled_event_ids:[]};cfg.detected_enabled=!cfg.detected_enabled;executionRoutine.event_config=cfg;renderRoutineEventConfig();await saveRoutineEventConfig();};
    byId('cancelRoutineEventConfigBtn').onclick=()=>{executionRoutine=null;panel.classList.add('hidden');byId('startRoutineBtn').disabled=false;};
    byId('runRoutineConfirmedBtn').onclick=runConfiguredRoutine;
  }
  function renderRoutineEventConfig(){if(!executionRoutine)return;const cfg=executionRoutine.event_config||{detected_enabled:false,enabled_event_ids:[]},selected=new Set(cfg.enabled_event_ids||[]);byId('toggleDetectedBtn').textContent=`Detected: ${cfg.detected_enabled?'ON':'OFF'}`;byId('routineEventList').innerHTML=currentEvents().map(e=>`<label class="library-card"><div class="card-main"><input class="routine-event-check" type="checkbox" value="${esc(e.id)}" ${selected.has(String(e.id))?'checked':''} style="width:auto"><div><strong>${esc(e.name)}</strong><p>${esc(describeEvent(e))}</p></div></div></label>`).join('')||'<p class="muted">No hay eventos.</p>';byId('routineEventList').querySelectorAll('.routine-event-check').forEach(input=>input.onchange=async()=>{executionRoutine.event_config={detected_enabled:!!executionRoutine.event_config?.detected_enabled,enabled_event_ids:[...byId('routineEventList').querySelectorAll('.routine-event-check:checked')].map(x=>x.value)};await saveRoutineEventConfig();});}
  async function saveRoutineEventConfig(){if(!executionRoutine)return;const data=await fetch(`/api/routines/${encodeURIComponent(executionRoutine.id)}/event-config`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(executionRoutine.event_config||{})}).then(r=>r.json());if(data.ok){executionRoutine=data.routine;routines=data.routines||routines;window.routines=routines;byId('routineEventConfigStatus').textContent='Configuración guardada.';}else byId('routineEventConfigStatus').textContent=data.error;}
  async function openRoutineEventConfig(){const name=byId('routineNameInput').value.trim();let routine=findRoutineByName(name);if(!routine){const s=await fetch('/api/status').then(r=>r.json());routines=s.routines||routines;events=s.events||events;window.routines=routines;window.events=events;routine=findRoutineByName(name);}if(!routine){byId('runStatus').textContent='No existe una rutina con ese nombre.';return;}const data=await fetch(`/api/routines/${encodeURIComponent(routine.id)}`).then(r=>r.json());if(!data.ok){byId('runStatus').textContent=data.error;return;}executionRoutine=data.routine;ensureRoutineEventPanel();byId('routineEventConfigPanel').classList.remove('hidden');byId('startRoutineBtn').disabled=true;renderRoutineEventConfig();}
  async function runConfiguredRoutine(){if(!executionRoutine)return;const btn=byId('runRoutineConfirmedBtn');btn.disabled=true;try{const d=await fetch('/api/routines/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:executionRoutine.name})}).then(r=>r.json());byId('runStatus').textContent=d.message||d.error||'';}finally{btn.disabled=false;byId('startRoutineBtn').disabled=false;byId('routineEventConfigPanel').classList.add('hidden');executionRoutine=null;}}

  (async()=>{await loadBattleReferences();installCreateForm();window.renderEvents();ensureRoutineEventPanel();if(byId('startRoutineBtn'))byId('startRoutineBtn').onclick=openRoutineEventConfig;})();
})();
