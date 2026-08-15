/* Minimal DOM, real renderer. Loads the site script from site/index.html,
   boots it, drives every text command, and MEASURES the rendered rows —
   the page's width invariant broke once as arithmetic and once as a glyph,
   and both were only ever caught by measuring.

   Run: node tests/site_harness.js site/index.html
   Exit 0 = every panel row is exactly 78 columns and carries no
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

// The POST chain steps through zero-delay timeouts; measure after it drains.
setTimeout(() => {
  const og = global.__og;
  if (!og) { console.error('window.__og hook missing'); process.exit(2); }
  for (const c of ['help', 'why', 'board', 'install', 'providers',
                   'privacy', 'doctor', 'open', 'donate', 'ver', 'mem', 'dir']) {
    og.run(c);
  }

  const banned = /[—–“”→▟▛▎▋▁▂▃▄▅▆▇]/;
  let rows = 0, bad = [];
  for (const child of og.out.children) {
    if (!/\bpan\b/.test(child.className)) continue;
    for (const r of child.children) {
      const t = r.textContent;
      rows++;
      if (t.length !== 78) bad.push(`len ${t.length}: ${JSON.stringify(t)}`);
      const g = t.match(banned);
      if (g) bad.push(`glyph ${JSON.stringify(g[0])}: ${JSON.stringify(t)}`);
    }
  }
  if (rows < 100) bad.push(`only ${rows} panel rows measured - the drive did not run`);
  if (bad.length) {
    console.error(`FAIL: ${bad.length} problem(s) across ${rows} rows`);
    for (const b of bad.slice(0, 20)) console.error('  ' + b);
    process.exit(1);
  }
  console.log(`OK: ${rows} panel rows, every one exactly 78 columns, no fallback-risk glyphs`);
  process.exit(0);
}, 150);
