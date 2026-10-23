// Open each generated page headless: JS errors, a screenshot at load, then a click + start keys and a second shot.
// node shoot.js runs/   (needs the playwright package)
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const dir = process.argv[2];
  const files = fs.readdirSync(dir).filter(f => f.endsWith('.html')).sort();
  const browser = await chromium.launch();
  const report = {};
  for (const f of files) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    const errors = [];
    page.on('pageerror', e => errors.push(String(e.message).slice(0, 200)));
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 200)); });
    const stem = path.join(dir, f.replace(/\.html$/, ''));
    try {
      await page.goto('file://' + path.resolve(dir, f));
      await page.waitForTimeout(800);
      await page.screenshot({ path: stem + '-load.png' });
      await page.mouse.click(640, 400);
      for (const k of ['Space', 'Enter']) await page.keyboard.press(k);
      const btn = page.getByRole('button').first();
      if (await btn.count()) await btn.click({ timeout: 1000 }).catch(() => {});
      await page.mouse.move(500, 700);
      await page.waitForTimeout(4000);
      await page.screenshot({ path: stem + '-play.png' });
    } catch (e) {
      errors.push('harness: ' + String(e.message).slice(0, 200));
    }
    report[f] = errors;
    await page.close();
  }
  await browser.close();
  fs.writeFileSync(path.join(dir, 'shoot-report.json'), JSON.stringify(report, null, 1));
  console.log(JSON.stringify(report, null, 1));
})();
