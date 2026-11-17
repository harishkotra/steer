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
let revealTop = null; // set when the user clicks a claim: hold that part of the text still
let audit = null;
let meta = {};
let vectors = [];
let boxes = [];
let pins = [];
let generating = false;
let autogen = false; // the reader decides when the next paragraph happens
let ws = null;
let dirty = true;
let errText = '';

const MAX_DOC = 14000;

// ---------------------------------------------------------------- socket

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    // one short opening paragraph, once, so the page is alive on arrival
    if (!doc.trim()) setTimeout(() => send({ cmd: 'generate', tokens: 90 }), 600);
  };

  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === 'init') {
      doc = msg.doc;
      meta = msg.meta;
      audit = msg.audit;
      vectors = msg.vectors || (msg.audit && msg.audit.vectors) || vectors;
      renderDock();
      // the dials are the point of the app: they are on screen unless the
      // reader deliberately folds them away with Tab
      if (!/[?&]fold=1/.test(location.search)) dockEl.classList.remove('hidden');
      schedule();
    } else if (msg.type === 'delta') {
      revealTop = null;
      doc += msg.text;
      if (doc.length > MAX_DOC) doc = doc.slice(-10000);
      schedule();
    } else if (msg.type === 'vectors') {
      vectors = msg.vectors || vectors;
      renderDock();
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
      // never start the next paragraph on its own during a first visit: the
      // dials arrive mid-stream and anything written before you touch them is
      // evidence that the dial did nothing
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
  const need = Math.max(0, h - proseEl.clientHeight + lh * 1.6);
  shift = Math.ceil(need / lh) * lh;
  // a click on a claim parks the view on that sentence until the next write
  if (revealTop !== null) shift = Math.min(shift, revealTop);
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
      // 34 made half the rail invisible on a laptop screen; the bar has to
      // carry the reading, not the caption
      const shade = Math.round(62 + v * 148);
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

  // the vertical guide is a connector to the instrument, not a page divider:
  // a full-height rule down the middle of the text reads as a layout bug
  overlay.appendChild(el('line', { x1: ix, y1: Math.round(band.top - 150), x2: ix, y2: Math.round(band.top - 16), class: 'cross' }));
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
  const rollBottom = rollBox.bottom - sbox.top;
  for (const a of anchors.slice(0, 9)) {
    overlay.appendChild(el('line', {
      // leaders start below the roll: a dashed line through the paragraph
      // looks like the text is being crossed out
      x1: a.x, y1: Math.max(a.y, rollBottom), x2: ix, y2: cy - 4, class: 'leader',
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

  // what this ring is, in words: it describes the passage, it is not a control
  const cap = el('text', { x: c.cx, y: c.cy - rMax * 1.28, class: 'chart-key', 'text-anchor': 'middle' });
  cap.textContent = 'the shape of the story so far';
  g.appendChild(cap);

  for (const deg of [104, 122, 142, 162, 186, 208, 228, 250, 272]) {
    const [x0, y0] = polar(c.cx, c.cy, deg, rMax * 0.13);
    const [x1, y1] = polar(c.cx, c.cy, deg, rMax * 0.86);
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
  label(102, rMax * 0.5, 'dialogue', 'start', 'chart-key', 4);

  // the tag labels the arc from outside it, on a short leader, so the arc reads whole
  const tagR = dialR + 54;
  const [ax, ay] = polar(c.cx, c.cy, 40, dialR + 7);
  const [cx2, cy2] = polar(c.cx, c.cy, 40, tagR - 11);
  // lift the chip clear of the verification ledger below the chart
  const tagDy = 0;
  g.appendChild(el('line', { x1: ax, y1: ay, x2: cx2, y2: cy2 + tagDy, class: 'badge-lead' }));
  const [bx, byRaw] = polar(c.cx, c.cy, 40, tagR);
  const by = byRaw + tagDy;
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
  // the dock already lists each dial and its strength; the only overlay worth
  // keeping is the mode the passage is running in
  const m = audit?.metrics?.mode;
  badgesEl.innerHTML = m
    ? `<div class="badge">mode: ${m.label} <span class="pct">${Math.round(m.value * 100)}%</span></div>`
    : '';
}

function renderControls() {
  const go = $('#go');
  const halt = $('#halt');
  if (!go || !halt) return;
  go.hidden = generating;
  halt.hidden = !generating;
  go.textContent = doc.length < 200 ? 'start writing' : 'write more';
}

function renderStatus() {
  const a = audit || {};
  const rate = a.rate ?? 0;
  const lat = a.latency_ms ?? 0;
  const words = a.words ?? 0;
  const tokens = a.tokens ?? 0;
  const c = a.counters || {};
  const bits = [
    `<span><b>${words}</b> words</span>`,
    `<span><b>${c.steer ?? 0}</b> dials</span>`,
    `<span><b>${c.box ?? 0}</b> attention box${(c.box ?? 0) === 1 ? '' : 'es'}</span>`,
    `<span>${rate > 0 ? rate.toFixed(0) : '—'} w/s</span>`,
    `<span>${lat > 0 ? lat.toFixed(1) : '—'} ms</span>`,
    `<span>${generating ? '<span class="red">writing…</span>' : 'idle'}</span>`,
  ];
  if (errText) bits.push(`<span class="err">${errText}</span>`);
  bits.push('<span class="grow"></span>');
  bits.push(`<span>${meta.activation ? 'real activations' : 'prompt-compiled'} · ${meta.provider || 'mock'} · ${meta.model || 'corpus'}</span>`);
  bits.push('<span class="by">idea: <a href="https://github.com/chuanqisun/spaceship" target="_blank" rel="noopener">Spaceship IDE</a> by <a href="https://chuanqisun.com" target="_blank" rel="noopener">Chuanqi Sun</a> · built by <a href="https://harishkotra.me" target="_blank" rel="noopener">Harish Kotra</a> · <a href="https://dailybuild.xyz" target="_blank" rel="noopener">other builds</a></span>');
  statusEl.innerHTML = bits.join('');
}

// ---------------------------------------------------------------- dock

function renderDock() {
  $('#dock-note').textContent = 'mined from the passage';

  const list = $('#vec-list');
  const items = vectors.map((v) => {
    const pct = Math.round(Math.abs(v.magnitude) * 100);
    const side = v.magnitude >= 0 ? v.plus : v.minus;
    return `
      <div class="vec" data-id="${v.id}">
        <div class="top"><span>${v.label} → ${side}</span><span><em>${pct}%</em>
          <button data-del="${v.id}" title="remove this dial">×</button></span></div>
        <div class="poles"><span>${v.plus}</span><span>${v.minus}</span></div>
        <div class="src" data-sentence="${esc(v.source || '')}" title="click to show this sentence in your text">${v.attested === false ? '<em title="the opposite end never appears in your text, so this end was guessed">guessed</em> · ' : ''}${v.source ? 'found in: ' + clip(v.source, 108) : '<em>you added this</em>'}</div>
        <input type="range" min="-100" max="100" value="${Math.round(v.magnitude * 100)}" data-slider="${v.id}" />
      </div>`;
  });
  list.innerHTML = items.join('') || '<div class="empty">no dials yet — write a few sentences and they get mined from your text</div>';

  list.querySelectorAll('input[data-slider]').forEach((input) => {
    input.addEventListener('input', () => {
      send({ cmd: 'vector', action: 'set', id: input.dataset.slider, magnitude: +input.value / 100 });
      const row = input.closest('.vec');
      row.querySelector('.top em').textContent = `${Math.abs(+input.value)}%`;
      const vv = vectors.find((v) => v.id === input.dataset.slider);
      if (vv) row.querySelector('.top span').textContent = `${vv.label} → ${+input.value >= 0 ? vv.plus : vv.minus}`;
    });
  });
  list.querySelectorAll('.src[data-sentence]').forEach((el) => {
    el.addEventListener('click', () => revealSentence(el.dataset.sentence));
  });

  list.querySelectorAll('button[data-del]').forEach((b) => {
    b.addEventListener('click', () => send({ cmd: 'vector', action: 'remove', id: b.dataset.del }));
  });

  const bl = $('#box-list');
  const lifts = {};
  (audit && audit.attention ? audit.attention : []).forEach((a) => { lifts[a.id] = a; });
  bl.innerHTML = boxes.map((b) => {
    const l = lifts[b.id];
    const tag = !l
      ? ''
      : l.lift >= 1.15
        ? `<em class="held">×${l.lift}</em>`
        : l.lift < 0.05
          ? '<em class="weak">no pull yet</em>'
          : `<em class="weak">×${l.lift}</em>`;
    return `
    <div class="box" data-id="${b.id}">
      <span title="${b.text}">“${b.text.slice(0, 30)}” ${tag}</span>
      <input type="range" min="0" max="150" value="${Math.round(b.weight * 100)}" data-boxw="${b.id}" />
      <button data-boxdel="${b.id}">×</button>
    </div>`;
  }).join('') || '<div class="empty">select text in the prose to pin attention</div>';

  bl.querySelectorAll('input[data-boxw]').forEach((input) => {
    input.addEventListener('input', () =>
      send({ cmd: 'box', action: 'weight', id: input.dataset.boxw, weight: +input.value / 100 }));
  });
  bl.querySelectorAll('button[data-boxdel]').forEach((b) => {
    b.addEventListener('click', () => send({ cmd: 'box', action: 'remove', id: b.dataset.boxdel }));
  });
}

// ---------------------------------------------------------------- loop

function clip(text, n) {
  const t = String(text || '').replace(/\s+/g, ' ').trim();
  if (t.length <= n) return esc(t);
  const cut = t.slice(0, n);
  const at = cut.lastIndexOf(' ');
  return esc(at > n * 0.6 ? cut.slice(0, at) : cut) + '…';
}

function esc(t) {
  return String(t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function renderLedger() {
  const box = $('#ledger');
  if (!box) return;
  const v = audit && audit.verification;
  if (!v || !v.claims || !v.claims.length) {
    box.innerHTML = '';
    return;
  }
  const rows = v.claims.slice(-3).map((c) => `
    <div class="row ${c.realized ? 'ok' : 'miss'}" data-sentence="${esc(c.sentence)}" title="click to show this sentence in the text">
      <span class="mk">${c.realized ? '✓' : '·'}</span>
      <span class="vx">${c.realized ? esc(c.vector) + ' → ' + esc(c.pole) : 'unclaimed'}</span>
      <span class="sh" title="how much of this sentence leans the dial's way">${c.share.toFixed(2)}</span>
      <span class="tx">${esc(c.sentence)}</span>
    </div>`).join('');
  box.innerHTML =
    `<header>did the dials land? <em>${esc(v.note)}</em></header>${rows}` +
    `<div class="foot">score: how much of that sentence leans the dial's way · 1.00 = all of it</div>`;

  box.querySelectorAll('.row[data-sentence]').forEach((row) => {
    row.addEventListener('click', () => revealSentence(row.dataset.sentence));
  });
}

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
    renderLedger();
    renderControls();
    renderStatus();
    paintClasses();
  }
  requestAnimationFrame(frame);
}

// ---------------------------------------------------------------- reveal

// a claim is only useful if you can see the sentence it is talking about
function revealSentence(sentence) {
  const probe = sentence.trim().split(/\s+/).slice(0, 4).join(' ').toLowerCase();
  if (!probe) return;
  const at = doc.toLowerCase().indexOf(probe);
  if (at < 0) return;
  const hit = words.filter((w) => +w.dataset.s >= at && +w.dataset.s < at + sentence.length);
  if (!hit.length) return;
  revealTop = Math.max(0, hit[0].offsetTop - proseEl.clientHeight * 0.45);
  hit.forEach((w) => w.classList.add('flash'));
  measure();
  setTimeout(() => hit.forEach((w) => w.classList.remove('flash')), 2200);
}

// ---------------------------------------------------------------- input

document.addEventListener('keydown', (e) => {
  if (e.target.matches('input, textarea')) return;
  // the blind-test panel owns the keyboard while it is open, or space would
  // start writing behind the question
  if (!document.querySelector('#blind').classList.contains('hidden')) return;
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
$('#go').addEventListener('click', () => send({ cmd: 'generate', tokens: 150 }));
$('#halt').addEventListener('click', () => send({ cmd: 'stop' }));

// the first thing anyone needs is "what is this and where do I press"
const tourEl = $('#tour');
function showTour() { tourEl.classList.remove('hidden'); }
function hideTour() {
  tourEl.classList.add('hidden');
  try { localStorage.setItem('steer.tour', '1'); } catch (e) { /* private mode */ }
}
$('#tourbtn').addEventListener('click', showTour);
$('#tourdone').addEventListener('click', hideTour);
tourEl.addEventListener('click', (e) => { if (e.target === tourEl) hideTour(); });
try {
  const seen = localStorage.getItem('steer.tour');
} catch (e) { /* ignore */ }
let seenTour = false;
try { seenTour = localStorage.getItem('steer.tour') === '1'; } catch (e) { /* ignore */ }
if (!seenTour || location.search.includes('tour=1')) showTour();

// ---------- blind test ----------
// Two futures from the same passage, one of them steered. The server keeps the
// answer until a pick comes back, so there is nothing to cheat with here: the
// page only ever holds two paragraphs of prose.
const blindEl = $('#blind');
const blindOut = $('#blind-out');
const blindAgain = $('#blindagain');
let blindRound = null;
const tally = { hit: 0, n: 0 };

function blindSide(name) { return blindEl.querySelector(`.side[data-side="${name}"]`); }

function setSide(name, text, loading) {
  const node = blindSide(name);
  node.classList.remove('done', 'steered', 'wrong', 'picked');
  const body = node.querySelector('.body');
  body.classList.toggle('loading', !!loading);
  body.textContent = text;
  const pick = node.querySelector('.pick');
  pick.disabled = !!loading;
  pick.textContent = 'pick ' + name.toUpperCase();
}

function tallyText() {
  $('#blind-tally').textContent = tally.n
    ? `you called ${tally.hit} of ${tally.n} so far`
    : 'no guesses yet — the answer sits on the server';
}

function blindBusy(text) {
  setSide('left', text, true);
  setSide('right', '', true);
}

async function deal() {
  blindEl.classList.remove('hidden');
  blindOut.hidden = true;
  blindAgain.hidden = true;
  blindRound = null;
  blindBusy('writing two futures from the same words…');
  // a blind test over a passage that is still growing is not a fair test:
  // stop the stream, let the server settle, then deal
  if (generating) {
    send({ cmd: 'stop' });
    await new Promise((r) => setTimeout(r, 400));
  }
  let data = null;
  // the stop is asynchronous on the server; give it a few beats before giving up
  for (let attempt = 0; attempt < 5; attempt += 1) {
    try {
      const res = await fetch('/api/blind', { method: 'POST' });
      data = await res.json();
    } catch (e) { data = null; }
    if (data && !data.error) break;
    if (data && data.error && !/sit still/.test(data.error)) break;
    await new Promise((r) => setTimeout(r, 700));
  }
  if (!data || data.error) {
    blindBusy((data && data.error) || 'the server did not answer.');
    return;
  }
  blindRound = data;
  setSide('left', data.sides.left, false);
  setSide('right', data.sides.right, false);
  tallyText();
}

async function guess(side) {
  if (!blindRound) return;
  blindBusy('reading both back…');
  let r = null;
  try {
    const res = await fetch(`/api/blind/${blindRound.round}/${side}`, { method: 'POST' });
    r = await res.json();
  } catch (e) { /* server gone */ }
  if (!r || r.error) {
    blindBusy((r && r.error) || 'the server did not answer.');
    return;
  }
  tally.n += 1;
  if (r.correct) tally.hit += 1;

  // put the text back before painting verdicts on it
  for (const name of ['left', 'right']) setSide(name, r.sides[name].text, false);

  const toward = (name) => r.sides[name].toward;
  for (const name of ['left', 'right']) {
    const node = blindSide(name);
    node.classList.add('done');
    if (name === r.answer) node.classList.add('steered');
    if (name === r.pick && !r.correct) node.classList.add('wrong');
  }

  const poleName = r.axis.pole;
  const a = toward(r.answer);
  const b = toward(r.answer === 'left' ? 'right' : 'left');
  const margin = Math.abs(a - b);
  const words = margin > 0.3 ? 'a wide gap' : margin > 0.12 ? 'a real gap' : 'barely a gap';
  const pct = (x) => `${Math.round(x * 100)}%`;

  blindOut.innerHTML = `
    <p>the dial was <b class="ok">${esc(r.axis.label)} → ${esc(poleName)}</b>, strength ${r.axis.strength.toFixed(2)}.
    ${r.correct ? `<b>you picked it — the ${r.answer} card.</b>` : `<b>it was the ${r.answer} card.</b>`}
    ${esc(words)} between the two texts.</p>
    <div class="metrics">
      <div class="m">the steered one (${r.answer}) · ${pct(a)} toward ${esc(poleName)}
        <div class="bar"><i style="width:${Math.round(a * 100)}%"></i></div></div>
      <div class="m">the plain one (${r.answer === 'left' ? 'right' : 'left'}) · ${pct(b)} toward ${esc(poleName)}
        <div class="bar"><i style="width:${Math.round(b * 100)}%"></i></div></div>
    </div>
    <p class="m">same words in, same model, one dial. this is the only difference the audit can find.</p>`;
  blindOut.hidden = false;
  blindAgain.hidden = false;
  tallyText();
}

$('#blindbtn').addEventListener('click', () => {
  // a tally carried over from a closed panel reads like a pre-filled result
  tally.hit = 0;
  tally.n = 0;
  tallyText();
  deal();
});
$('#blindagain').addEventListener('click', deal);
$('#blindclose').addEventListener('click', () => blindEl.classList.add('hidden'));
blindEl.addEventListener('click', (e) => { if (e.target === blindEl) blindEl.classList.add('hidden'); });
blindEl.querySelectorAll('.pick').forEach((btn) => {
  btn.addEventListener('click', () => guess(btn.closest('.side').dataset.side));
});
window.addEventListener('keydown', (e) => {
  if (blindEl.classList.contains('hidden')) return;
  if (e.key === 'Escape') { blindEl.classList.add('hidden'); return; }
  // the panel is a question: L and R answer it while it is open
  if (!blindRound || !blindOut.hidden) return;
  const k = e.key.toLowerCase();
  if (k === 'l' || k === 'arrowleft') guess('left');
  if (k === 'r' || k === 'arrowright') guess('right');
});

window.addEventListener('resize', schedule);

// boot
renderText();
measure();
renderRail();
drawOverlay();
renderStatus();
requestAnimationFrame(frame);
connect();
