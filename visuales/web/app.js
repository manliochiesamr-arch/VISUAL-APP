'use strict';
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
let state = null, clips = [], ws = null, shows = { shows: [], active: null };
const dragging = new Set();

// ---------------- conexion ----------------
function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => $('#conn').classList.remove('off');
  ws.onclose = () => { $('#conn').classList.add('off'); setTimeout(start, 1000); };
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.type === 'state') { onState(m); }
    else if (m.type === 'shows') { shows = m; renderShows(); renderLibrary(); }
    else if (m.type === 'usb') { $('#usb').textContent = m.text; $('#usb').hidden = !m.text; }
    else if (m.type === 'library') { clips = m.clips; $('#free').textContent = `Espacio libre: ${m.free_gb} GB`; renderShows(); renderLibrary(); }
  };
}
function send(cmd, data = {}) {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ cmd, ...data }));
}

// ---------------- faders ----------------
class Fader {
  constructor(el) {
    this.el = el; this.max = parseFloat(el.dataset.max || 1); this.min = parseFloat(el.dataset.min || 0); this.value = 0;
    el.innerHTML = '<div class="fill"></div><div class="knob"></div>';
    this.fill = el.firstChild; this.knob = el.lastChild;
    this.pending = null;
    el.addEventListener('pointerdown', (e) => { el.setPointerCapture(e.pointerId); dragging.add(el.id); this.move(e); });
    el.addEventListener('pointermove', (e) => { if (dragging.has(el.id)) this.move(e); });
    const end = () => { dragging.delete(el.id); this.flush(); };
    el.addEventListener('pointerup', end); el.addEventListener('pointercancel', end);
  }
  move(e) {
    const r = this.el.getBoundingClientRect();
    const k = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    this.set(this.min + k * (this.max - this.min));
    this.pending = this.value;
    if (!this.raf) this.raf = requestAnimationFrame(() => { this.raf = null; this.flush(); });
  }
  flush() {
    if (this.pending === null) return;
    const v = this.pending; this.pending = null;
    const d = this.el.dataset;
    if (d.clip) send('clipfx', { deck: clipDeck(), [d.clip]: v });
    else if (d.key) send(d.cmd, { [d.key]: v });
    else if (d.deck) send(d.cmd, { deck: d.deck, value: v });
    else send(d.cmd, { value: v });
    this.onchange && this.onchange(v);
  }
  set(v) {
    this.value = v;
    const p = ((v - this.min) / (this.max - this.min)) * 100;
    this.fill.style.width = p + '%'; this.knob.style.left = p + '%';
  }
}
const faders = {};
$$('.fader').forEach((el) => { faders[el.id] = new Fader(el); });
const setFader = (id, v) => { if (!dragging.has(id)) faders[id].set(v); };

// ---------------- estado ----------------
let lastBeat = -1, beatT = 0;
function onState(s) {
  const prev = state; state = s;
  if (s.beat !== lastBeat) { lastBeat = s.beat; beatT = performance.now(); }
  $('#bpm').textContent = Math.round(s.bpm);
  $('#blackout').classList.toggle('on', s.blackout);
  setFader('f-xfade', s.xfade); setFader('f-master', s.master);
  setFader('f-fade_time', s.fade_time); $('#v-fade_time').textContent = s.fade_time.toFixed(1) + 's';
  setFader('f-tint', s.tint_amount);
  setFader('f-blackout_time', s.blackout_time); $('#v-blackout_time').textContent = s.blackout_time.toFixed(1) + 's';
  renderClipPanel();
  for (const k of ['A', 'B']) {
    const el = $('#deck' + k);
    el.classList.toggle('live', s.live === k); el.classList.toggle('next', s.next === k);
    const c = clips.find((c) => c.id === s.decks[k].clip);
    el.querySelector('.dname').textContent = c ? c.name : '—';
  }
  $('#strobe').classList.toggle('on', s.strobe);
  if (s.glitch) {
    setFader('f-g-rgb', s.glitch.rgb); setFader('f-g-tracking', s.glitch.tracking);
    setFader('f-g-hue', s.glitch.hue); setFader('f-g-sat', s.glitch.sat);
    $('#v-g-sat').textContent = Math.round(s.glitch.sat * 100) + '%';
  }
  if (Array.isArray(s.osd)) {
    const o = s.osd[osdLayer] || s.osd[0];
    const ti = $('#osd-text');
    if (document.activeElement !== ti && ti.value !== o.text) ti.value = o.text;
    $('#osd-on').classList.toggle('on', o.on); $('#osd-blink').classList.toggle('on', o.blink);
    segOn('#osd-pos', o.pos); segOn('#osd-size', String(o.size)); segOn('#osd-layer', String(osdLayer));
    // punto en las capas que estan prendidas
    $$('#osd-layer button').forEach((b, i) => b.classList.toggle('lit', !!(s.osd[i] && s.osd[i].on)));
  }
  $('#quake').classList.toggle('on', s.quake);
  setFader('f-quake', s.quake_amount);
  setFader('f-zoom', s.zoom); $('#v-zoom').textContent = s.zoom.toFixed(1) + 'x';
  segOn('#screen', s.screen); segOn('#zoom-mode', s.zoom_mode);
  $$('#zoom-cycle button').forEach((b) => b.classList.toggle('on', parseFloat(b.dataset.v) === s.zoom_cycle));
  $$('#strobe-div button').forEach((b) => b.classList.toggle('on', parseFloat(b.dataset.v) === s.strobe_div));
  $$('#strobe-color button').forEach((b) => b.classList.toggle('on', b.dataset.v === s.strobe_color));
  $$('#swatches button').forEach((b) => b.classList.toggle('on', b.dataset.c === s.tint.map((x) => x.toFixed(2)).join(',')));
  if (!prev || prev.decks.A.clip !== s.decks.A.clip || prev.decks.B.clip !== s.decks.B.clip || prev.live !== s.live ||
      String(prev.texts) !== String(s.texts)) renderGrid();
}

// luz de beat (interpolada localmente)
(function beatLoop() {
  if (state) {
    const period = 60000 / state.bpm;
    const ph = ((performance.now() - beatT) % period) / period;
    $('#beat').classList.toggle('on', ph < 0.2);
  }
  requestAnimationFrame(beatLoop);
})();

// ---------------- biblioteca / grilla ----------------
function thumb(c) { return `/thumbs/${c.id}.jpg?v=${c.status}`; }
function renderGrid() {
  const g = $('#grid');
  const show = activeShow();
  let ready = clips.filter((c) => c.status === 'ready' || c.status === 'processing' || c.status === 'queued');
  if (show) ready = show.clips.map((id) => ready.find((c) => c.id === id)).filter(Boolean);
  if (!ready.length) {
    g.innerHTML = show
      ? `<div class="empty">El show "${esc(show.name)}" no tiene videos.<br>Agregalos desde Biblioteca.</div>`
      : '<div class="empty">No hay videos. Subilos desde la pestaña Biblioteca.</div>';
    return;
  }
  g.innerHTML = '';
  for (const c of ready) {
    const d = document.createElement('div');
    d.className = 'clip';
    if (c.kind === 'text') { renderTextTile(d, c); g.appendChild(d); continue; }
    if (c.status !== 'ready') d.classList.add('busy');
    else if (c.kind === 'solid') d.style.background = solidCss(c.fx);
    else d.style.backgroundImage = `url(${thumb(c)})`;
    let tag = '';
    if (state) {
      const onA = state.decks.A.clip === c.id, onB = state.decks.B.clip === c.id;
      const k = onA ? 'A' : onB ? 'B' : null;
      if (k && state.live === k) { d.classList.add('live'); tag = 'AIRE'; }
      else if (k) { d.classList.add('next'); tag = 'NEXT'; }
    }
    d.innerHTML = (tag ? `<b class="tag">${tag}</b>` : '') + `<span>${esc(c.status === 'ready' ? c.name : 'convirtiendo…')}</span>`;
    d.onclick = () => {
      if (c.status !== 'ready') return;
      // 1er toque: precargar en NEXT. 2do toque sobre el mismo: GO
      if (state && state.decks[state.next].clip === c.id) send('go');
      else send('cue', { clip: c.id });
    };
    g.appendChild(d);
  }
}
// ---------------- solidos y textos ----------------
function hsv(h, s, v) {
  const f = (n) => { const k = (n + h * 6) % 6; return v - v * s * Math.max(0, Math.min(k, 4 - k, 1)); };
  return [f(5), f(3), f(1)];
}
function solidCss(fx) {
  fx = fx || {};
  const c = hsv(fx.hue || 0, fx.sat ?? 1, fx.bright ?? 1);
  return `rgb(${c.map((x) => Math.round(x * 255)).join(',')})`;
}
const rgbCss = (c) => `rgb(${(c || [1, 1, 1]).map((x) => Math.round(x * 255)).join(',')})`;
function textPreview(el, t, big) {
  // vista aproximada: letra monoespaciada, ubicada como en la pantalla
  el.className = 'tprev pos-' + t.pos;
  el.textContent = t.text.replace(/\{hora\}/g, 'PM 9:41').replace(/\{fecha\}/g, 'NOV. 12 2026').toUpperCase() || '(vacío)';
  el.style.color = rgbCss(t.color);
  el.style.fontSize = (big === 'lib' ? [4, 5, 6, 7] : big ? [10, 16, 22, 30] : [6, 8, 11, 14])[t.size - 1] + 'px';
}
function liveClip() { return state ? state.decks[state.live].clip : null; }
function textOn(c) {
  if (!state) return false;
  return (state.texts || []).includes(c.id) || (!!c.text.link && c.text.link === liveClip());
}
function renderTextTile(d, c) {
  const on = textOn(c);
  d.classList.add('textclip'); d.classList.toggle('live', on);
  d.innerHTML = '<div></div>' + (on ? '<b class="tag">ON</b>' : '') +
    `<span>${c.text.link ? '🔗 ' : ''}${c.text.fx ? 'FX · ' : ''}${esc(c.name)}</span><button class="tedit">✎</button>`;
  textPreview(d.firstChild, c.text, false);
  d.onclick = () => send('text_toggle', { clip: c.id });
  d.querySelector('.tedit').onclick = (e) => { e.stopPropagation(); openText(c.id); };
}
let editText = null;
function openText(id) {
  editText = id; clipTarget = 'text';
  $('nav button[data-tab=clip]').click();
  const c = clips.find((x) => x.id === id);
  if (c) $('#t-text').value = c.text.text;
  renderClipPanel();
}
const textClip = () => clips.find((x) => x.id === editText && x.kind === 'text');
const tsend = (data) => { if (editText) send('textclip', { clip: editText, ...data }); };
let tTimer = null;
$('#t-text').oninput = (e) => { clearTimeout(tTimer); tTimer = setTimeout(() => tsend({ text: e.target.value }), 250); };
$$('#t-quick button').forEach((b) => b.onclick = () => {
  const ti = $('#t-text');
  ti.value = (ti.value ? ti.value + ' ' : '') + b.dataset.t;
  tsend({ text: ti.value });
});
$$('#t-pos button').forEach((b) => b.onclick = () => tsend({ pos: b.dataset.v }));
$$('#t-size button').forEach((b) => b.onclick = () => tsend({ size: parseInt(b.dataset.v, 10) }));
$('#t-blink').onclick = () => { const c = textClip(); if (c) tsend({ blink: !c.text.blink }); };
$('#t-on').onclick = () => { if (editText) send('text_toggle', { clip: editText }); };
$('#t-alloff').onclick = () => send('texts_off');
$('#t-fx').onclick = () => { const c = textClip(); if (c) tsend({ fx: !c.text.fx }); };
$('#t-link').onchange = (e) => tsend({ link: e.target.value || null });
// clips a los que se puede vincular un texto: primero los del show activo
function linkOptions() {
  const ok = clips.filter((c) => c.kind !== 'text' && c.status === 'ready');
  const show = activeShow();
  if (!show) return ok;
  return [...show.clips.map((id) => ok.find((c) => c.id === id)).filter(Boolean),
          ...ok.filter((c) => !show.clips.includes(c.id))];
}
$('#t-ren').onclick = async () => {
  const c = textClip(); if (!c) return;
  const n = await askText('Nombre del texto', c.name);
  if (n) tsend({ name: n });
};
const TEXT_COLORS = [[1,1,1],[1,1,0.2],[0.2,1,0.3],[0.1,0.9,1],[1,0.15,0.15],[1,0.2,0.8],[0.25,0.35,1],[0,0,0]];
for (const col of TEXT_COLORS) {
  const b = document.createElement('button');
  b.dataset.c = col.join(','); b.style.background = rgbCss(col);
  b.onclick = () => tsend({ color: col });
  $('#t-colors').appendChild(b);
}
// colores rapidos del solido (tono, saturacion, brillo)
const SOLID_COLORS = [[0,0,1],[0,1,1],[0.08,1,1],[0.16,1,1],[0.33,1,1],[0.5,1,1],[0.63,1,1],[0.8,1,1],[0.9,1,1],[0,0,0]];
for (const [h, s, v] of SOLID_COLORS) {
  const b = document.createElement('button');
  b.style.background = solidCss({ hue: h, sat: s, bright: v });
  b.onclick = () => send('clipfx', { deck: clipDeck(), hue: h, sat: s, bright: v });
  $('#c-swatches').appendChild(b);
}
async function newResource(kind) {
  let body = { kind };
  if (kind === 'text') {
    const t = await askText('Texto (después lo editás en la pestaña Clip)', '');
    if (!t) return;
    body.text = t;
  }
  const r = await fetch('/api/clips/new', { method: 'POST', body: JSON.stringify(body) }).then((x) => x.json()).catch(() => null);
  if (!r || !r.ok) return alert('No se pudo crear: ' + ((r && r.error) || 'error de red'));
  if (kind === 'text') {
    if (!clips.find((c) => c.id === r.clip.id)) clips.unshift(r.clip);
    openText(r.clip.id);
  }
}
$('#new-solid').onclick = () => newResource('solid');
$('#new-text').onclick = () => newResource('text');

function renderLibrary() {
  renderGrid();
  const ul = $('#liblist');
  ul.innerHTML = '';
  const label = { ready: 'listo', queued: 'en cola', processing: 'convirtiendo…', error: 'error' };
  for (const c of clips) {
    const li = document.createElement('li');
    li.className = 'st-' + c.status;
    const dur = c.kind === 'gen' ? ' · generativo' : c.kind === 'solid' ? ' · sólido' : c.kind === 'text' ? ' · texto'
      : c.duration ? ` · ${Math.round(c.duration)}s` : '';
    const pic = c.kind === 'solid' ? `<div class="noimg" style="background:${solidCss(c.fx)}"></div>`
      : c.kind === 'text' ? '<div class="noimg tbox"><div></div></div>'
      : c.status === 'ready' ? `<img src="${thumb(c)}">` : '<div class="noimg"></div>';
    li.innerHTML = pic +
      `<div class="meta"><b>${esc(c.name)}</b><small>${label[c.status] || c.status}${c.error ? ': ' + esc(c.error) : ''}${dur}</small></div>` +
      (activeShow() ? `<button class="small inshow${activeShow().clips.includes(c.id) ? ' on' : ''}">${activeShow().clips.includes(c.id) ? '✓ show' : '＋ show'}</button>` : '') +
      (c.kind === 'gen' ? '' : '<button class="small ren">✎</button><button class="small del">🗑</button>');
    const ins = li.querySelector('.inshow');
    if (ins) ins.onclick = () => send('show_toggle_clip', { id: shows.active, clip: c.id });
    if (c.kind === 'text') { textPreview(li.querySelector('.tbox div'), c.text, 'lib'); li.querySelector('.tbox').onclick = () => openText(c.id); }
    if (c.kind !== 'gen') li.querySelector('.del').onclick = async () => {
      if (!confirm(`¿Borrar "${c.name}"?`)) return;
      await fetch(`/api/clips/${c.id}`, { method: 'DELETE' });
    };
    if (c.kind !== 'gen') li.querySelector('.ren').onclick = async () => {
      if (c.kind === 'text') return openText(c.id);
      const n = await askText('Nombre', c.name);
      if (n) await fetch(`/api/clips/${c.id}/rename`, { method: 'POST', body: JSON.stringify({ name: n }) });
    };
    ul.appendChild(li);
  }
  if (state) onState(state);
}
// ---------------- shows ----------------
function activeShow() { return shows.shows.find((s) => s.id === shows.active) || null; }
function renderShows() {
  const sel = $('#show-sel');
  sel.innerHTML = '<option value="">Todos los videos</option>' +
    shows.shows.map((s) => `<option value="${s.id}">${esc(s.name)} (${s.clips.length})</option>`).join('');
  sel.value = shows.active || '';
  const box = $('#show-admin'), show = activeShow();
  // lista de todos los shows: tocar uno lo activa
  const chips = '<div class="showchips">' +
    `<button data-id="" class="${show ? '' : 'on'}">Todos</button>` +
    shows.shows.map((s) => `<button data-id="${s.id}" class="${s.id === shows.active ? 'on' : ''}">${esc(s.name)}</button>`).join('') +
    '<button id="sa-new" class="add">＋ Nuevo show</button></div>';
  if (!show) {
    box.innerHTML = '<div class="showbox"><div class="row"><b>Shows</b></div>' + chips +
      '<p class="hint">Un show es la lista de videos y ajustes de una banda. Creá uno por banda y elegí cuál está activo.</p></div>';
  } else {
    box.innerHTML = '<div class="showbox"><div class="row"><b>Shows</b></div>' + chips +
      `<div class="row" style="margin-top:10px"><b>${esc(show.name)}</b>` +
      '<button class="small" id="sa-ren">✎</button><button class="small" id="sa-del">🗑</button></div>' +
      '<p class="hint">Lo que subas entra a este show. Con ＋ show agregás videos que ya están en la biblioteca. ' +
      'BPM, tinte, pantalla y tiempos se guardan con el show.</p><ul class="order" id="sa-order"></ul></div>';
  }
  $$('.showchips button[data-id]').forEach((bt) => bt.onclick = () => send('show_select', { id: bt.dataset.id || null }));
  $('#sa-new').onclick = newShow;
  if (!show) return;
  $('#sa-ren').onclick = async () => { const n = await askText('Nombre del show', show.name); if (n) send('show_rename', { id: show.id, name: n }); };
  $('#sa-del').onclick = () => { if (confirm(`¿Borrar el show "${show.name}"? Los videos quedan en la biblioteca.`)) send('show_delete', { id: show.id }); };
  const ul = $('#sa-order');
  show.clips.forEach((id, i) => {
    const c = clips.find((x) => x.id === id);
    if (!c) return;
    const li = document.createElement('li');
    li.innerHTML = `<span>${i + 1}. ${esc(c.name)}</span><button>↑</button><button>↓</button><button>✕</button>`;
    const [up, down, rm] = li.querySelectorAll('button');
    up.onclick = () => send('show_move', { id: show.id, clip: id, dir: -1 });
    down.onclick = () => send('show_move', { id: show.id, clip: id, dir: 1 });
    rm.onclick = () => send('show_toggle_clip', { id: show.id, clip: id });
    ul.appendChild(li);
  });
}
async function newShow() {
  const n = await askText('Nombre del show nuevo (ej: la banda)', '');
  if (n) send('show_create', { name: n });
}
// cuadro de texto propio: el navegador puede bloquear prompt() despues de usarlo varias veces
function askText(title, value) {
  return new Promise((resolve) => {
    const bg = document.createElement('div');
    bg.className = 'ask';
    bg.innerHTML = `<form><b>${esc(title)}</b><input type="text" maxlength="60"><div class="row">` +
      '<button type="button" class="wide">Cancelar</button><button type="submit" class="wide ok">OK</button></div></form>';
    const input = bg.querySelector('input');
    input.value = value || '';
    const done = (v) => { bg.remove(); resolve(v); };
    bg.querySelector('form').onsubmit = (e) => { e.preventDefault(); done(input.value.trim() || null); };
    bg.querySelector('button[type=button]').onclick = () => done(null);
    document.body.appendChild(bg);
    input.focus(); input.select();
  });
}
$('#show-sel').onchange = (e) => send('show_select', { id: e.target.value || null });
$('#show-new').onclick = newShow;

function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

// ---------------- subida ----------------
$('#file').addEventListener('change', async (e) => {
  const files = [...e.target.files];
  e.target.value = '';
  for (const f of files) await uploadOne(f);
});
function uploadOne(f) {
  return new Promise((resolve) => {
    const row = document.createElement('div');
    row.className = 'up';
    row.innerHTML = `${esc(f.name)} <small></small><div class="bar"><div></div></div>`;
    $('#uploads').prepend(row);
    const bar = row.querySelector('.bar div'), info = row.querySelector('small');
    if (!/\.(mp4|mov|m4v)$/i.test(f.name)) { row.classList.add('err'); info.textContent = 'rechazado: solo .mp4 / .mov'; return resolve(); }
    const fd = new FormData(); fd.append('file', f, f.name);
    const x = new XMLHttpRequest();
    x.open('POST', '/api/upload');
    x.upload.onprogress = (ev) => { if (ev.lengthComputable) bar.style.width = (100 * ev.loaded / ev.total) + '%'; };
    x.onload = () => {
      try {
        const r = JSON.parse(x.responseText).results[0];
        if (r.ok) { row.classList.add('ok'); info.textContent = 'subido, convirtiendo…'; }
        else { row.classList.add('err'); info.textContent = r.error; }
      } catch { row.classList.add('err'); info.textContent = 'error ' + x.status; }
      resolve();
    };
    x.onerror = () => { row.classList.add('err'); info.textContent = 'error de red'; resolve(); };
    x.send(fd);
  });
}

// ---------------- botones ----------------
$$('nav button').forEach((b) => b.onclick = () => {
  $$('nav button').forEach((x) => x.classList.toggle('on', x === b));
  $$('.tab').forEach((t) => t.classList.toggle('on', t.id === 'tab-' + b.dataset.tab));
});
$('#tap').addEventListener('pointerdown', () => send('tap'));
$('#blackout').onclick = () => send('blackout', { value: !(state && state.blackout) });
$('#go').onclick = () => send('go');
$('#cut').onclick = () => send('cut');
$('#resync').onclick = () => send('resync');
$('#bpm-plus').onclick = () => send('bpm', { value: state.bpm + 1 });
$('#bpm-minus').onclick = () => send('bpm', { value: state.bpm - 1 });
$('#bpm-half').onclick = () => send('bpm', { value: state.bpm / 2 });
$('#bpm-double').onclick = () => send('bpm', { value: state.bpm * 2 });
$$('#strobe-div button').forEach((b) => b.onclick = () => send('strobe', { div: parseFloat(b.dataset.v) }));
$$('#strobe-color button').forEach((b) => b.onclick = () => send('strobe', { color: b.dataset.v }));
function segOn(sel, v) { $$(sel + ' button').forEach((b) => b.classList.toggle('on', b.dataset.v === v)); }
$$('#screen button').forEach((b) => b.onclick = () => send('view', { screen: b.dataset.v }));
// ---------------- panel de clip (NEXT / AL AIRE) ----------------
let clipTarget = 'next';
function clipDeck() { return state ? state[clipTarget] : 'B'; }
$$('#clip-target button').forEach((b) => b.onclick = () => { clipTarget = b.dataset.v; renderClipPanel(); });
function renderTextPanel() {
  const c = textClip();
  $('#deck-edit').hidden = true; $('#text-edit').hidden = !c;
  $('#pv-img').style.display = 'none';
  const pt = $('#pv-text');
  $('#pv-empty').style.display = c ? 'none' : '';
  $('#preview').style.background = '#000';
  if (!c) { $('#clip-name').textContent = 'No hay texto elegido'; pt.textContent = ''; return; }
  const on = (state.texts || []).includes(c.id);
  $('#clip-name').textContent = `TEXTO · ${c.name}` + (textOn(c) && !on ? ' (sale con su clip)' : '');
  $('#t-fx').classList.toggle('on', !!c.text.fx);
  const sel = $('#t-link'), opts = linkOptions();
  const html = '<option value="">— nadie (solo a mano) —</option>' +
    opts.map((x) => `<option value="${x.id}">${esc(x.name)}</option>`).join('');
  if (sel.dataset.h !== html) { sel.innerHTML = html; sel.dataset.h = html; }
  sel.value = c.text.link || '';
  const ti = $('#t-text');
  if (document.activeElement !== ti && ti.value !== c.text.text) ti.value = c.text.text;
  segOn('#t-pos', c.text.pos); segOn('#t-size', String(c.text.size));
  $('#t-on').classList.toggle('on', on); $('#t-blink').classList.toggle('on', c.text.blink);
  $$('#t-colors button').forEach((b) => b.classList.toggle('on', b.dataset.c === c.text.color.join(',')));
  textPreview(pt, c.text, true);
}
$$('#cfit button').forEach((b) => b.onclick = () => send('clipfx', { deck: clipDeck(), fit: b.dataset.v }));
$('#c-speed1').onclick = () => send('clipfx', { deck: clipDeck(), speed: 1 });
$('#c-center').onclick = () => send('clipfx', { deck: clipDeck(), panx: 0, pany: 0 });
$('#c-reset').onclick = () => send('clipfx', { deck: clipDeck(), reset: true });
// tocar un deck en Show abre su panel de clip
for (const k of ['A', 'B']) $('#deck' + k).onclick = () => {
  if (!state) return;
  clipTarget = state.live === k ? 'live' : 'next';
  $('nav button[data-tab=clip]').click();
};
function fitScale(ca, sa, mode) {
  if (mode === 'stretch') return [1, 1];
  const wider = ca > sa;
  if (mode === 'fill') return wider ? [ca / sa, 1] : [1, sa / ca];
  return wider ? [1, sa / ca] : [ca / sa, 1];
}
function renderClipPanel() {
  if (!state) return;
  $('#ct-text').hidden = !editText;
  if (clipTarget === 'text' && !editText) clipTarget = 'next';
  segOn('#clip-target', clipTarget);
  if (clipTarget === 'text') return renderTextPanel();
  $('#deck-edit').hidden = false; $('#text-edit').hidden = true;
  $('#pv-text').textContent = ''; $('#pv-text').className = '';
  $('#preview').style.background = '';
  const deck = state.decks[clipDeck()], fx = deck.fx;
  const c = clips.find((x) => x.id === deck.clip);
  $('#clip-name').textContent = c ? `${clipTarget === 'live' ? 'AL AIRE' : 'NEXT'} · ${c.name}` : 'No hay clip en ' + (clipTarget === 'live' ? 'el aire' : 'NEXT');
  segOn('#cfit', fx.fit);
  setFader('f-czoom', fx.zoom); $('#v-czoom').textContent = fx.zoom.toFixed(2) + 'x';
  setFader('f-cpanx', fx.panx); setFader('f-cpany', fx.pany);
  setFader('f-cspeed', fx.speed); $('#v-cspeed').textContent = fx.speed.toFixed(2) + 'x';
  const isGen = !!(c && c.kind === 'gen');
  const isSolid = !!(c && c.kind === 'solid');
  $$('#tab-clip .genonly, #tab-clip .solidonly').forEach((el) => { el.hidden = true; });
  $$('#tab-clip .vid').forEach((el) => { el.hidden = isSolid; });
  if (isGen) $$('#tab-clip .genonly').forEach((el) => { el.hidden = false; });
  if (isSolid) $$('#tab-clip .solidonly').forEach((el) => { el.hidden = false; });
  if (isGen || isSolid) setFader('f-chue', fx.hue || 0);
  if (isGen) setFader('f-cdetail', fx.detail ?? 0.5);
  setFader('f-cg-rgb', fx.g_rgb || 0); setFader('f-cg-trk', fx.g_trk || 0);
  setFader('f-cg-hue', fx.g_hue || 0); setFader('f-cg-sat', fx.g_sat ?? 1);
  $('#v-cg-sat').textContent = Math.round((fx.g_sat ?? 1) * 100) + '%';
  if (isSolid) {
    setFader('f-csat', fx.sat ?? 1); setFader('f-cbright', fx.bright ?? 1);
    $('#preview').style.background = solidCss(fx);
    $('#pv-empty').style.display = 'none'; $('#pv-img').style.display = 'none';
    return;
  }
  // vista previa del encuadre con la miniatura
  const pv = $('#preview'), img = $('#pv-img');
  const sa = state.screen === '16:9' ? 16 / 9 : 4 / 3;
  pv.style.aspectRatio = state.screen === '16:9' ? '16/9' : '4/3';
  $('#pv-empty').style.display = c ? 'none' : '';
  img.style.display = c && c.status === 'ready' ? '' : 'none';
  if (!c || c.status !== 'ready') return;
  const want = thumb(c);
  if (img.getAttribute('src') !== want) img.src = want;
  const ca = (c.width && c.height) ? c.width / c.height : 16 / 9;
  const [sx, sy] = fitScale(ca, sa, fx.fit);
  img.style.width = (sx * fx.zoom * 100) + '%';
  img.style.height = (sy * fx.zoom * 100) + '%';
  img.style.left = (50 + fx.panx * 50 * fx.zoom) + '%';
  img.style.top = (50 + fx.pany * 50 * fx.zoom) + '%';
}
$$('#zoom-mode button').forEach((b) => b.onclick = () => send('zoom', { mode: b.dataset.v }));
$$('#zoom-cycle button').forEach((b) => b.onclick = () => send('zoom', { cycle: parseFloat(b.dataset.v) }));
$('#zoom-reset').onclick = () => send('zoom', { value: 1, mode: 'fixed' });
// strobe / terremoto: toque = alterna, mantener = momentaneo
function holdToggle(id, cmd) {
  const b = $(id); let t0 = 0, was = false;
  b.addEventListener('pointerdown', () => { t0 = performance.now(); was = state && state[cmd]; send(cmd, { on: true }); });
  const up = () => {
    if (!t0) return;
    const held = performance.now() - t0 > 350; t0 = 0;
    if (held || was) send(cmd, { on: false });
  };
  b.addEventListener('pointerup', up); b.addEventListener('pointercancel', up);
}
holdToggle('#strobe', 'strobe');
holdToggle('#quake', 'quake');
// paleta de tinte
const COLORS = [[1,0.2,0.6],[1,0.1,0.1],[1,0.55,0],[1,1,0.2],[0.2,1,0.3],[0.1,0.9,1],[0.2,0.3,1],[0.7,0.2,1]];
for (const c of COLORS) {
  const b = document.createElement('button');
  b.dataset.c = c.map((x) => x.toFixed(2)).join(',');
  b.style.background = `rgb(${c.map((x) => Math.round(x * 255)).join(',')})`;
  b.onclick = () => send('tint', { color: c, ...(state && state.tint_amount === 0 ? { amount: 0.7 } : {}) });
  $('#swatches').appendChild(b);
}

// ---------------- texto VHS ----------------
$('#g-reset').onclick = () => send('glitch', { reset: true });
let osdTimer = null, osdLayer = 0;
const osd = (data) => send('osd', { layer: osdLayer, ...data });
$$('#osd-layer button').forEach((b) => b.onclick = () => {
  osdLayer = parseInt(b.dataset.v, 10);
  $('#osd-text').value = (state && state.osd[osdLayer].text) || '';
  if (state) onState(state);
});
$('#osd-text').oninput = (e) => {
  clearTimeout(osdTimer);
  osdTimer = setTimeout(() => osd({ text: e.target.value }), 250);
};
$$('.osd-quick button').forEach((b) => b.onclick = () => {
  const ti = $('#osd-text');
  ti.value = (ti.value ? ti.value + ' ' : '') + b.dataset.t;
  osd({ text: ti.value, on: true });
});
$$('#osd-pos button').forEach((b) => b.onclick = () => osd({ pos: b.dataset.v }));
$$('#osd-size button').forEach((b) => b.onclick = () => osd({ size: parseInt(b.dataset.v, 10) }));
const curLayer = () => (state && state.osd && state.osd[osdLayer]) || {};
$('#osd-on').onclick = () => osd({ on: !curLayer().on, text: $('#osd-text').value });
$('#osd-blink').onclick = () => osd({ blink: !curLayer().blink });

// ---------------- BPM por microfono (experimental) ----------------
// 32 bandas logaritmicas de 40 Hz a 10 kHz, 0..255
function sendSpectrum() {
  const buf = mic.spBuf; mic.sp.getByteFrequencyData(buf);
  const hz = mic.ctx.sampleRate / 2 / buf.length, out = [];
  for (let i = 0; i < 32; i++) {
    const f0 = 40 * Math.pow(250, i / 32), f1 = 40 * Math.pow(250, (i + 1) / 32);
    let a = Math.floor(f0 / hz), b = Math.max(a + 1, Math.ceil(f1 / hz)), m = 0;
    for (let j = a; j < b && j < buf.length; j++) m = Math.max(m, buf[j]);
    out.push(m);
  }
  // ganancia automatica: el pico reciente pasa a ser el maximo, asi reacciona igual
  // con musica fuerte o bajita. Debajo del piso de ruido no se amplifica.
  const peak = Math.max(...out);
  mic.peak = Math.max(peak, (mic.peak || 0) * 0.995, 60);
  const floor = 25;
  send('audio', { b: out.map((v) => Math.round(Math.max(0, v - floor) / (mic.peak - floor) * 255)) });
}
const mic = { on: false, ctx: null, stream: null, onsets: [], avg: 0, last: 0, history: [], sent: 0 };
$('#mic').onclick = async () => {
  if (mic.on) return stopMic();
  if (!navigator.mediaDevices || !window.isSecureContext) {
    $('#mic-hint').textContent = 'El micrófono solo funciona abriendo la app por https://… (ver README).';
    return;
  }
  try {
    mic.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
  } catch (e) { $('#mic-hint').textContent = 'Sin permiso de micrófono: ' + e.message; return; }
  mic.ctx = new (window.AudioContext || window.webkitAudioContext)();
  const src = mic.ctx.createMediaStreamSource(mic.stream);
  const lp = mic.ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 150;
  const an = mic.ctx.createAnalyser(); an.fftSize = 1024;
  src.connect(lp); lp.connect(an);
  // espectro completo para los visuales que reaccionan al sonido (Linea de audio)
  const sp = mic.ctx.createAnalyser(); sp.fftSize = 1024; sp.smoothingTimeConstant = 0.4;
  sp.minDecibels = -95; sp.maxDecibels = -25;
  src.connect(sp); mic.sp = sp; mic.spBuf = new Uint8Array(sp.frequencyBinCount);
  mic.an = an; mic.buf = new Float32Array(an.fftSize); mic.on = true; mic.onsets = []; mic.history = [];
  $('#mic').classList.add('on'); $('#mic-hint').textContent = 'Escuchando… acercá el teléfono al bombo.';
  micLoop();
};
function stopMic() {
  mic.on = false; $('#mic').classList.remove('on');
  if (mic.stream) mic.stream.getTracks().forEach((t) => t.stop());
  if (mic.ctx) mic.ctx.close();
}
function micLoop() {
  if (!mic.on) return;
  mic.an.getFloatTimeDomainData(mic.buf);
  let e = 0; for (const v of mic.buf) e += v * v; e = Math.sqrt(e / mic.buf.length);
  const now = performance.now();
  mic.avg = mic.avg * 0.97 + e * 0.03;
  let onset = false;
  if (e > mic.avg * 1.5 && e > 0.01 && now - mic.last > 280) { onset = true; mic.last = now; mic.onsets.push(now); }
  mic.onsets = mic.onsets.filter((t) => now - t < 8000);
  if (onset && mic.onsets.length >= 6) estimateBpm(now);
  if (now - (mic.specT || 0) > 50) { mic.specT = now; sendSpectrum(); }
  drawMeter(e, onset);
  requestAnimationFrame(micLoop);
}
function estimateBpm(now) {
  const hist = new Float32Array(200);
  const o = mic.onsets;
  for (let i = 0; i < o.length; i++) for (let j = i + 1; j < o.length && j < i + 5; j++) {
    let bpm = 60000 / (o[j] - o[i]);
    while (bpm < 80) bpm *= 2; while (bpm > 165) bpm /= 2;
    const w = 1 / (j - i);
    for (let d = -2; d <= 2; d++) { const k = Math.round(bpm) + d; if (k > 0 && k < 200) hist[k] += w * Math.exp(-d * d / 2); }
  }
  let best = 0; for (let k = 1; k < 200; k++) if (hist[k] > hist[best]) best = k;
  mic.history.push(best); mic.history = mic.history.slice(-4);
  const stable = mic.history.length >= 3 && Math.max(...mic.history) - Math.min(...mic.history) <= 2;
  $('#mic-hint').textContent = `Estimado: ${best} BPM${stable ? ' ✓' : ' …'}`;
  if (stable && now - mic.sent > 4000) {
    mic.sent = now;
    const avg = mic.history.reduce((a, b) => a + b, 0) / mic.history.length;
    send('bpm', { value: avg, resync: true });  // este onset pasa a ser el beat 1
  }
}
function drawMeter(e, onset) {
  const c = $('#mic-meter'), g = c.getContext('2d');
  const img = g.getImageData(2, 0, c.width - 2, c.height); g.putImageData(img, 0, 0);
  g.fillStyle = '#16161b'; g.fillRect(c.width - 2, 0, 2, c.height);
  const h = Math.min(c.height, e * 400);
  g.fillStyle = onset ? '#ff2e88' : '#555'; g.fillRect(c.width - 2, c.height - h, 2, h);
}

// pantalla siempre encendida mientras la app esta abierta (iOS 16.4+)
async function keepAwake() { try { await navigator.wakeLock.request('screen'); } catch {} }
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') keepAwake(); });
keepAwake();

// PIN: si la Pi tiene PIN, se pide una vez y queda guardado en una cookie
async function start() {
  let bad = false;
  for (;;) {
    let a;
    try { a = await (await fetch('/api/auth')).json(); } catch { await new Promise((r) => setTimeout(r, 2000)); continue; }
    if (a.ok) return connect();
    const pin = await askText(bad ? 'PIN incorrecto, proba de nuevo' : 'PIN de Visuales', '');
    if (!pin) continue;
    const r = await (await fetch('/api/pin', { method: 'POST', body: JSON.stringify({ pin }) })).json();
    bad = !r.ok;
  }
}
start();
