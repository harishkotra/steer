// steer console — one file, no build step.
// Drawing order matches the reference stills: text roll, gutter rail, leader
// lines, crosshair, radial dial, side readouts, status.

const $ = (s) => document.querySelector(s);
const stage = $('#stage');
const overlay = $('#overlay');
const proseEl = $('#prose');
const rollEl = $('#roll');
const textEl = $('#text');
const railEl = $('#rail');
const caretEl = $('#caret');
const statusEl = $('#status');
const badgesEl = $('#badges');
const dockEl = $('#dock');

let doc = '';
let words = [];
let lines = [];
let shift = 0;
let audit = null;
let meta = {};
let vectors = [];
let boxes = [];
let pins = [];
let generating = false;
let autogen = true;
let ws = null;
let dirty = true;
let errText = '';

const MAX_DOC = 14000;

// ---------------------------------------------------------------- socket

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    if (autogen) setTimeout(() => send({ cmd: 'generate', tokens: 150 }), 600);
  };

  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === 'init') {
      doc = msg.doc;
      meta = msg.meta;
      audit = msg.audit;
      vectors = msg.vectors || (msg.audit && msg.audit.vectors) || vectors;
      renderDock();
      schedule();
    } else if (msg.type === 'delta') {
      doc += msg.text;
      if (doc.length > MAX_DOC) doc = doc.slice(-10000);
      schedule();
    } else if (msg.type === 'audit') {
      audit = msg;
      schedule();
    } else if (msg.type === 'state') {
      vectors = msg.vectors || [];
      boxes = msg.boxes || [];
      pins = msg.pins || [];
      if (msg.audit) audit = msg.audit;
      generating = msg.generating;
      renderDock();
      schedule();
    } else if (msg.type === 'status') {
      generating = msg.generating;
      schedule();
      if (!generating && autogen) setTimeout(() => send({ cmd: 'generate', tokens: 150 }), 500);
    } else if (msg.type === 'reset') {
      doc = msg.doc;
      boxes = [];
      vectors = [];
      pins = [];
      schedule();
    } else if (msg.type === 'error') {
      errText = msg.message;
      generating = false;
      schedule();
    }
  };

  ws.onclose = () => setTimeout(connect, 1200);
}

function send(obj) {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj));
}

// ---------------------------------------------------------------- text

function renderText() {
  const frag = document.createDocumentFragment();
  const re = /\S+/g;
  let m, cursor = 0;
  words = [];
  while ((m = re.exec(doc))) {
    if (m.index > cursor) frag.appendChild(document.createTextNode(doc.slice(cursor, m.index)));
    const span = document.createElement('span');
    span.className = 'w';
    span.dataset.s = m.index;
    span.dataset.e = m.index + m[0].length;
    span.textContent = m[0];
    frag.appendChild(span);
    words.push(span);
    cursor = m.index + m[0].length;
  }
  if (cursor < doc.length) frag.appendChild(document.createTextNode(doc.slice(cursor)));
  textEl.replaceChildren(frag);
  textEl.appendChild(caretEl);
  paintClasses();
}

function paintClasses() {
  const segs = (audit && audit.segments) || [];
  const sorted = [...segs].sort((a, b) => b.score - a.score);
  const cut = sorted.length ? Math.max(0.08, sorted[0].score * 0.82) : 0;
  const beats = sorted.slice(0, 3).filter((s) => s.score >= cut);

  for (const w of words) {
    const s = +w.dataset.s;
    const e = +w.dataset.e;
    w.className = 'w';
    for (const b of boxes) {
      if (s < b.end && e > b.start) { w.classList.add('box'); break; }
    }
    if (w.classList.contains('box')) continue;
    for (const b of beats) {
      if (s < b.end && e > b.start) { w.classList.add('beat'); break; }
    }
  }
}

function segScoreAt(offset) {
  const segs = (audit && audit.segments) || [];
  let lo = 0, hi = segs.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const s = segs[mid];
    if (offset < s.start) hi = mid - 1;
    else if (offset >= s.end) lo = mid + 1;
    else return s.score;
  }
  return 0;
}

function measure() {
  const box = proseEl.getBoundingClientRect();
  textEl.style.transform = 'translateY(0px)';
  const h = textEl.getBoundingClientRect().height;
  const lh = 25.5;
  const need = Math.max(0, h - proseEl.clientHeight + lh);
  shift = Math.ceil(need / lh) * lh;
  textEl.style.transform = `translateY(${-shift}px)`;

  lines = [];
  let cur = null;
  for (const w of words) {
    const r = w.getBoundingClientRect();
    if (!r.height) continue;
    const top = r.top - box.top;
    if (!cur || Math.abs(top - cur.top) > 4) {
      cur = { top, text: '', score: 0, n: 0, start: +w.dataset.s };
      lines.push(cur);
    }
    cur.text += w.textContent + ' ';
    cur.score += segScoreAt(+w.dataset.s);
    cur.n += 1;
  }
  for (const l of lines) l.score = l.n ? l.score / l.n : 0;
}

// ---------------------------------------------------------------- rail

function renderRail() {
  const parts = [];
  const lh = 25.5;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const y = line.top;
    const n = Math.max(4, Math.min(11, Math.round(3 + line.score * 3 + (i % 3))));
    let cells = '';
    for (let c = 0; c < n; c++) {
      const v = Math.max(0.06, Math.min(1, line.score * (0.6 + ((c * 7 + i * 3) % 11) / 14)));
      const shade = Math.round(34 + v * 148);
      const w = c % 5 === 4 ? 5 : 6;
      cells += `<i class="cell" style="background:rgb(${shade},${shade},${shade});width:${w}px"></i>`;
    }
    parts.push(`<div class="cells" style="top:${y + 6}px;height:11px">${cells}</div>`);
    if (i % 5 === 0) {
      parts.push(`<div class="num" style="top:${y + 1}px">${i + 1}</div>`);
    }
  }

  // peak lines get a numeric readout and a bracket to the next peak
  const peaks = [];
  for (let i = 1; i < lines.length - 1; i++) {
    const s = lines[i].score;
    if (s > 0.07 && s >= lines[i - 1].score && s >= lines[i + 1].score) peaks.push(i);
  }
  const chosen = peaks.slice(-6);
  for (let k = 0; k < chosen.length; k++) {
    const line = lines[chosen[k]];
    parts.push(`<div class="score" style="top:${line.top + 1}px">${(line.score * 10).toFixed(2)}</div>`);
    const next = chosen[k + 1] ? lines[chosen[k + 1]].top : line.top + lh * 2;
    const top = line.top + 2;
    const height = Math.max(10, next - top - 2);
    parts.push(`<div class="brk" style="top:${top}px;height:${height}px"></div>`);
  }
  railEl.innerHTML = parts.join('');
}

// ---------------------------------------------------------------- overlay

const SVGNS = 'http://www.w3.org/2000/svg';
function el(name, attrs = {}) {
  const n = document.createElementNS(SVGNS, name);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
}

function drawOverlay() {
  const W = stage.clientWidth;
  const H = stage.clientHeight;
  overlay.setAttribute('viewBox', `0 0 ${W} ${H}`);
  overlay.replaceChildren();

  const caret = caretEl.getBoundingClientRect();
  const sbox = stage.getBoundingClientRect();
  const band = dialBand(H);
  // the instrument sits under the right half of the column, where the prose is
  // not: the caret gets its own mark, so the dial never has to chase it
  const ix = Math.round(Math.max(LEFT_LIMIT + 200, Math.min(W - 300, W * 0.6)));
  const cy = band.cy;

  // where the writer actually is, and only while that is inside the roll
  const cxp = caret.left - sbox.left;
  const cyp = caret.top - sbox.top;
  const rollBox = rollEl.getBoundingClientRect();
  if (cyp > rollBox.top - sbox.top - 6 && cyp < rollBox.bottom - sbox.top) {
    overlay.appendChild(el('rect', {
      x: cxp, y: cyp, width: Math.max(5, caret.width), height: caret.height,
      class: 'caret-mark',
    }));
  }

  // the vertical guide stops at the roll so it never crosses a character
  overlay.appendChild(el('line', { x1: ix, y1: 0, x2: ix, y2: Math.round(band.top - 16), class: 'cross' }));
  overlay.appendChild(el('line', { x1: LEFT_LIMIT - 64, y1: cy, x2: W - 24, y2: cy, class: 'cross' }));

  // leader lines from every live box and from the strongest clauses
  const anchors = [];
  for (const b of boxes) {
    const rect = rectForRange(b.start, b.end);
    if (rect) anchors.push({ x: rect.x + rect.width / 2, y: rect.y + rect.height, w: b.weight });
  }
  const segs = [...((audit && audit.segments) || [])].sort((a, b) => b.score - a.score).slice(0, 3);
  for (const s of segs) {
    if (s.score < 0.08) continue;
    const rect = rectForRange(s.start, s.end);
    if (rect) anchors.push({ x: rect.x + rect.width / 2, y: rect.y + rect.height, w: s.score });
  }
  for (const a of anchors.slice(0, 9)) {
    overlay.appendChild(el('line', {
      x1: a.x, y1: a.y, x2: ix, y2: cy - 4, class: 'leader',
      opacity: String(Math.min(0.5, 0.16 + a.w * 0.35)),
    }));
  }

  drawDial(ix, cy, W, H);

  overlay.appendChild(el('circle', { cx: ix, cy, r: 8, class: 'focus-ring' }));
  overlay.appendChild(el('circle', { cx: ix, cy, r: 4.2, class: 'focus-dot' }));
}

function rectForRange(start, end) {
  const hit = words.filter((w) => +w.dataset.s < end && +w.dataset.e > start);
  if (!hit.length) return null;
  const sbox = stage.getBoundingClientRect();
  const a = hit[0].getBoundingClientRect();
  const b = hit[hit.length - 1].getBoundingClientRect();
  const top = Math.min(a.top, b.top) - sbox.top;
  return {
    x: a.left - sbox.left,
    y: top,
    width: Math.max(4, b.right - a.left),
    height: a.height,
  };
}

const D2R = Math.PI / 180;
const polar = (cx, cy, deg, r) => [cx + Math.cos(deg * D2R) * r, cy + Math.sin(deg * D2R) * r];

function arcPath(cx, cy, r, a0, a1) {
  const [x0, y0] = polar(cx, cy, a0, r);
  const [x1, y1] = polar(cx, cy, a1, r);
  const large = Math.abs(a1 - a0) > 180 ? 1 : 0;
  return `M ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1}`;
}

const LEFT_LIMIT = 268;   // right edge of the gutter rail
const RIGHT_LIMIT = 870;  // left edge of the side readouts

// the dial owns the band between the prose roll and the status bar; every
// radius and label hangs off this, so the chart can never climb into the text
function dialBand(H) {
  const top = Math.round(H * 0.565) + 34;
  const bottom = Math.round(H * 0.945);
  return {
    top,
    bottom,
    cy: Math.round((top + bottom) / 2),
    rMax: Math.max(92, Math.min(188, (bottom - top) / 2 - 62)),
  };
}

function drawDial(cx, cy, W, H) {
  const rMax = dialBand(H).rMax;
  const g = el('g', {});
  const c = { cx, cy: cy + 6 };

  for (const [i, f] of [0.42, 0.68, 0.95].entries()) {
    const r = rMax * f;
    g.appendChild(el('circle', { cx: c.cx, cy: c.cy, r, class: 'ring' }));
    // ticks ride the 250° spoke, clear of every axis label
    const [lx, ly] = polar(c.cx, c.cy, 250, r);
    const t = el('text', { x: lx - 6, y: ly + 3, class: 'chart-key', 'text-anchor': 'end' });
    t.textContent = ['25', '50', '75'][i];
    g.appendChild(t);
  }

  for (const deg of [104, 122, 142, 162, 186, 208, 228, 250, 272]) {
    const [x0, y0] = polar(c.cx, c.cy, deg, rMax * 0.13);
    const [x1, y1] = polar(c.cx, c.cy, deg, rMax * 1.02);
    g.appendChild(el('line', { x1: x0, y1: y0, x2: x1, y2: y1, class: 'spoke' }));
  }

  // dialogue share (white) and description share (orange) around the rim
  const mode = audit?.metrics?.mode || { label: 'description', value: 0.5 };
  const dialR = rMax * 0.98;
  g.appendChild(el('path', { d: arcPath(c.cx, c.cy, dialR, 128, 176), class: 'arc-dialogue' }));
  g.appendChild(el('path', { d: arcPath(c.cx, c.cy, dialR, 16, 62), class: 'arc-desc' }));

  for (const deg of [128, 140, 152, 164, 176]) {
    const [x0, y0] = polar(c.cx, c.cy, deg, dialR - 6);
    const [x1, y1] = polar(c.cx, c.cy, deg, dialR + 6);
    g.appendChild(el('line', { x1: x0, y1: y0, x2: x1, y2: y1, class: 'tick' }));
  }

  const label = (deg, r, text, anchor, cls = 'chart-label', dy = 0) => {
    const [x, y] = polar(c.cx, c.cy, deg, r);
    const w = text.length * 6.1;
    let tx = x;
    if (anchor === 'end') tx = Math.max(LEFT_LIMIT + w, x);
    else if (anchor === 'start') tx = Math.min(RIGHT_LIMIT - w, x);
    else tx = Math.max(LEFT_LIMIT + w / 2, Math.min(RIGHT_LIMIT - w / 2, x));
    const t = el('text', {
      x: tx, y: Math.max(20, Math.min(H - 44, y + dy)),
      class: cls, 'text-anchor': anchor,
    });
    t.textContent = text;
    g.appendChild(t);
  };

  const m = audit?.metrics || {};
  if (m.tension) label(196, rMax * 1.2, `tension: ${m.tension.label}`, 'end');
  if (m.surprise) label(12, rMax * 1.2, `surprise: ${m.surprise.label}`, 'start');
  if (m.pace) label(132, rMax * 1.5, `pace: ${m.pace.label}`, 'end');
  label(90, rMax * 0.46, 'dialogue', 'middle', 'chart-key', 4);

  // the tag labels the arc from outside it, on a short leader, so the arc reads whole
  const tagR = dialR + 42;
  const [ax, ay] = polar(c.cx, c.cy, 40, dialR + 7);
  const [cx2, cy2] = polar(c.cx, c.cy, 40, tagR - 11);
  g.appendChild(el('line', { x1: ax, y1: ay, x2: cx2, y2: cy2, class: 'badge-lead' }));
  const [bx, by] = polar(c.cx, c.cy, 40, tagR);
  const txt = mode.label;
  const bw = txt.length * 6.4 + 14;
  const bx2 = Math.max(10, Math.min(W - bw - 96, bx - bw / 2));
  g.appendChild(el('rect', { x: bx2, y: by - 10, width: bw, height: 17, class: 'badge-bg' }));
  const bt = el('text', { x: bx2 + 7, y: by + 2.5, class: 'badge-txt' });
  bt.textContent = txt;
  g.appendChild(bt);

  overlay.appendChild(g);
}

// ---------------------------------------------------------------- readouts

function renderBadges() {
  const rows = [];
  const active = (audit && audit.vectors) || [];

  active.forEach((v, i) => {
    rows.push(
      `<div class="badge" style="top:${i * 27}px">` +
      `${v.label}: ${v.pole} <span class="pct">${Math.round(v.realized * 100)}%</span></div>`
    );
  });

  if (audit?.metrics?.mode) {
    const m = audit.metrics.mode;
    rows.push(
      `<div class="badge" style="top:${active.length * 27 + 10}px">` +
      `mode: ${m.label} <span class="pct">${Math.round(m.value * 100)}%</span></div>`
    );
  }
  badgesEl.innerHTML = rows.join('');
}

function renderStatus() {
  const a = audit || {};
  const rate = a.rate ?? 0;
  const lat = a.latency_ms ?? 0;
  const words = a.words ?? 0;
  const tokens = a.tokens ?? 0;
  const c = a.counters || {};
  const bits = [
    `<span>≈ <b>${rate > 0 ? rate.toFixed(0) : '—'}</b> w/s</span>`,
    `<span>≈ <b>${lat > 0 ? lat.toFixed(1) : '—'}</b> ms</span>`,
    `<span><b>${words}</b>/<b>${tokens}</b></span>`,
    `<span>box <b>${c.box ?? 0}</b></span>`,
    `<span>steer <b>${c.steer ?? 0}</b></span>`,
    `<span>pin <b>${c.pin ?? 0}</b></span>`,
    `<span>${generating ? '<span class="red">/ writing</span>' : '/ idle'}</span>`,
  ];
  if (errText) bits.push(`<span class="err">${errText}</span>`);
  bits.push('<span class="grow"></span>');
  bits.push(`<span>${meta.provider || 'mock'} · ${meta.model || 'corpus'}</span>`);
  statusEl.innerHTML = bits.join('');
}

// ---------------------------------------------------------------- dock

function renderDock() {
  $('#dock-note').textContent = meta.note || meta.model || '';

  const list = $('#vec-list');
  const items = vectors.map((v) => {
    const pct = Math.round(Math.abs(v.magnitude) * 100);
    const side = v.magnitude >= 0 ? v.plus : v.minus;
    return `
      <div class="vec" data-id="${v.id}">
        <div class="top"><span>${v.label} → ${side}</span><span><em>${pct}%</em>
          <button data-del="${v.id}">×</button></span></div>
        <div class="poles"><span>${v.plus}</span><span>${v.minus}</span></div>
        <input type="range" min="-100" max="100" value="${Math.round(v.magnitude * 100)}" data-slider="${v.id}" />
      </div>`;
  });
  list.innerHTML = items.join('') || '<div class="empty">no vectors yet — add one below, or select text to steer</div>';

  list.querySelectorAll('input[data-slider]').forEach((input) => {
    input.addEventListener('input', () => {
      send({ cmd: 'vector', action: 'set', id: input.dataset.slider, magnitude: +input.value / 100 });
      const row = input.closest('.vec');
      row.querySelector('.top em').textContent = `${Math.abs(+input.value)}%`;
      row.querySelector('.top span').textContent =
        `${vectors.find((v) => v.id === input.dataset.slider).label} → ${+input.value >= 0 ? 'plus' : 'minus'}`;
    });
  });
  list.querySelectorAll('button[data-del]').forEach((b) => {
    b.addEventListener('click', () => send({ cmd: 'vector', action: 'remove', id: b.dataset.del }));
  });

  const bl = $('#box-list');
  bl.innerHTML = boxes.map((b) => `
    <div class="box" data-id="${b.id}">
      <span title="${b.text}">“${b.text.slice(0, 34)}”</span>
      <input type="range" min="0" max="150" value="${Math.round(b.weight * 100)}" data-boxw="${b.id}" />
      <button data-boxdel="${b.id}">×</button>
    </div>`).join('') || '<div class="empty">select text in the prose to pin attention</div>';

  bl.querySelectorAll('input[data-boxw]').forEach((input) => {
    input.addEventListener('input', () =>
      send({ cmd: 'box', action: 'weight', id: input.dataset.boxw, weight: +input.value / 100 }));
  });
  bl.querySelectorAll('button[data-boxdel]').forEach((b) => {
    b.addEventListener('click', () => send({ cmd: 'box', action: 'remove', id: b.dataset.boxdel }));
  });
}

// ---------------------------------------------------------------- loop

function schedule() {
  dirty = true;
}

function frame() {
  if (dirty) {
    dirty = false;
    renderText();
    measure();
    renderRail();
    drawOverlay();
    renderBadges();
    renderStatus();
    paintClasses();
  }
  requestAnimationFrame(frame);
}

// ---------------------------------------------------------------- input

document.addEventListener('keydown', (e) => {
  if (e.target.matches('input, textarea')) return;
  if (e.code === 'Space') {
    e.preventDefault();
    send({ cmd: 'generate', tokens: 150 });
  } else if (e.key === 'Tab') {
    e.preventDefault();
    dockEl.classList.toggle('hidden');
  } else if (e.key === 'r') {
    send({ cmd: 'reset', seed: 'keeper' });
  } else if (e.key === '.') {
    send({ cmd: 'stop' });
  }
});

proseEl.addEventListener('mouseup', () => {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || !sel.rangeCount) return;
  const range = sel.getRangeAt(0);
  const hit = words.filter((w) => {
    try { return range.intersectsNode(w); } catch { return false; }
  });
  if (!hit.length) return;
  const start = +hit[0].dataset.s;
  const end = +hit[hit.length - 1].dataset.e;
  const text = doc.slice(start, end).trim();
  if (!text) return;
  send({ cmd: 'box', action: 'add', start, end, text, weight: 0.75 });
  sel.removeAllRanges();
});

proseEl.addEventListener('contextmenu', (e) => {
  e.preventDefault();
  const w = e.target.closest('.w');
  if (!w) return;
  const at = +w.dataset.s;
  const box = boxes.find((b) => at >= b.start && at < b.end);
  if (box) send({ cmd: 'box', action: 'remove', id: box.id });
});

$('#vec-add').addEventListener('submit', (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  send({
    cmd: 'vector', action: 'add',
    label: f.get('label'), plus: f.get('plus'), minus: f.get('minus'), magnitude: 0,
  });
});

$('#autogen').addEventListener('change', (e) => { autogen = e.target.checked; });
$('#reset').addEventListener('click', () => send({ cmd: 'reset', seed: 'keeper' }));

window.addEventListener('resize', schedule);

// boot
renderText();
measure();
renderRail();
drawOverlay();
renderStatus();
requestAnimationFrame(frame);
connect();
