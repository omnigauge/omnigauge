/* Minimal DOM, real renderer. Loads the site script from site/index.html,
   boots it, drives every text command IN BOTH MODES, and MEASURES the
   rendered rows - the page's width invariant broke once as arithmetic and
   once as a glyph, and both were only ever caught by measuring.

   Desktop is a 78-column grid; mobile is 42. Panel rows must measure the
   grid exactly; loose lines must fit inside it. The one exemption is the
   `cmd` class - a copyable string longer than the mobile grid (an install
   command, the donation address) that CSS soft-wraps while the text stays
   one selectable line. Those are exempt from width, never from glyphs.

   Run: node tests/site_harness.js site/index.html
   Exit 0 = every measured row obeys its mode's grid and carries no
   fallback-risk glyph. Nonzero = the failure list is on stdout. */
'use strict';
const fs = require('fs');

const html = fs.readFileSync(process.argv[2] || 'site/index.html', 'utf8');
const m = html.match(/<script>([\s\S]*)<\/script>/);
if (!m) { console.error('no <script> block found'); process.exit(2); }

function makeEl(tag) {
  const e = {
    tag, className: '', style: {}, dataset: {}, value: '',
    children: [], _html: '', parent: null,
    set innerHTML(v) { this._html = String(v); this.children = []; },
    get innerHTML() { return this._html; },
    set textContent(v) {
      this._html = String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;');
      this.children = [];
    },
    get textContent() {
      let t = this._html.replace(/<[^>]*>/g, '')
        .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
        .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&');
      return t + this.children.map(c => c.textContent).join('');
    },
    appendChild(c) { this.children.push(c); c.parent = this; return c; },
    remove() {}, focus() {}, click() {}, blur() {},
    addEventListener() {}, removeEventListener() {},
    closest() { return null; }, hasAttribute() { return false; },
    querySelector() { return null; }, querySelectorAll() { return []; },
    getBoundingClientRect() { return { width: 4680, left: 0, bottom: 20 }; },
    setAttribute() {},
    get isConnected() { return true; },
  };
  e.classList = {
    add(c) { e.className += ' ' + c; },
    remove() {}, contains() { return false; },
  };
  return e;
}

const ids = {};
global.document = {
  getElementById: id => (ids[id] = ids[id] || makeEl('div')),
  createElement: t => makeEl(t),
  addEventListener() {}, removeEventListener() {},
  documentElement: { clientWidth: 1200, style: { setProperty() {} } },
  body: { appendChild(c) { return c; }, removeChild() {} },
  hidden: false, fonts: undefined,
  querySelectorAll() { return []; },
  get activeElement() { return makeEl('div'); },
};
global.window = global;
global.matchMedia = () => ({ matches: true });   // reduced motion: boot instantly
global.addEventListener = () => {};
global.removeEventListener = () => {};
global.setInterval = () => 0;                     // clock/saver must not hold the process
// node's own navigator/performance are getter-only globals; shadow them
Object.defineProperty(global, 'navigator', { configurable: true, value:
  { clipboard: { writeText: () => ({ then: f => { if (f) f(); } }) } } });
Object.defineProperty(global, 'performance', { configurable: true, value:
  { now: () => 0 } });
global.requestAnimationFrame = () => {};
global.getComputedStyle = () => ({ paddingLeft: '8px' });
global.open = () => {};

eval(m[1]);

const CMDS = ['help', 'why', 'board', 'install', 'providers', 'legend',
              'privacy', 'doctor', 'open', 'donate', 'ver', 'mem', 'dir',
              'copy', 'wallet', 'exit'];

// The ban covers EVERY emitted line, loose ones included - checking only
// panel rows left five survivors, one of them in a panel header.
const banned = /[—–“”→▟▛▎▋▁▂▃▄▅▆▇]/;

function measure(og, label, width, bad) {
  let rows = 0, loose = 0;
  for (const child of og.out.children) {
    if (/\bpan\b/.test(child.className)) {
      for (const r of child.children) {
        const t = r.textContent;
        rows++;
        if (t.length !== width)
          bad.push(`${label} len ${t.length} (want ${width}): ${JSON.stringify(t)}`);
        const g = t.match(banned);
        if (g) bad.push(`${label} glyph ${JSON.stringify(g[0])}: ${JSON.stringify(t)}`);
      }
    } else {
      const t = child.textContent;
      loose++;
      const g = t.match(banned);
      if (g) bad.push(`${label} glyph ${JSON.stringify(g[0])} in loose line: ${JSON.stringify(t)}`);
      if (!/\bcmd\b/.test(child.className) && t.trimEnd().length > width)
        bad.push(`${label} loose len ${t.trimEnd().length} > ${width}: ${JSON.stringify(t)}`);
    }
  }
  if (rows < 100) bad.push(`${label}: only ${rows} panel rows measured - the drive did not run`);
  return { rows, loose };
}

// The POST chain steps through zero-delay timeouts; measure after it drains.
setTimeout(() => {
  const og = global.__og;
  if (!og) { console.error('window.__og hook missing'); process.exit(2); }
  const bad = [];

  for (const c of CMDS) og.run(c);
  if (og.W() !== 78) bad.push(`desktop mode W=${og.W()}, expected 78`);
  const d = measure(og, 'desktop', 78, bad);

  og.mode(true);
  if (og.W() !== 42) bad.push(`mobile mode W=${og.W()}, expected 42`);
  for (const c of CMDS) og.run(c);
  const mo = measure(og, 'mobile', 42, bad);
  og.mode(false);

  if (bad.length) {
    console.error(`FAIL: ${bad.length} problem(s) across desktop ${d.rows}+${d.loose} / mobile ${mo.rows}+${mo.loose} rows`);
    for (const b of bad.slice(0, 25)) console.error('  ' + b);
    process.exit(1);
  }
  console.log(`OK: desktop ${d.rows} panel rows at 78 cols, mobile ${mo.rows} panel rows at 42 cols; ` +
              `${d.rows + d.loose + mo.rows + mo.loose} total lines free of fallback-risk glyphs`);
  process.exit(0);
}, 150);
