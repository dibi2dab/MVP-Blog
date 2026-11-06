#!/usr/bin/env node
/**
 * 티스토리 관리 페이지에서 글을 조회/삭제하는 일회성 운영 스크립트.
 *
 *   node scripts/manageTistoryPosts.js inspect 45 43
 *   node scripts/manageTistoryPosts.js delete 45 43
 *
 * GitHub Actions 에서 Secrets 의 카카오 계정으로 자동 로그인한 뒤 실행한다.
 * 로그에는 버튼/체크박스의 메타데이터만 남기고 페이지 HTML/토큰은 출력하지 않는다.
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

    if (mode === 'inspect') {
      await page.goto(`${base}/manage/posts/`, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(5000);
      await describe(page, '/manage/posts/ before selection');

      for (const id of ids) {
        const ok = await selectPost(page, id);
        console.log(`select ${id}: ${ok}`);
      }
      await page.waitForTimeout(1500);
      await describe(page, '/manage/posts/ after selection');

      // '변경' 류 드롭다운을 열어 실제 액션 메뉴를 확인한다.
      for (const name of ['변경', '선택한 글', '글 관리']) {
        const btn = page.getByRole('button', { name }).first();
        if (await btn.count()) {
          await btn.click({ force: true }).catch(() => {});
          await page.waitForTimeout(1000);
          await describe(page, `/manage/posts/ after click ${name}`);
        }
      }
      return;
    }

    if (mode === 'delete') {
      await page.goto(`${base}/manage/posts/`, { waitUntil: 'domcontentloaded' });
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

      const del = page
        .locator('button, a')
        .filter({ hasText: /^\s*삭제\s*$/ })
        .first();
      if (!(await del.count())) {
        console.log('delete control not found; run inspect mode first');
        return;
      }
      await del.click({ force: true });
      await page.waitForTimeout(1500);
      await describe(page, 'after delete click (confirm probe)');

      const confirm = page
        .locator('button, a')
        .filter({ hasText: /^\s*(삭제|확인|예)\s*$/ })
        .last();
      if (await confirm.count()) {
        await confirm.click({ force: true }).catch(() => {});
      }
      await page.waitForTimeout(4000);
      console.log(`delete attempted for ${selected} post(s)`);
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
