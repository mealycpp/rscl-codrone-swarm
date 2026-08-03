const DEFAULT_PALETTE = ['#ff2aa1','#28d7ff','#69ff9a','#ffbd3f','#b785ff','#ff5050','#7efff5','#f8ef42'];

const state = {
  drones: {},
  events: [],
  simulate: true,
  autoDetect: false,
  mission: {active:false,name:'IDLE',step_index:0,total_steps:0,status:'READY'},
  customSteps: [],
  selectedPreset: 'split_merge',
  palette: loadStored('rsclDronePaletteV051', DEFAULT_PALETTE),
  droneColors: {},
  droneMapSignature: ''
};

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const fmt = (value, digits=1) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '--';
const esc = value => String(value ?? '').replace(/[&<>'"]/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));

function loadStored(key, fallback) {
  try {
    const value = JSON.parse(localStorage.getItem(key));
    return value && typeof value === 'object' ? value : structuredClone(fallback);
  } catch (_) {
    return structuredClone(fallback);
  }
}

function saveStored(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

function metric(label, value) {
  return `<div class="metric"><label>${esc(label)}</label><strong>${esc(value)}</strong></div>`;
}

function renderDrone(drone) {
  const status = !drone.present ? 'DETACHED' : (drone.connected ? 'LINKED' : 'OFFLINE');
  const statusClass = !drone.present ? 'detached' : (drone.connected ? 'linked' : 'offline');
  return `<article class="drone-card ${statusClass}" style="--accent:${esc(drone.accent)};--led:${esc(drone.led_color || '#000000')}">
    <div class="drone-head">
      <div><div class="drone-name">${esc(drone.drone_id)} · ${esc(drone.role)}</div><small>${esc(drone.port)} · ${esc(drone.device_label || '')}</small></div>
      <span class="connection">${status}</span>
    </div>
    <div class="led-orb" title="Drone LED: ${esc(drone.led_mode)}"></div>
    <div class="metric-grid">
      ${metric('BATTERY', `${fmt(drone.battery,0)}%`)}
      ${metric('FLIGHT', drone.flight_state)}
      ${metric('HEIGHT', `${fmt(drone.bottom_height_m,2)} m`)}
      ${metric('ROLL', `${fmt(drone.roll)}°`)}
      ${metric('PITCH', `${fmt(drone.pitch)}°`)}
      ${metric('YAW', `${fmt(drone.yaw)}°`)}
      ${metric('FRONT RANGE', `${fmt(drone.front_range_mm,0)} mm`)}
      ${metric('TEMP', `${fmt(drone.temperature_c)} °C`)}
      ${metric('PRESSURE', `${fmt(drone.pressure_pa,0)} Pa`)}
      ${metric('LOCAL XYZ', `${fmt(drone.x_m,2)}, ${fmt(drone.y_m,2)}, ${fmt(drone.z_m,2)}`)}
      ${metric('POS QUALITY', drone.position_quality || 'UNKNOWN')}
      ${metric('SPEED', `${fmt(drone.speed,2)} (${drone.speed_source || 'UNKNOWN'})`)}
      ${metric('LED', `${drone.led_mode || 'SOLID'} ${drone.led_color || ''}`)}
      ${metric('LAST CMD', drone.last_command)}
      ${metric('ACCEL XYZ', `${fmt(drone.acceleration_x,2)} ${fmt(drone.acceleration_y,2)} ${fmt(drone.acceleration_z,2)}`)}
      ${metric('GYRO RPY', `${fmt(drone.gyro_roll)} ${fmt(drone.gyro_pitch)} ${fmt(drone.gyro_yaw)}`)}
      ${metric('MOVEMENT', drone.movement_state || 'UNKNOWN')}
      ${metric('ERROR', drone.error_state || 'NONE')}
    </div>
  </article>`;
}

function sortedDrones() {
  return Object.values(state.drones).sort((a,b) => Number(a.drone_id.slice(1)) - Number(b.drone_id.slice(1)));
}

function syncTargetSelect(select, drones) {
  const current = select.value;
  select.innerHTML = '<option>ALL</option>' + drones.map(drone => `<option>${esc(drone.drone_id)}</option>`).join('');
  if ([...select.options].some(option => option.value === current)) select.value = current;
}

function renderMission() {
  const mission = state.mission || {};
  const total = Number(mission.total_steps || 0);
  const step = Number(mission.step_index || 0);
  const percent = total ? Math.min(100, Math.round((step / total) * 100)) : 0;
  $('#missionState').textContent = mission.active ? `${mission.name} ACTIVE` : (mission.status || 'READY');
  $('#missionState').classList.toggle('active', Boolean(mission.active));
  $('#missionProgress').style.width = `${percent}%`;
  $('#missionReadout').textContent = mission.active
    ? `${mission.name} · ${mission.target} · step ${step}/${total} · ${mission.status}`
    : `${mission.name || 'MISSION'} · ${mission.status || 'READY'}`;
}

function renderTimeline() {
  if (!state.customSteps.length) {
    $('#timeline').innerHTML = '<div class="empty-timeline">Build a custom mission one step at a time.</div>';
    return;
  }
  $('#timeline').innerHTML = state.customSteps.map((step, index) => `
    <div class="timeline-step">
      <span class="step-index">${String(index + 1).padStart(2, '0')}</span>
      <span class="step-action">${esc(step.label)}</span>
      <code>${esc(JSON.stringify(step.params))}</code>
      <button data-remove-step="${index}" title="Remove step">×</button>
    </div>`).join('');
  $$('[data-remove-step]').forEach(button => {
    button.addEventListener('click', () => {
      state.customSteps.splice(Number(button.dataset.removeStep), 1);
      renderTimeline();
    });
  });
}

function renderLocalPosition(drones) {
  $$('.blip, .radar-meta, .radar-warning, .radar-unknown').forEach(element => element.remove());
  const positioned = drones.filter(drone =>
    drone.present && drone.connected && drone.position_valid &&
    Number.isFinite(Number(drone.x_m)) && Number.isFinite(Number(drone.y_m))
  );
  const unknown = drones.filter(drone => drone.present && (!drone.connected || !drone.position_valid));
  const maximum = positioned.reduce((value, drone) => Math.max(
    value, Math.abs(Number(drone.x_m)), Math.abs(Number(drone.y_m))
  ), 0);
  const scaleMeters = Math.max(1.0, Math.ceil((maximum * 1.18) / 0.5) * 0.5);
  const radius = 42;
  const plotted = [];

  positioned.forEach((drone, index) => {
    const forwardX = Number(drone.x_m);
    const leftY = Number(drone.y_m);
    const screenLeft = 50 - (leftY / scaleMeters) * radius;
    const screenTop = 50 - (forwardX / scaleMeters) * radius;
    const overlapDepth = plotted.filter(point => Math.hypot(point.x-forwardX, point.y-leftY) < 0.07).length;
    plotted.push({x:forwardX,y:leftY});

    const blip = document.createElement('div');
    blip.className = `blip online ${overlapDepth ? 'coincident' : ''}`;
    blip.style.left = `${screenLeft}%`;
    blip.style.top = `${screenTop}%`;
    blip.style.color = drone.led_color || drone.accent;
    blip.style.background = overlapDepth ? 'transparent' : (drone.led_color || drone.accent);
    blip.style.width = `${15 + overlapDepth * 7}px`;
    blip.style.height = `${15 + overlapDepth * 7}px`;
    blip.style.border = overlapDepth ? `2px solid ${drone.led_color || drone.accent}` : 'none';
    blip.style.zIndex = String(20 + overlapDepth);
    blip.title = `${drone.drone_id}: local X=${forwardX.toFixed(2)} m, Y=${leftY.toFixed(2)} m`;

    const angle = index * 2.3999632297;
    const labelDistance = 20 + overlapDepth * 13;
    blip.innerHTML = `<span style="left:${Math.cos(angle)*labelDistance}px;top:${Math.sin(angle)*labelDistance}px">${esc(drone.drone_id)} X:${fmt(drone.x_m,2)} Y:${fmt(drone.y_m,2)}</span>`;
    $('#radar').appendChild(blip);
  });

  const meta = document.createElement('div');
  meta.className = 'radar-meta';
  meta.textContent = `REPORTED LOCAL XY · ±${scaleMeters.toFixed(1)} m · UP=+X FORWARD · LEFT=+Y`;
  $('#radar').appendChild(meta);

  const warning = document.createElement('div');
  warning.className = 'radar-warning';
  warning.textContent = 'PER-DRONE OPTICAL-FLOW FRAMES · NOT GLOBAL POSITION · NOT COLLISION AVOIDANCE';
  $('#radar').appendChild(warning);

  if (unknown.length) {
    const unavailable = document.createElement('div');
    unavailable.className = 'radar-unknown';
    unavailable.textContent = `POSITION UNAVAILABLE: ${unknown.map(drone => drone.drone_id).join(', ')}`;
    $('#radar').appendChild(unavailable);
  }
}

function renderDroneColorMap(drones) {
  const signature = drones.map(drone => drone.drone_id).join('|');
  if (signature === state.droneMapSignature) return;
  state.droneMapSignature = signature;
  drones.forEach((drone, index) => {
    if (!state.droneColors[drone.drone_id]) state.droneColors[drone.drone_id] = state.palette[index % state.palette.length];
  });
  $('#droneColorMap').innerHTML = drones.map(drone => `
    <label class="drone-color-row">${esc(drone.drone_id)} · ${esc(drone.role)}
      <input type="color" data-drone-color="${esc(drone.drone_id)}" value="${esc(state.droneColors[drone.drone_id])}" />
    </label>`).join('') || '<span class="subhead">No drones registered.</span>';
  $$('[data-drone-color]').forEach(input => input.addEventListener('input', () => {
    state.droneColors[input.dataset.droneColor] = input.value;
  }));
}

function render() {
  const drones = sortedDrones();
  $('#modeBadge').textContent = state.simulate ? 'SIMULATION' : 'LIVE HARDWARE';
  $('#autoBadge').textContent = state.autoDetect ? 'AUTO-DETECT ACTIVE' : 'STATIC FLEET';
  const linkedCount = drones.filter(drone => drone.connected).length;
  $('#linkBadge').textContent = linkedCount ? `FLEET LINKED ${linkedCount}/${drones.filter(drone=>drone.present).length}` : 'AWAITING LINK';
  $('#linkBadge').classList.toggle('dim', !linkedCount);
  $('#droneCards').innerHTML = drones.map(renderDrone).join('') || '<p>No controllers discovered. Auto-detect is watching.</p>';
  const present = drones.filter(drone => drone.present).length;
  const airborne = drones.filter(drone => ['AIRBORNE','HOVER'].includes(drone.flight_state)).length;
  $('#fleetSummary').textContent = `${drones.length} REGISTERED · ${present} PRESENT · ${linkedCount} LINKED · ${airborne} AIRBORNE`;
  syncTargetSelect($('#targetSelect'), drones);
  syncTargetSelect($('#missionTarget'), drones);
  syncTargetSelect($('#lightTarget'), drones);
  renderDroneColorMap(drones);
  renderLocalPosition(drones);
  $('#events').innerHTML = state.events.slice(-120).reverse().map(event => `
    <div class="event level-${esc((event.level || '').toLowerCase())}">
      <span>${esc((event.timestamp || '').slice(11,23))}</span>
      <span class="level">${esc(event.level)}</span>
      <span>${esc(event.message)}</span>
    </div>`).join('');
  renderMission();
}

async function post(path, body={}) {
  const response = await fetch(path, {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
  });
  if (!response.ok) {
    let message = await response.text();
    try { message = JSON.parse(message).detail || message; } catch (_) {}
    throw new Error(message);
  }
  return response.json();
}

function hexToRgb(hex) {
  const clean = String(hex).replace('#','');
  return {red:parseInt(clean.slice(0,2),16),green:parseInt(clean.slice(2,4),16),blue:parseInt(clean.slice(4,6),16)};
}

function hslToHex(h, s, l) {
  s /= 100; l /= 100;
  const c = (1 - Math.abs(2*l - 1)) * s;
  const x = c * (1 - Math.abs((h/60)%2 - 1));
  const m = l - c/2;
  let r=0,g=0,b=0;
  if (h < 60) [r,g,b]=[c,x,0]; else if (h < 120) [r,g,b]=[x,c,0];
  else if (h < 180) [r,g,b]=[0,c,x]; else if (h < 240) [r,g,b]=[0,x,c];
  else if (h < 300) [r,g,b]=[x,0,c]; else [r,g,b]=[c,0,x];
  return `#${[r,g,b].map(value => Math.round((value+m)*255).toString(16).padStart(2,'0')).join('')}`;
}

function randomVividColor(offset=0) {
  return hslToHex((Math.random()*360 + offset)%360, 72 + Math.random()*22, 52 + Math.random()*12);
}

async function command(commandName, confirm=false, extraParams={}) {
  if (commandName === 'scan') {
    await post('/api/scan');
    return;
  }
  const params = {
    distance_cm:Number($('#distance').value),
    speed:Number($('#speed').value),
    degrees:Number($('#degrees').value),
    duration:2,
    ...extraParams
  };
  await post('/api/command', {target:$('#targetSelect').value,command:commandName,params,confirm});
}

$$('button[data-command]').forEach(button => button.addEventListener('click', () => command(button.dataset.command).catch(error => alert(error.message))));
$('#setLed').addEventListener('click', () => command('set_led', false, {...hexToRgb($('#quickColor').value),brightness:Number($('#quickBrightness').value)}).catch(error => alert(error.message)));
$('#ledOff').addEventListener('click', () => command('led_off').catch(error => alert(error.message)));

let holdTimer;
const emergency = $('#emergency');
const startHold = () => {
  emergency.classList.add('holding');
  holdTimer = setTimeout(() => command('emergency_stop', true).catch(error => alert(error.message)), 2000);
};
const cancelHold = () => { clearTimeout(holdTimer); emergency.classList.remove('holding'); };
emergency.addEventListener('mousedown', startHold); emergency.addEventListener('mouseup', cancelHold); emergency.addEventListener('mouseleave', cancelHold);
emergency.addEventListener('touchstart', event => {event.preventDefault();startHold();},{passive:false}); emergency.addEventListener('touchend', cancelHold);

function setLightState(message) {
  $('#lightState').textContent = message;
}

async function directPhysicalLed(commandName, color=$('#physicalColor').value) {
  const target = $('#lightTarget').value;
  const brightness = Number($('#physicalBrightness').value);
  const params = commandName === 'set_led' ? {...hexToRgb(color), brightness} : {};
  await post('/api/command', {target, command:commandName, params, confirm:false});
  setLightState(`${target} ${commandName === 'set_led' ? color.toUpperCase() + ' @ ' + brightness + '%' : 'LED OFF'}`);
}

function lightMissionParams() {
  return {
    min_battery: 0,
    auto_takeoff: false,
    auto_land: false,
    palette: state.palette,
    led_brightness: Number($('#physicalBrightness').value)
  };
}

async function runLightShow(kind) {
  const color = $('#physicalColor').value;
  const rgb = hexToRgb(color);
  const brightness = Number($('#physicalBrightness').value);
  const target = $('#lightTarget').value;
  const steps = [];

  if (kind === 'pulse') {
    const levels = [15, 35, 60, 85, 100, 85, 60, 35, 15];
    for (let cycle=0; cycle<2; cycle++) {
      levels.forEach(level => {
        steps.push({action:'set_led',params:{...rgb,brightness:Math.round(brightness*level/100)},label:`PHYSICAL LED PULSE ${level}%`});
        steps.push({action:'wait',params:{duration:0.10},label:'PULSE INTERVAL'});
      });
    }
  } else if (kind === 'strobe') {
    for (let cycle=0; cycle<8; cycle++) {
      steps.push({action:'set_led',params:{...rgb,brightness},label:'PHYSICAL LED STROBE ON'});
      steps.push({action:'wait',params:{duration:0.12},label:'STROBE ON INTERVAL'});
      steps.push({action:'led_off',params:{},label:'PHYSICAL LED STROBE OFF'});
      steps.push({action:'wait',params:{duration:0.12},label:'STROBE OFF INTERVAL'});
    }
  } else if (kind === 'chase' || kind === 'rainbow') {
    const cycles = kind === 'rainbow' ? 12 : 8;
    for (let index=0; index<cycles; index++) {
      steps.push({
        action:'color_wave',
        params:{palette:state.palette,palette_offset:index,stagger_ms:kind==='rainbow'?110:240,brightness},
        label:kind === 'rainbow' ? `PHYSICAL RAINBOW PHASE ${index+1}` : `PHYSICAL COLOR CHASE ${index+1}`
      });
      steps.push({action:'wait',params:{duration:kind==='rainbow'?0.10:0.18},label:'LIGHT PHASE HOLD'});
    }
  }

  await post('/api/mission/run', {target,name:`PHYSICAL LED ${kind.toUpperCase()}`,steps,params:lightMissionParams()});
  setLightState(`${kind.toUpperCase()} ACTIVE ON ${target}`);
}

$('#physicalBrightness').addEventListener('input', () => $('#brightnessReadout').textContent = `${$('#physicalBrightness').value}%`);
$('#applyPhysicalColor').addEventListener('click', () => directPhysicalLed('set_led').catch(error => alert(error.message)));
$('#physicalLedOff').addEventListener('click', () => directPhysicalLed('led_off').catch(error => alert(error.message)));
$$('[data-led-color]').forEach(button => button.addEventListener('click', () => {
  $('#physicalColor').value = button.dataset.ledColor;
  if (button.dataset.ledColor === '#000000') directPhysicalLed('led_off').catch(error => alert(error.message));
  else directPhysicalLed('set_led', button.dataset.ledColor).catch(error => alert(error.message));
}));
$('#runPulse').addEventListener('click', () => runLightShow('pulse').catch(error => alert(error.message)));
$('#runStrobe').addEventListener('click', () => runLightShow('strobe').catch(error => alert(error.message)));
$('#runColorChase').addEventListener('click', () => runLightShow('chase').catch(error => alert(error.message)));
$('#runRainbowSequence').addEventListener('click', () => runLightShow('rainbow').catch(error => alert(error.message)));
$('#abortLightShow').addEventListener('click', () => post('/api/mission/abort').then(()=>setLightState('STOP REQUESTED')).catch(error => alert(error.message)));

$('#randomPalette').addEventListener('click', () => {state.palette=state.palette.map((_,index)=>randomVividColor(index*41));renderPaletteEditor();});
$('#savePalette').addEventListener('click', () => {saveStored('rsclDronePaletteV051',state.palette);setLightState('DRONE PALETTE SAVED');});
$('#roleColors').addEventListener('click', () => {
  const roleMap = {LEADER:'#ff2aa1',FOLLOWER:'#28d7ff',SUPPORT:'#69ff9a',RESERVE:'#ffbd3f'};
  sortedDrones().forEach((drone,index) => state.droneColors[drone.drone_id] = roleMap[drone.role] || state.palette[index % state.palette.length]);
  state.droneMapSignature='';
  renderDroneColorMap(sortedDrones());
  setLightState('ROLE COLORS ASSIGNED; APPLY TO SEND');
});
$('#applyDroneColors').addEventListener('click', async () => {
  try { await post('/api/lighting/apply',{mapping:state.droneColors,brightness:Number($('#fleetBrightness').value)}); }
  catch (error) { alert(error.message); }
});
$('#rotateDroneColors').addEventListener('click', () => {
  const drones = sortedDrones();
  const colors = drones.map(drone => state.droneColors[drone.drone_id] || state.palette[0]);
  if (colors.length) colors.unshift(colors.pop());
  drones.forEach((drone,index) => state.droneColors[drone.drone_id] = colors[index]);
  state.droneMapSignature=''; renderDroneColorMap(drones);
});


function renderPaletteEditor() {
  const editor = $('#paletteEditor');

  editor.innerHTML = state.palette.map((color, index) => `
    <label class="palette-slot">
      <span>C${index + 1}</span>
      <input
        type="color"
        data-palette-index="${index}"
        value="${esc(color)}"
        title="Physical mission color ${index + 1}"
      />
    </label>
  `).join('');

  $$('[data-palette-index]').forEach(input => {
    input.addEventListener('input', () => {
      const index = Number(input.dataset.paletteIndex);
      state.palette[index] = input.value;

      const drones = sortedDrones();
      drones.forEach((drone, droneIndex) => {
        if (!state.droneColors[drone.drone_id]) {
          state.droneColors[drone.drone_id] =
            state.palette[droneIndex % state.palette.length];
        }
      });
    });
  });
}

function missionParams() {
  return {
    repetitions:Number($('#missionRepeats').value),
    distance_cm:Number($('#missionDistance').value),
    speed:Number($('#missionSpeed').value),
    degrees:Number($('#missionDegrees').value),
    phase_ms:Number($('#missionPhase').value),
    led_brightness:Number($('#missionLedBrightness').value),
    min_battery:Number($('#missionBattery').value),
    auto_takeoff:$('#missionTakeoff').checked,
    auto_land:$('#missionLand').checked,
    palette:state.palette
  };
}

function selectPreset(name) {
  state.selectedPreset = name;
  $$('[data-preset]').forEach(button => button.classList.toggle('selected', button.dataset.preset === name));
  previewSelectedPreset();
}

async function previewSelectedPreset() {
  try {
    const preview = await post('/api/mission/preview',{target:$('#missionTarget').value,preset:state.selectedPreset,params:missionParams()});
    $('#missionPreview').innerHTML = `<strong>${esc(preview.preset.toUpperCase())}</strong> · ${esc(preview.classification)} · ${preview.members} member(s) · ${preview.step_count} steps · estimated ${fmt(preview.estimated_seconds,1)} s
      <ol class="preview-steps">${preview.steps.slice(0,18).map(step=>`<li>${esc(step)}</li>`).join('')}${preview.steps.length>18?`<li>… ${preview.steps.length-18} additional steps</li>`:''}</ol>
      <div class="preview-warning">${esc(preview.warning)}</div>`;
  } catch (error) {
    $('#missionPreview').textContent = error.message;
  }
}

$$('[data-preset]').forEach(button => button.addEventListener('click', () => selectPreset(button.dataset.preset)));
$('#previewPreset').addEventListener('click', previewSelectedPreset);
$('#runPreset').addEventListener('click', async () => {
  try { await post('/api/mission/run',{target:$('#missionTarget').value,preset:state.selectedPreset,params:missionParams()}); }
  catch (error) { alert(error.message); }
});

function buildStep() {
  const action = $('#stepAction').value;
  const value = Number($('#stepValue').value);
  const rgb = hexToRgb($('#stepColor').value);
  const speed = Number($('#missionSpeed').value);
  let params = {};
  let label = action.replaceAll('_',' ').toUpperCase();
  if (['forward','backward','left','right'].includes(action)) {params={distance_cm:value,speed};label+=` ${value} cm`;}
  else if (['turn_left','turn_right'].includes(action)) {params={degrees:value};label+=` ${value}°`;}
  else if (['hover','wait'].includes(action)) {params={duration:value};label+=` ${value} s`;}
  else if (action === 'set_led') {params={...rgb,brightness:Number($('#missionLedBrightness').value)};label=`LED ${$('#stepColor').value.toUpperCase()}`;}
  else if (action === 'color_wave') {params={palette:state.palette,palette_offset:state.customSteps.length,stagger_ms:Number($('#missionPhase').value),brightness:100};label='FLEET COLOR WAVE';}
  return {action,params,label};
}

$('#addStep').addEventListener('click', () => {
  if (state.customSteps.length >= 60) {alert('Maximum custom mission length is 60 steps.');return;}
  state.customSteps.push(buildStep());renderTimeline();
});
$('#clearTimeline').addEventListener('click', () => {state.customSteps=[];renderTimeline();});
$('#runCustom').addEventListener('click', async () => {
  if (!state.customSteps.length) {alert('Add at least one mission step.');return;}
  try {await post('/api/mission/run',{target:$('#missionTarget').value,name:'CUSTOM CHOREOGRAPHY',steps:state.customSteps,params:missionParams()});}
  catch (error) {alert(error.message);}
});
$('#abortMission').addEventListener('click', () => post('/api/mission/abort').catch(error => alert(error.message)));

function connectWs() {
  const socket = new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);
  socket.onopen = () => $('#linkBadge').textContent='DATA LINK ACTIVE';
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.type === 'snapshot') {
      state.simulate=message.payload.simulate;state.autoDetect=message.payload.auto_detect;state.drones={};
      message.payload.drones.forEach(drone=>state.drones[drone.drone_id]=drone);
      state.events=message.payload.events||[];state.mission=message.payload.mission||state.mission;
    }
    if (message.type === 'telemetry') state.drones[message.payload.drone_id]=message.payload;
    if (message.type === 'event') state.events.push(message.payload);
    if (message.type === 'mission') state.mission={...state.mission,...message.payload};
    render();
  };
  socket.onclose = () => setTimeout(connectWs,1200);
}

setInterval(() => $('#clock').textContent=new Date().toLocaleTimeString(),1000);
renderPaletteEditor();
renderTimeline();
selectPreset(state.selectedPreset);
fetch('/api/status').then(response=>response.json()).then(snapshot=>{
  state.simulate=snapshot.simulate;state.autoDetect=snapshot.auto_detect;
  snapshot.drones.forEach(drone=>state.drones[drone.drone_id]=drone);
  state.events=snapshot.events||[];state.mission=snapshot.mission||state.mission;render();
});
connectWs();
