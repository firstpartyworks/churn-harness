// Play-test generated one-file games headless, desktop (mouse) and phone (touch), with a video of each run.
//   node playtest.js <dir> [filter]     (needs the playwright package)
// Writes <dir>/playtest/<game>-<device>.webm and <dir>/playtest/report.json.
// Breakout: does the paddle follow the pointer / a finger drag, is the game animating, does the score move.
// Tower defense: after placing towers and sending a wave, do enemies move, does gold/kills rise, do lives fall.
const { chromium, devices } = require('playwright');
const fs = require('fs');
const path = require('path');

const DEVICES = { desktop: { viewport: { width: 1280, height: 800 } }, phone: devices['Pixel 7'] };
const START = /^(start|begin|play|press to play|enter|descend|insert coin|new game|launch|go)\b|begin the|enter the|start game/i;
const WAVE = /send wave|start wave|next wave|begin wave|call wave|wave \d+$|^wave$|start$/i;

// Downsampled grayscale of the largest canvas (or the whole page if none), for change and paddle detection.
const SIG = () => {
  const cs = [...document.querySelectorAll('canvas')].sort((a, b) => b.width * b.height - a.width * a.height);
  const c = cs[0];
  if (!c) return null;
  const W = 96, H = 64, o = document.createElement('canvas');
  o.width = W; o.height = H;
  const g = o.getContext('2d');
  try { g.drawImage(c, 0, 0, W, H); } catch (e) { return null; }
  const d = g.getImageData(0, 0, W, H).data, out = [];
  for (let i = 0; i < d.length; i += 4) out.push((d[i] + d[i + 1] + d[i + 2]) / 3);
  const r = c.getBoundingClientRect();
  return { px: out, W, H, rect: { x: r.x, y: r.y, w: r.width, h: r.height } };
};
const diff = (a, b) => a && b ? a.px.reduce((s, v, i) => s + Math.abs(v - b.px[i]), 0) / a.px.length : null;
// Brightness centroid of the bottom strip (where the paddle lives), 0..1 across the canvas.
const paddleX = (s) => {
  if (!s) return null;
  const { px, W, H } = s, y0 = Math.floor(H * 0.78), cols = new Array(W).fill(0);
  for (let y = y0; y < H; y++) for (let x = 0; x < W; x++) cols[x] += px[y * W + x];
  const sorted = [...cols].sort((a, b) => a - b), med = sorted[W >> 1];
  let sw = 0, sx = 0;
  cols.forEach((v, x) => { const w = Math.max(0, v - med); sw += w; sx += w * x; });
  return sw > 0 ? sx / sw / W : null;
};
// Numbers next to the usual HUD words in the page text (canvas-drawn HUDs read as unknown).
const HUD = () => {
  const num = (s) => { const m = (s || '').replace(/,/g, '').match(/-?\d+/); return m ? Number(m[0]) : null; };
  const byId = (re) => {
    for (const e of document.querySelectorAll('[id],[class]')) {
      const tag = (e.id + ' ' + (typeof e.className === 'string' ? e.className : '')).toLowerCase();
      if (re.test(tag) && e.children.length <= 2 && (e.innerText || '').length < 24) { const v = num(e.innerText); if (v != null) return v; }
    }
    return null;
  };
  const t = document.body.innerText.replace(/\s+/g, ' ');
  const pick = (re) => { const m = t.match(re); return m ? Number(m[1].replace(/,/g, '')) : null; };
  return {
    score: byId(/\bscore/) ?? pick(/score\D{0,12}?([\d,]+)/i),
    lives: byId(/\blives?\b|\bhp\b|health/) ?? pick(/(?:lives?|❤️?|♥)\D{0,12}?(\d+)/i),
    gold: byId(/\bgold|\bcoins?|money|cash/) ?? pick(/(?:gold|coins?|💰|🪙)\D{0,12}?([\d,]+)/i),
    kills: byId(/kills?|slain|felled/) ?? pick(/(?:kills?|slain|felled|killed)\D{0,12}?(\d+)/i),
    wave: byId(/\bwave(?!btn|-?button)/) ?? pick(/(?:wave|🌊)\D{0,6}?(\d+)/i),
  };
};

async function clickButton(page, re) {
  const btns = page.locator('button, [role=button], .btn, a');
  const n = await btns.count();
  for (let i = 0; i < n; i++) {
    const b = btns.nth(i);
    const txt = ((await b.innerText().catch(() => '')) || '').trim().split('\n')[0];
    if (re.test(txt) && await b.isVisible().catch(() => false)) {
      await b.click({ timeout: 1500 }).catch(() => {});
      return txt;
    }
  }
  return null;
}

async function tapOrClick(page, dev, x, y) {
  if (dev === 'phone') await page.touchscreen.tap(x, y); else await page.mouse.click(x, y);
}

async function drag(page, cdp, dev, x0, x1, y) {
  if (dev === 'desktop') {
    await page.mouse.move(x0, y);
    await page.mouse.move(x1, y, { steps: 12 });
    return;
  }
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: x0, y }] });
  for (let i = 1; i <= 12; i++)
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: x0 + (x1 - x0) * i / 12, y }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
}

async function breakout(page, cdp, dev, r) {
  let s0 = await page.evaluate(SIG);
  if (!s0) { r.notes.push('no canvas'); return; }
  const c = s0.rect, cx = c.x + c.w / 2, by = c.y + c.h * 0.9;
  r.start_button = await clickButton(page, START);
  await tapOrClick(page, dev, cx, c.y + c.h * 0.5);
  if (dev === 'desktop') await page.keyboard.press('Space');
  await page.waitForTimeout(600);
  const pos = {};
  for (const [k, fx] of [['left', 0.15], ['right', 0.85], ['left2', 0.2]]) {
    await drag(page, cdp, dev, c.x + c.w * (k === 'right' ? 0.2 : 0.8), c.x + c.w * fx, by);
    await page.waitForTimeout(450);
    pos[k] = paddleX(await page.evaluate(SIG));
  }
  r.paddle = pos;
  r.paddle_follows = pos.left != null && pos.right != null && pos.left2 != null &&
    pos.right - pos.left > 0.25 && pos.right - pos.left2 > 0.25;
  if (dev === 'desktop') await page.keyboard.press('Space');
  await tapOrClick(page, dev, cx, c.y + c.h * 0.5);
  const h0 = await page.evaluate(HUD), a = await page.evaluate(SIG);
  // keep the paddle sweeping so the ball has something to hit
  for (let i = 0; i < 10; i++) {
    await drag(page, cdp, dev, c.x + c.w * (i % 2 ? 0.8 : 0.2), c.x + c.w * (i % 2 ? 0.2 : 0.8), by);
    await page.waitForTimeout(500);
  }
  const b = await page.evaluate(SIG), h1 = await page.evaluate(HUD);
  r.animating = diff(a, b) > 1.0;
  r.hud_before = h0; r.hud_after = h1;
  r.score_moved = h0.score != null && h1.score != null ? h1.score !== h0.score : null;
}

async function towerDefense(page, cdp, dev, r) {
  r.start_button = await clickButton(page, START);
  await page.waitForTimeout(600);
  r.start_button2 = await clickButton(page, START);
  let s = await page.evaluate(SIG);
  if (!s) { r.notes.push('no canvas'); return; }
  const c = s.rect, h0 = await page.evaluate(HUD);
  // pick the cheapest-looking tower (first shop entry or key 1), then tap a spread of points
  const shop = page.locator('[data-k], [data-type], [data-tower], .tower-btn, .shop button, #shop > *, .arsenal *[class*=tower]').first();
  if (await shop.count()) await shop.click({ timeout: 1000 }).catch(() => {});
  else if (dev === 'desktop') await page.keyboard.press('1');
  for (const [fx, fy] of [[0.3, 0.3], [0.5, 0.5], [0.7, 0.4], [0.4, 0.7], [0.6, 0.2], [0.2, 0.55], [0.8, 0.7]]) {
    await tapOrClick(page, dev, c.x + c.w * fx, c.y + c.h * fy);
    await page.waitForTimeout(250);
  }
  const hBuilt = await page.evaluate(HUD);
  r.gold_spent = h0.gold != null && hBuilt.gold != null ? h0.gold - hBuilt.gold : null;
  r.wave_button = await clickButton(page, WAVE);
  if (!r.wave_button && dev === 'desktop') await page.keyboard.press('Space');
  const a = await page.evaluate(SIG);
  await page.waitForTimeout(4000);
  const b = await page.evaluate(SIG);
  r.enemies_moving = diff(a, b) > 0.6;
  await page.waitForTimeout(36000);
  const h1 = await page.evaluate(HUD);
  r.hud_start = h0; r.hud_built = hBuilt; r.hud_end = h1;
  r.kills_rose = h1.kills != null && hBuilt.kills != null ? h1.kills > hBuilt.kills : null;
  r.gold_rose = h1.gold != null && hBuilt.gold != null ? h1.gold > hBuilt.gold : null;
  r.lives_fell = h1.lives != null && hBuilt.lives != null ? h1.lives < hBuilt.lives : null;
  r.wave_advanced = h1.wave != null && hBuilt.wave != null ? h1.wave > hBuilt.wave : null;
}

(async () => {
  const dir = path.resolve(process.argv[2]);
  const filter = process.argv[3] || '';
  const out = path.join(dir, 'playtest');
  fs.mkdirSync(out, { recursive: true });
  const files = fs.readdirSync(dir).filter(f => f.endsWith('.html') && f.includes(filter)).sort();
  const browser = await chromium.launch();
  const report = fs.existsSync(path.join(out, 'report.json')) ? JSON.parse(fs.readFileSync(path.join(out, 'report.json'))) : {};
  for (const f of files) {
    const genre = /tower|defen/i.test(f) ? 'towerdefense' : 'breakout';
    for (const [dev, opts] of Object.entries(DEVICES)) {
      const key = `${f.replace(/\.html$/, '')}-${dev}`;
      const ctx = await browser.newContext({ ...opts, recordVideo: { dir: out, size: opts.viewport } });
      const page = await ctx.newPage();
      const r = { file: f, device: dev, genre, errors: [], notes: [] };
      page.on('pageerror', e => r.errors.push(String(e.message).slice(0, 160)));
      const cdp = await ctx.newCDPSession(page);
      try {
        await page.goto('file://' + path.join(dir, f));
        await page.waitForTimeout(800);
        if (genre === 'breakout') await breakout(page, cdp, dev, r); else await towerDefense(page, cdp, dev, r);
        await page.screenshot({ path: path.join(out, key + '.png') });
      } catch (e) { r.notes.push('harness: ' + String(e.message).slice(0, 160)); }
      const video = page.video();
      await ctx.close();
      if (video) { const p = await video.path(); fs.renameSync(p, path.join(out, key + '.webm')); r.video = key + '.webm'; }
      report[key] = r;
      fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 1));
      const flags = genre === 'breakout'
        ? `paddle=${r.paddle_follows} anim=${r.animating} score=${r.score_moved}`
        : `moving=${r.enemies_moving} spent=${r.gold_spent} kills+=${r.kills_rose} gold+=${r.gold_rose} lives-=${r.lives_fell}`;
      console.log(`${key}: ${flags}${r.errors.length ? ' ERR ' + r.errors[0] : ''}`);
    }
  }
  await browser.close();
})();
