#!/usr/bin/env node
/**
 * ?°ìŠ¤? ë¦¬ ê´€ë¦??˜ì´ì§€?ì„œ ê¸€??ì¡°íšŒ/?? œ?˜ëŠ” ?¼íšŒ???´ì˜ ?¤í¬ë¦½íŠ¸.
 *
 *   node scripts/manageTistoryPosts.js inspect 45 43
 *   node scripts/manageTistoryPosts.js delete 45 43
 *
 * GitHub Actions ?ì„œ Secrets ??ì¹´ì¹´??ê³„ì •?¼ë¡œ ?ë™ ë¡œê·¸?¸í•œ ???¤í–‰?œë‹¤.
 * ë¡œê·¸?ëŠ” ë²„íŠ¼/ì²´í¬ë°•ìŠ¤??ë©”í??°ì´?°ë§Œ ?¨ê¸°ê³??˜ì´ì§€ HTML/? í°?€ ì¶œë ¥?˜ì? ?ŠëŠ”??
 */
import { chromium } from 'playwright';
import { tistoryConfig } from '../src/tistoryConfig.js';
import { ensureSession } from '../src/tistoryAuth.js';

const [mode = 'inspect', ...ids] = process.argv.slice(2);
const base = `https://${tistoryConfig.blogName}.tistory.com`;

async function describe(page, label) {
  const items = await page.evaluate(() => {
    const isVisible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
    };
    const rows = [];
    for (const el of document.querySelectorAll(
      'button, a, input[type="checkbox"], select, option, [role="button"], [role="menuitem"]'
    )) {
      rows.push({
        tag: el.tagName.toLowerCase(),
        type: el.getAttribute('type') || '',
        id: el.id || '',
        name: el.getAttribute('name') || '',
        value: el.getAttribute('value') || '',
        text: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 50),
        cls: String(el.className || '').slice(0, 90),
        aria: el.getAttribute('aria-label') || '',
        visible: isVisible(el),
      });
    }
    return rows;
  });
  console.log(`=== ${label} ===`);
  for (const it of items) {
    if (!it.visible) continue;
    console.log(
      `${it.tag}\ttype=${it.type}\tid=${it.id}\tname=${it.name}\tvalue=${it.value}\ttext=${it.text}\taria=${it.aria}\tcls=${it.cls}`
    );
  }
}

async function selectPost(page, id) {
  const box = page.locator(`#inpCheck${id}`).first();
  if (await box.count()) {
    await box.check({ force: true }).catch(async () => {
      await box.click({ force: true }).catch(() => {});
    });
    return true;
  }
  const fallback = page.locator(`input[type="checkbox"][id$="Check${id}"]`).first();
  if (await fallback.count()) {
    await fallback.check({ force: true }).catch(() => {});
    return true;
  }
  return false;
}

async function main() {
  const browser = await chromium.launch({ headless: tistoryConfig.headless });
  const context = await browser.newContext({ storageState: tistoryConfig.paths.storageState });
  try {
    const session = await ensureSession(context);
    console.log(`session=${session.method}`);
    const page = await context.newPage();
    page.setDefaultTimeout(tistoryConfig.timeout);
    page.on('dialog', (dialog) => dialog.accept().catch(() => {}));

    if (mode === 'discover') {
      await page.goto(`${base}/manage`, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(5000);
      const links = await page.evaluate(() =>
        Array.from(document.querySelectorAll('a'))
          .map((a) => ({
            text: (a.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40),
            href: a.getAttribute('href') || '',
          }))
          .filter((item) => item.href)
      );
      console.log('=== links on /manage ===');
      console.log(JSON.stringify(links, null, 2));
      console.log(`url=${page.url()}`);
      console.log(`frames=${page.frames().map((f) => f.url()).join(' | ')}`);

      const candidates = [
        '/manage/post',
        '/manage/posts',
        '/manage/entry',
        '/manage/contents/post',
        '/manage/blog/post',
        '/manage/post/list',
      ];
      for (const candidate of candidates) {
        try {
          await page.goto(`${base}${candidate}`, { waitUntil: 'domcontentloaded' });
          await page.waitForTimeout(2500);
          const checks = await page.evaluate(() => ({
            url: location.href,
            checkboxes: Array.from(document.querySelectorAll('input[type="checkbox"]'))
              .map((el) => el.id)
              .filter(Boolean)
              .slice(0, 5),
            hasPostCheck: !!document.querySelector('[id^="inpCheck"]'),
          }));
          console.log(`candidate ${candidate} -> ${JSON.stringify(checks)}`);
        } catch (err) {
          console.log(`candidate ${candidate} -> error ${err?.message || err}`);
        }
      }
      return;
    }

    if (mode === 'inspect') {
      await page.goto(`${base}/manage/posts`, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(5000);
      await describe(page, '/manage/posts before selection');

      for (const id of ids) {
        const ok = await selectPost(page, id);
        console.log(`select ${id}: ${ok}`);
      }
      await page.waitForTimeout(1500);
      await describe(page, '/manage/posts after selection');

      // 'ë³€ê²? ë¥??œë¡­?¤ìš´???´ì–´ ?¤ì œ ?¡ì…˜ ë©”ë‰´ë¥??•ì¸?œë‹¤.
      for (const name of ['ë³€ê²?, '? íƒ??ê¸€', 'ê¸€ ê´€ë¦?]) {
        const btn = page.getByRole('button', { name }).first();
        if (await btn.count()) {
          await btn.click({ force: true }).catch(() => {});
          await page.waitForTimeout(1000);
          await describe(page, `/manage/posts after click ${name}`);
        }
      }
      return;
    }

    if (mode === 'delete') {
      await page.goto(`${base}/manage/posts`, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(5000);

      let selected = 0;
      for (const id of ids) {
        if (await selectPost(page, id)) selected += 1;
        else console.log(`post ${id}: checkbox not found`);
      }
      if (!selected) {
        console.log('no posts selected; aborting');
        return;
      }
      await page.waitForTimeout(1200);
      await describe(page, 'after selection (delete probe)');

      // ?°ìŠ¤? ë¦¬ ê´€ë¦??”ë©´???¤ì œ ?? œ ë²„íŠ¼?€ "? íƒ??ê¸€ ?? œ"ì²˜ëŸ¼
      // ë¬¸êµ¬ê°€ ê¸¸ê³  btn_delete ?´ëž˜?¤ë? ?´ë‹¤. ?•í™•??"?? œ"ë§?ì°¾ìœ¼ë©??“ì¹œ??
      const del = page.locator('button.btn_delete, a.btn_delete').first();
      const fallbackDel = page
        .locator('button, a')
        .filter({ hasText: /?? œ/ })
        .first();
      const target = (await del.count()) ? del : fallbackDel;
      if (!(await target.count())) {
        console.log('delete control not found; run inspect mode first');
        return;
      }
      await target.click({ force: true });
      await page.waitForTimeout(2000);
      await describe(page, 'after delete click (confirm probe)');

      // ?•ì¸ ?ˆì´?´ê? ?ˆìœ¼ë©??? œ/?•ì¸/??ë²„íŠ¼???„ë¥¸?? ë¸Œë¼?°ì?
      // confirm() ?€ ?„ì˜ dialog ?¸ë“¤?¬ê? ?´ë? ?¹ì¸?œë‹¤.
      const confirm = page
        .locator(
          '.layer_confirm button, .layer_popup button, .modal button, [role="dialog"] button'
        )
        .filter({ hasText: /?? œ|?•ì¸|?? })
        .last();
      if (await confirm.count()) {
        await confirm.click({ force: true }).catch(() => {});
      }
      await page.waitForTimeout(5000);
      console.log(`delete attempted for ${selected} post(s)`);
      console.log(`url=${page.url()}`);
      return;
    }

    console.log(`unknown mode: ${mode}`);
    process.exitCode = 1;
  } finally {
    await browser.close().catch(() => {});
  }
}

main().catch((err) => {
  console.error(`manage failed: ${err?.message || err}`);
  process.exit(1);
});
