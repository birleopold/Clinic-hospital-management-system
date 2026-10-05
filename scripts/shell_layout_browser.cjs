// Reusable first-load/navigation checks. Run only with a disposable staff session.
const assert = require('node:assert/strict');

async function assertShellLayout(page, label) {
  const layout = await page.evaluate(() => {
    const sidebar = document.getElementById('workspace-navigation');
    const topbar = document.querySelector('.workspace-topbar');
    const main = document.getElementById('main-content');
    const label = document.querySelector('label[for="global-patient-query"]');
    const style = element => element ? getComputedStyle(element) : null;
    return {
      shell: document.body.classList.contains('workspace-shell'),
      stylesheets: [...document.querySelectorAll('link[rel="stylesheet"]')].map(link => ({
        path: new URL(link.href).pathname, loaded: Boolean(link.sheet),
        inHead: link.parentElement === document.head, media: link.media,
      })),
      compact: matchMedia('(max-width: 1100px)').matches,
      sidebarPosition: style(sidebar)?.position,
      sidebarDisplay: style(sidebar)?.display,
      sidebarWidth: style(sidebar)?.width,
      topbarDisplay: style(topbar)?.display,
      mainMargin: style(main)?.marginLeft,
      labelWidth: style(label)?.width ?? null,
      overflow: document.documentElement.scrollWidth > innerWidth,
    };
  });
  assert.equal(layout.shell, true, label + ': authenticated shell class');
  const shellSheets = layout.stylesheets.filter(sheet => /\/workspace(?:\.[a-f0-9]+)?\.css$/.test(sheet.path));
  assert.equal(shellSheets.length, 1, label + ': exactly one canonical shell stylesheet');
  assert.equal(shellSheets[0].loaded, true, label + ': stylesheet loaded on first visit');
  assert.equal(shellSheets[0].inHead, true, label + ': render-blocking stylesheet in head');
  assert.equal(shellSheets[0].media, '', label + ': no deferred/print-only shell stylesheet');
  assert.equal(layout.stylesheets.some(sheet => /\/(legacy-shell|suite)(\.|$)/.test(sheet.path)), false, label + ': no old skin');
  assert.equal(layout.topbarDisplay, 'flex', label + ': topbar layout');
  assert.equal(layout.sidebarPosition, 'fixed', label + ': fixed sidebar');
  assert.equal(layout.sidebarDisplay, layout.compact ? 'none' : 'block', label + ': responsive sidebar');
  assert.equal(layout.mainMargin, layout.compact ? '0px' : '220px', label + ': content offset');
  assert.equal(layout.sidebarWidth, '220px', label + ': sidebar width');
  if (layout.labelWidth !== null) assert.equal(layout.labelWidth, '1px', label + ': search label visually hidden');
  assert.equal(layout.overflow, false, label + ': no horizontal overflow');
  return layout;
}

async function verifyShellNavigation(browser, {baseURL, storageState, firstPath, nextPath, contextOptions = {}}) {
  // Cookies authenticate; fresh contexts deliberately carry no HTTP/asset cache.
  const fresh = await browser.newContext({...contextOptions, storageState, viewport: {width: 1440, height: 900}});
  try {
    const page = await fresh.newPage();
    assert.equal((await page.goto(baseURL + firstPath)).status(), 200);
    assert.equal(new URL(page.url()).pathname, firstPath, 'first-load route must not redirect to login');
    await assertShellLayout(page, 'fresh browser first visit');
    // Match the existing navigation target exactly, rather than replacing a real click with goto.
    const target = page.locator(`#workspace-navigation a[href="${nextPath}"]`).first();
    assert.equal(await target.count(), 1, 'navigation target exists');
    await Promise.all([page.waitForURL(url => url.pathname === nextPath), target.click()]);
    const navigated = await assertShellLayout(page, 'ordinary link navigation');
    await page.reload();
    const reloaded = await assertShellLayout(page, 'ordinary reload');
    assert.deepEqual(reloaded, navigated, 'navigation and reload must use the same layout');
    await page.goBack();
    assert.equal(new URL(page.url()).pathname, firstPath);
    await assertShellLayout(page, 'history back');
    await page.setViewportSize({width: 390, height: 900});
    await page.goto(baseURL + firstPath);
    await assertShellLayout(page, 'fresh mobile route');
    await page.getByRole('button', {name: 'Menu', exact: true}).click();
    assert.equal(await page.locator('#workspace-navigation').isVisible(), true, 'mobile menu opens');
    await page.keyboard.press('Escape');
    await assertShellLayout(page, 'mobile menu closed');
  } finally {
    await fresh.close();
  }
  // The new layout must be CSS/server-rendered, not a post-load JavaScript skin.
  const noScripts = await browser.newContext({...contextOptions, storageState, javaScriptEnabled: false, viewport: {width: 1440, height: 900}});
  try {
    const page = await noScripts.newPage();
    assert.equal((await page.goto(baseURL + firstPath)).status(), 200);
    await assertShellLayout(page, 'first visit with JavaScript disabled');
  } finally {
    await noScripts.close();
  }
}

module.exports = {assertShellLayout, verifyShellNavigation};
